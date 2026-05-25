# Diagnosis: Issue #51 — Eight Sleep score always shows 79 on Sleep & Recovery detail page

## 1. Symptom restated

When the reporter taps any sleep/recovery row in the History tab, the destination Sleep & Recovery detail page renders an Eight Sleep score of **79** regardless of which historical night was selected. They expect the page to reflect the night they tapped (e.g., 73 last Tuesday, 84 last Thursday). The data in the database is fine and the API response is fine; **the bug is purely a frontend routing/data-fetch issue**: the detail page is unable to render anything except the *latest* Eight Sleep row because it is never told which date to show. The Eight Sleep sync is not implicated — the value "79" is simply the score on the single most recent Eight Sleep row, served back unchanged on every visit.

## 2. Reproduction (read-only)

No date scope is encoded anywhere on the path from History click → `/sleep`:

- `frontend/src/lib/historyEvents.ts:242` builds every sleep history event with `navigateTo: "/sleep"` — no date, no id, no query string.
- `frontend/src/pages/History.tsx:104-106` does a plain `navigate(event.navigateTo!)`.
- `frontend/src/App.tsx:38` registers `/sleep` with no path or search parameter.
- `frontend/src/components/Sleep.tsx:18-25` calls `fetchLatestSleepBySource("whoop"|"eight_sleep")` with no `onOrBefore`.
- `frontend/src/api/sleep.ts:70-76` (`fetchLatestSleepBySource`) builds `/sleep/latest?source=eight_sleep` — no date filter, period.
- `backend/routers/sleep.py:93-123` (`latest_sleep`) without `on_or_before` does `order_by(date.desc()).limit(1)` and returns that one row. Same row every call.

Repro commands (read-only):

```bash
# Both return the identical Eight Sleep row (sleep_score: 79):
curl -s "http://localhost:8000/sleep/latest?source=eight_sleep"
# And after navigating to "history → click June 3 sleep card", the
# browser still fires exactly that request — no date context survives
# the History → /sleep transition.
```

There is no existing automated test that catches this — `frontend/src/components/Sleep.test.tsx` mocks `fetchLatestSleepBySource` once and asserts a render; it never asserts that a date-scoped call is made.

## 3. Ranked hypotheses

### H1 (most likely, **near certainty**): History click drops the selected date; `/sleep` always renders the latest Eight Sleep row

- **Evidence:**
  - `frontend/src/lib/historyEvents.ts:193-243` — `sleepToEvent` hard-codes `navigateTo: "/sleep"` for every row in the history list. The session id, date, and source it has in `s` are thrown away.
  - `frontend/src/components/Sleep.tsx:18-25, 42-52` — `Sleep` ignores `useParams` / `useSearchParams` entirely. It calls `fetchLatestSleepBySource(...)` (no opts) twice and runs `resolveSleepPairForCard(...)` which only ever returns the most-recent pair, or falls back to `latestWhoop` / `latestEight`.
  - `frontend/src/api/sleep.ts:70-76` — `fetchLatestSleepBySource` has no parameter for `on_or_before`. (The sibling `fetchLatestSleep` at `:52-63` *does* accept `onOrBefore`, but the detail page does not use it.)
  - `backend/routers/sleep.py:114-123` — without `on_or_before`, the query returns the single newest Eight Sleep row.
  - `SleepRecoveryDetailsCard.tsx:63` reads `eightSleep?.sleep_score` from whatever row `Sleep.tsx` passed in. That row is invariant across visits, so the rendered score is invariant. The literal "79" matches a real row in the table — nothing in the rendering logic synthesizes the number.
- **Mechanism:** History click → `navigate("/sleep")` → `Sleep.tsx` mounts → fires `GET /sleep/latest?source=eight_sleep` (and the WHOOP one). Backend returns the most recent row (sleep_score = 79). Card paints `Math.round(79) → 79`. Every history row produces the same end state because the destination URL is identical and the API request carries no date.
- **Falsification:** Open DevTools Network panel; click three different sleep rows in History. Observe whether the three resulting `GET /sleep/latest?source=eight_sleep` requests differ in their query string. If they are byte-identical (which they will be), H1 is confirmed. If any of them carries a date hint and the response still always returns the same row, H1 is wrong and the bug is in the backend.

### H2 (very low): Eight Sleep sync has not produced new rows; "latest" is the only row that exists

- **Evidence against:** The reporter said "Eight Sleep score consistently shows 79" — that's a single literal value, which would match a *single row* being returned for every request. Both H1 and H2 are consistent with this. But H1 is consistent for an arbitrarily fresh DB, while H2 would mean every Eight Sleep night for weeks has actually been written with `sleep_score = 79`. That's vanishingly unlikely on a real device.
- **Mechanism:** If `backend/services/eight_sleep_sync.py` stopped writing new rows, then `/sleep?source=eight_sleep&days=30` (which `Sleep.tsx` also calls) would return a list of just the latest row plus older rows, and `resolveSleepPairForCard` might still always pick that same one. But the user's first known-issue list in `CLAUDE.md` already mentions data refresh as suspect, so it's worth quickly checking the DB once.
- **Falsification:** `curl -s "http://localhost:8000/sleep?source=eight_sleep&days=30" | jq '[.[].sleep_score]'`. If the list contains varied scores like `[79, 82, 75, 84, ...]`, sync is healthy and the bug is purely H1. If it returns one row or many identical 79s, sync is broken (separate bug — track via the broader "data not refreshing" issue, not this one).

### H3 (low): Sleep.tsx caches by source key only; switching dates would still hit a stale cache

- **Evidence:** `frontend/src/components/Sleep.tsx:19-25` keys `useApi` with `["sleep", "latest-by-source", "whoop"]` and `["sleep", "latest-by-source", "eight_sleep"]` — no date in the key. This is only *latent*: even if H1 were fixed by adding a date to the URL, the cache key must also include the date or `useApi` would return the previously cached row for a different night.
- **Mechanism:** TanStack Query keys on the array passed to `useApi`. If a future fix passes `onOrBefore` to the fetcher but doesn't include the date in the key, all dates would still return the first cached payload.
- **Falsification:** Not relevant on current `main` — irrelevant until H1 is fixed. Flag it as part of the fix's regression-test plan.

### H4 (very low): `/sleep` consumes a stale TanStack cache from a previous visit

- **Evidence:** Same useApi key analysis. But for the reporter's symptom to be explained purely by cache, every fresh tab / hard refresh / cold load would also have to surface 79. The simpler "no date in URL" explanation already covers all observations, so H4 is subsumed by H1.

### H5 (negligible): Backend `latest_sleep` is silently dropping a date param

- **Evidence:** None. `backend/routers/sleep.py:93-123` plumbs `on_or_before` directly into the SQL. The frontend never sends it.

## 4. Recommended fix

**H1 is the bug.** Minimum-scope frontend-only fix; no backend change, no migration.

Change shape:

1. **Encode the night on the History event** — in `frontend/src/lib/historyEvents.ts:193-243`, build `navigateTo` as a date-scoped URL: `` `/sleep?date=${s.date}` ``. (`s.date` is already on the `SleepSession` and is ISO `YYYY-MM-DD`.)
2. **Read the date in the Sleep page** — in `frontend/src/components/Sleep.tsx`, parse `useSearchParams().get("date")`. Default to "latest" when absent so the existing dashboard-tap entry point (`MorningStatusCard.tsx:25`, which passes `undefined` for today) keeps working.
3. **Plumb the date to the API call** — replace the two `fetchLatestSleepBySource(source)` calls in `Sleep.tsx:20, 24` with `fetchLatestSleep({ source, onOrBefore: dateParam })` (already exists at `frontend/src/api/sleep.ts:52-63`). Drop `fetchLatestSleepBySource` if it has no other callers (grep confirms only `Sleep.tsx` + its test reference it).
4. **Include the date in the useApi cache key** — `["sleep", "latest", source, dateParam ?? "latest"]`. Closes H3.
5. **Recovery window** — `fetchRecovery(14)` returns a list narrowed by `pickRecoveryForSleeps`. When deep-linking to a night > 14 days back, the recovery cross-fill currently falls through to today's row. Either widen the lookback or anchor it to `dateParam`. Include `dateParam` in that cache key as well.
6. **Pairing pass** — `resolveSleepPairForCard` and `mergeSleepSessions` need no rewrite; they operate on whatever rows the (now date-scoped) fetch returns.

Files that change:

- `frontend/src/lib/historyEvents.ts` — change line 242.
- `frontend/src/components/Sleep.tsx` — read query param, swap fetch calls, fix cache keys.
- (Optional) `frontend/src/api/sleep.ts` — delete now-unused `fetchLatestSleepBySource`, or leave it.
- Tests below.

No backend change, no DB migration. `/sleep/latest?on_or_before=` already exists.

**Required new / updated tests** (all frontend, Vitest):

- `frontend/src/lib/historyEvents.test.ts` — "sleepToEvent encodes the row's date in navigateTo": build an event from a row with `date: "2025-05-12"`, assert `navigateTo === "/sleep?date=2025-05-12"`. Must fail on `main`.
- `frontend/src/components/Sleep.test.tsx` — render `<Sleep />` under `<MemoryRouter initialEntries={["/sleep?date=2025-05-10"]}>`, mock `fetchLatestSleep` and assert it was called with `{ source: "eight_sleep", onOrBefore: "2025-05-10" }`. Must fail on `main`.
- Cache-key regression (closes H3): render twice with two different `?date=` values; assert that the mock fetch is called twice with the two different `onOrBefore` values.

**Migration required?** No.

## 5. Out-of-scope cleanup spotted

- `resolveSleepPairForCard` in `Sleep.tsx:117-140` is only useful when there is no anchor date. Once date-scoped, the pairing logic should anchor on the requested date directly rather than the newest row. Worth tightening, but a non-blocker.
- `frontend/src/api/sleep.ts:70-76` exports `fetchLatestSleepBySource(source)` that is essentially `fetchLatestSleep({ source })`. After the fix, it becomes dead code (and a footgun encouraging callers to skip `onOrBefore`).
- `SleepRecoveryDetailsCard.tsx:55-57` derives a "header date" from `pickLatestDate(...)`. On a date-scoped detail page the rendered header could disagree with the requested URL date by ±1 day. Cosmetic.
- `Sleep.tsx:27-28` requests only `fetchRecovery(14)`. Deep-linking to a night > 14 days back will silently fall through to today's recovery row.
- `MorningStatusCard.tsx:25` already knows the `onOrBefore` pattern. The two surfaces (dashboard + history-deep-link) should share one tiny helper so this kind of drift doesn't recur.
- `historyEvents.ts:258-263` sleep dedup-by-date prefers `eight_sleep` over `whoop`, but `sleepToEvent` only encodes one source. After the fix, verify neighbor-matching still works when the kept Eight row has its WHOOP counterpart on the same night.
