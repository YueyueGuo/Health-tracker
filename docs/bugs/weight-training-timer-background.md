# Bug diagnosis — strength workout timer stops in background

Surface: frontend (PWA), `/record` page strength workout timer.
Issue source: user report (inline; no GitHub issue number provided).

## 1. Symptom restated
On the manual weight-training entry screen (`/record`), the workout timer in the header advances correctly while the page is in the foreground but appears to **stop or fall behind** when the user switches to another app or the device screen sleeps. When the user returns, the displayed elapsed time reflects only the time the tab was actually active, not the true wall-clock duration since they hit Start (or logged their first set). Expected behavior: once started, the timer should track real elapsed time continuously regardless of tab focus or screen state.

## 2. Reproduction (read-only, no test exists yet)
There is no existing regression test for tick-vs-wallclock behavior. `frontend/src/pages/Record.test.tsx` covers rendering, set logging, draft persistence, and superset grouping, but never asserts that `elapsed` matches wall-clock time after a simulated background interval.

Manual repro path (without running anything):
1. Load `/record`.
2. Click Start (or enter reps/weight on Set 1 and tap the complete checkmark — `Record.tsx:444` auto-starts).
3. Switch to another tab (desktop) or background the PWA / let the screen sleep (mobile).
4. Wait 60 s.
5. Return. The header clock reads less than 60 s — often 5–20 s on desktop (Chrome throttles background `setInterval` to ~1 Hz then to ~1/minute after 5 min; Safari/iOS PWAs may suspend the JS context entirely).

Programmatic repro available with `vi.useFakeTimers()`: advance `Date.now()` by 60 000 ms **without** running pending timers, and the rendered `elapsed` stays at whatever value the last tick stamped — proving the displayed value is a function of tick count, not wallclock.

## 3. Ranked hypotheses

### H1 (most likely — confirmed by code reading): `elapsed` is incremented purely by an in-tab `setInterval`, with no wall-clock catch-up while the component stays mounted.
- **File**: `/home/user/Health-tracker/frontend/src/pages/Record.tsx`
- **Lines**:
  - `282`: `const [elapsed, setElapsed] = useState(initialDraft.elapsed);`
  - `310–314`: the timer effect:
    ```
    useEffect(() => {
      if (!isRunning) return;
      const id = window.setInterval(() => setElapsed((s) => s + 1), 1000);
      return () => window.clearInterval(id);
    }, [isRunning]);
    ```
  - `502`: the value is passed verbatim into `<SessionHeader elapsed={elapsed} ... />`.
  - `SessionHeader.tsx:14–18, 37`: `formatTime(elapsed)` renders `MM:SS` directly from this counter.
- **Mechanism**: `elapsed` is a pure tick-driven accumulator. Browsers throttle `setInterval` in backgrounded tabs (Chrome down to once/minute after 5 minutes, often more aggressively for low-priority pages; Safari/iOS suspend JS in backgrounded PWAs). On mobile, when the screen sleeps the WebView is paused. While the page stays mounted (no unmount/reload), nothing else writes to `elapsed`, so the counter under-counts by exactly the suppressed time. There is **no `visibilitychange` listener, no Page Lifecycle handling, no Wake Lock request, and no derivation of `elapsed` from a stored start timestamp** anywhere on this page.
- **Falsification**: if `elapsed` were derived from `Date.now() - startMs`, the displayed value would correct itself on every tick (or at minimum when the tab regains focus). It does not, so H1 stands.

### H2 (partially confirmed but only mitigates page-reload, not backgrounding): the localStorage loader at `loadRecordDraft` already does wallclock catch-up, but only runs on mount.
- **File**: `/home/user/Health-tracker/frontend/src/pages/Record.tsx`
- **Lines**:
  - `56–86` `loadRecordDraft` reconstructs `elapsed` as `storedElapsed + floor((Date.now() - savedAt) / 1000)` when `wasRunning`.
  - `300–307` the persistence effect intentionally **omits `elapsed` from its dependency list** — comment at 295–299 says this is on purpose so we don't churn localStorage at 1 Hz. The dependencies are `[date, exercises, isRunning]`. The eslint react-hooks rule would normally flag this; in any case the closure captures whatever `elapsed` is at the time `isRunning` flips.
- **Mechanism**: the wallclock catch-up only fires when `Record` re-mounts (i.e., user navigates away and back, or fully reloads). If the user just backgrounds the app and returns without the component unmounting, the catch-up never runs. Worse: `savedAt` is only refreshed when `[date, exercises, isRunning]` change — so a snapshot can be hours stale by the time it's read. There is also a subtle correctness gap: when the user pauses (`isRunning: true → false`), the persistence effect re-runs and saves the **current in-memory `elapsed`** — which itself under-counts if the tab was backgrounded immediately before the pause. So even the existing reload-recovery path is wrong when the user backgrounds, then returns, then pauses, then leaves and returns.
- **Falsification**: a test that mounts `Record`, sets `isRunning: true`, advances `Date.now` by 60 s without advancing timers, then unmounts and remounts — should show `elapsed >= 60` (loader catch-up works). Same test without unmount/remount would currently show `elapsed ~= 0` (background bug remains).

### H3 (likely false but worth listing): the workout `started_at` sent to the server is itself wrong.
- **File**: `/home/user/Health-tracker/frontend/src/pages/Record.tsx`
- **Lines**:
  - `288` state `startedAt: string | null`.
  - `318–322` stamped to `toNaiveLocalIso(new Date())` the first time `isRunning` flips true.
  - `487` posted as `started_at` on save.
- **Mechanism**: `startedAt` is captured from real wallclock (`new Date()`), so the **persisted** session duration on the backend (`ended_at − started_at`) will be correct regardless of UI ticks. This means the saved session is fine; only the **on-screen timer** is wrong. Also note `startedAt` is *not* persisted to localStorage in the draft snapshot — so if the user reloads mid-workout, `startedAt` becomes `null` again and is re-stamped on the next user action. That is a separate latent bug (see §5), not the one the user is reporting.
- **Falsification**: the user's complaint is about the on-screen counter, not "my saved workout duration was wrong." H3 is not the reported bug.

### H4 (speculative): rest timer is also affected.
- `Record.tsx:324–328` and `341–344` compute `restSeconds` from `now - lastLoggedAt`, where `now` is updated by another `setInterval`. The `lastLoggedAt` source-of-truth is a real timestamp (`performed_at`), so this timer self-corrects on every tick that *does* fire. Backgrounded, the rest chip will freeze, but it will jump to the correct value the moment a tick fires after foregrounding. So the rest timer is less broken than the workout timer, but it would still benefit from a `visibilitychange` nudge.

**Conclusion**: H1 is the root cause. H2 explains why "leave and come back via navigation/reload" partially works today and why naive users might have thought the timer was OK in some scenarios.

## 4. Recommended fix

**Hypothesis to act on**: H1.

**Minimum-scope fix** (all in `/home/user/Health-tracker/frontend/src/pages/Record.tsx`, plus the small `SessionHeader` prop already in place — no API or schema change):

1. **Make `startedAt` the timer's source of truth, not `elapsed`.** Today `startedAt` is a *display-string* (naive-local ISO) used only at save-time. Add a sibling epoch-ms field — call it `startedAtMs: number | null` — set the same time `startedAt` is set (lines 318–322).
2. **Derive `elapsed` from `Date.now() - startedAtMs`** (plus a frozen-at-pause offset to support pause/resume). Concretely: keep an `accumulatedSecs` integer for time accrued during previous run-segments, and when running, `displayedElapsed = accumulatedSecs + floor((now - startedAtMs) / 1000)`. The existing `now`-state interval at lines 325–328 (rest timer) can double as the re-render driver — no second interval needed. The interval is then **purely a re-render trigger**; even if it's throttled, the next tick computes the correct value from wallclock.
3. **Persist `startedAtMs` and `accumulatedSecs` to localStorage** so background-eviction and reload are both handled by the same code path. Replace the loader's `storedElapsed + floor((Date.now() - savedAt) / 1000)` fudge (lines 71–76) with a true reconstruction from `startedAtMs + accumulatedSecs`.
4. **Add a `visibilitychange` listener** that forces a re-render (e.g., `setNow(Date.now())`) when the tab becomes visible again. This snaps the timer to correct value immediately rather than waiting up to a second for the next tick.
5. **Optional: request a Screen Wake Lock while `isRunning`** (`navigator.wakeLock.request("screen")`, release on pause / unmount / `visibilitychange → hidden`). This addresses the screen-sleep case for users who keep the app foregrounded. Feature-detect — Wake Lock is HTTPS-only and unavailable on some browsers; failures must be swallowed silently. This is a UX improvement, not a correctness fix; ship it together since it's small.

**Files that must change**:
- `/home/user/Health-tracker/frontend/src/pages/Record.tsx` — state shape, timer effects, persistence loader & saver, visibilitychange listener, optional wake-lock hook call.
- (No change required to `SessionHeader.tsx` — it already accepts an `elapsed: number` prop.)
- If a Wake Lock helper hook is preferred: new file `/home/user/Health-tracker/frontend/src/hooks/useWakeLock.ts`.

**New / updated tests** (in `/home/user/Health-tracker/frontend/src/pages/Record.test.tsx`, or a sibling pure-logic test if the elapsed-derivation is extracted into a hook/util):
- **`timer survives a backgrounded interval (regression for #<bug-id>)`**: with `vi.useFakeTimers({ shouldAdvanceTime: false })`, mount `Record`, click Start, then mock `Date.now()` to return start+60 000 without running queued timers (simulating a paused tab), then advance one tick — the header MM:SS must read `01:00`, not `00:00`/`00:01`. This directly asserts the source-of-truth swap.
- **`pause then resume accumulates wall-clock-correct elapsed`**: start → advance wallclock 30 s with timers running → pause → advance wallclock 5 minutes with timers running → resume → advance another 10 s → assert `elapsed == 40`. Today this passes only because `setInterval` is faithful in tests; with the new logic, the explicit wallclock-mock variant must also pass.
- **`mount restoration uses persisted startedAtMs, not stale elapsed`**: prime localStorage with `{ startedAtMs: now − 120 000, accumulatedSecs: 0, isRunning: true }`, mount, assert header shows `02:00`. Update the existing "restores an in-progress draft" test (line 102) to use the new schema.
- **`visibilitychange triggers a recompute`**: dispatch a `visibilitychange` event with `document.visibilityState = "visible"` after mocking `Date.now` forward, assert the rendered `elapsed` updates without waiting for the next tick.
- **(Optional)** unit-test the pure `computeElapsedSeconds({ startedAtMs, accumulatedSecs, isRunning, now })` if extracted — easier to mock than the integration test.

**Migration**: none. No backend or schema change. The new localStorage shape should bump the draft key (e.g., `health-tracker:record-draft:v2`) or the `version` field (currently `1` at `Record.tsx:46`) so v1 snapshots get discarded cleanly rather than mis-parsed.

## 5. Out-of-scope cleanup spotted (do not include in fix PR)
- **`Record.tsx:300–307` has an intentional missing-dependency on `elapsed`** with a paragraph-long comment. After the fix, this whole save-only-on-transitions trick becomes unnecessary — persistence can include `startedAtMs`/`accumulatedSecs` since they only change on user action. Worth a follow-up pass to delete the workaround and let the loader become a straight read.
- **`startedAt` (naive-local ISO at `Record.tsx:288`) is never persisted to localStorage.** If a user reloads mid-workout, `startedAt` becomes `null` and the next stamp will use the reload time, not the true start — the saved session's `started_at` will be wrong by however many minutes/hours the user had been training. The fix above will incidentally cover this if `startedAt` is recomputed from the persisted `startedAtMs` on load, but call it out as a deliberate correctness fix in the PR description.
- **Two separate `setInterval`s, one for `elapsed` and one for `now` (lines 310 and 325).** After the refactor only one is needed; the `now`-driven re-render handles both displays.
- **`autoStartIfIdle` (line 349) and `toggleSetComplete` (line 444) both auto-start the workout** on first set input — slightly different conditions (`isRunning || elapsed !== 0` vs `!isRunning && elapsed === 0`). Worth unifying with a single `ensureStarted()` helper to avoid drift; not user-visible today.
- **`Record.tsx:274` recomputes `today` on every render**: `new Date().toISOString().slice(0, 10)`. Fine in practice but a minor wart — `useMemo` or move into the `useState` initializer.
- **No `useWakeLock`-style hook exists** even though Wake Lock would also be useful on the running/cycling Record screens if such manual flows ever exist. Not in scope for this bug, but if introduced for strength, parameterize it.

---

Relevant absolute file paths:
- `/home/user/Health-tracker/frontend/src/pages/Record.tsx` (root-cause site)
- `/home/user/Health-tracker/frontend/src/components/record/SessionHeader.tsx` (display, no change needed)
- `/home/user/Health-tracker/frontend/src/pages/Record.test.tsx` (test home for regression)
- `/home/user/Health-tracker/frontend/src/components/record/datetime.ts` (`toNaiveLocalIso` already used; keep for `started_at` payload)
