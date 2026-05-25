# Sleep Stages Card UI Improvement

## 1. Goal
Replace the cluttered Sleep Stages card on the Sleep & Recovery details page with a cleaner layout that shows total sleep duration + bed-time → wake-time labels above each source's stacked bar, in-segment percentage labels inside the stacked bars (with tooltip fallback for narrow segments), and a simplified comparison table where each source cell shows only its raw duration (no parenthetical percentage). The Δ column keeps its existing relative-percent diff. No backend, no API contract, no DB changes — single-component frontend tweak.

## 2. Affected surfaces

| Surface | Change | Files |
|---|---|---|
| `frontend/src/components/sleep/` | Edit single component: new bar header rows (total duration + bed→wake), new in-segment labels, simplified table cells, new `formatClockTime` helper | `frontend/src/components/sleep/SleepRecoveryDetailsCard.tsx` |
| `frontend/src/components/sleep/` | Tests for new behavior + update existing assertions that depend on `(NN%)` in source cells | `frontend/src/components/sleep/SleepRecoveryDetailsCard.test.tsx` |
| `frontend/src/api/sleep.ts` | No code change. Reference only — confirms `bed_time` / `wake_time` / `total_duration` are already on `SleepSession` | (no change) |

## 3. Data model
**None.** No new tables, columns, indexes, or backfills. Reads only fields already present on the `SleepSession` interface (`bed_time`, `wake_time`, `total_duration`, `deep_sleep`, `rem_sleep`, `light_sleep`, `awake_time`).

## 4. External integration
**None — frontend-only change.** No external APIs touched, no integration-researcher needed.

## 5. Backend tasks
**None — frontend-only change.**

## 6. Frontend tasks
All edits inside `frontend/src/components/sleep/SleepRecoveryDetailsCard.tsx`. Ordered, small.

1. **Add `formatClockTime` helper** near the other formatters at the bottom of the file.
   - Signature: `formatClockTime(iso: string | null | undefined): string | null`.
   - Returns `null` if `iso` is missing or `Date` parse yields `NaN`.
   - Otherwise returns `Date.prototype.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })` style output (e.g. `11:14 PM`).

2. **Add `formatBedWakeRange` helper** (small composer) — returns a single string `"11:14 PM ─── 6:42 AM"` from a `SleepSession | null`. Returns `null` if either `bed_time` or `wake_time` is missing/unparseable, so callers can skip rendering the range entirely. Use an en-dash or em-dash (engineer's choice — `─` U+2500 or `–` U+2013 work; pick one that renders cleanly).

3. **Bar header row per source** (replaces the current single-line `{whoopColumnLabel}` / `{eightSleepColumnLabel}` row above each bar):
   - Left side: source label (existing styling — `text-slate-300` for WHOOP, `text-sky-400` for Eight).
   - Right side: a small **stat strip** combining total sleep duration and the bed→wake range, separated by a thin dot/middot. Shape:
     `<total duration> · <bed time> ─── <wake time>`
     Example: `6h 48m · 11:14 PM ─── 6:42 AM`.
     - Total duration comes from `formatDurationMinutes(whoopSleep?.total_duration)` (existing helper); render only if non-null.
     - Bed/wake range comes from `formatBedWakeRange(...)`; render only if non-null.
     - If both are present, join with ` · ` separator. If only one is present, render just that one. If neither is present, omit the right side entirely.
   - Use `text-[10px]`, `tabular-nums`, `text-slate-400` on the right side. Keep the existing `flex justify-between` container.

4. **Bump bar height** from `h-4` to `h-5` (20px) on both the populated and empty-state bar containers so percentage labels have room. Keep `rounded-full overflow-hidden gap-0.5` and `min-w-[2px]` segment behavior.

5. **In-segment percentage labels** in each of the four segment `<div>`s for both bars (Deep / REM / Light / Awake). Refactor each segment to:
   - Add `flex items-center justify-center` to the segment div so the text centers.
   - Render a child `<span>` with `text-[10px] tabular-nums font-semibold text-white leading-none` (engineer may downshift to `text-[9px]` if `text-[10px]` overflows during visual QA).
   - Set `title={\`${stageLabel} ${pct}%\`}` (e.g. `"Deep 22%"`) on the segment div so tooltips work on hover and the value is keyboard/screen-reader reachable. Also set `aria-label` with the same string.
   - Render the visible span **only when `pct >= 8`** (initial threshold — engineer may tune after eyeballing). When suppressed, keep the `title` / `aria-label` so the value is still reachable on hover/tap.

6. **Simplify comparison table source cells**: drop the `<span className="text-[10px] text-slate-500 ml-1">({pct}%)</span>` fragment so the cell renders only `<span className="text-xs font-bold text-white">{formatStageCell(...)}</span>` (or the `—` placeholder when stages are missing). Leave the wrapping `<div className="text-right">` and `—` fallback path unchanged.

7. **Visual sanity passes** (no code change, exploratory): confirm the bar still sums to 100% width, gaps are visible, percentage labels don't collide with neighbors, and the new bar header row fits on a 360px-wide mobile screen without wrapping. Adjust label-show threshold if needed.

## 7. Migration tasks
**None — frontend-only change.**

## 8. Tests to add / update
File: `frontend/src/components/sleep/SleepRecoveryDetailsCard.test.tsx`.

- **Add — total duration + bed→wake string renders for each source when all three are present.** Mount with a `whoopSleep` whose `bed_time` is `"2026-05-24T23:14:00"`, `wake_time` is `"2026-05-25T06:42:00"`, and `total_duration` is `408` (i.e. 6h 48m). Assert the rendered output contains `"6h 48m"`, `"11:14 PM"`, and `"6:42 AM"` within the WHOOP bar header. Repeat for `eightSleep`.
- **Add — total duration shown without bed/wake when bed_time is null.** Mount with `bed_time: null`, `wake_time: <valid>`, `total_duration: 408`. Assert `"6h 48m"` is present but `"PM"` / `"AM"` are not present *next to that source's bar* (scope the query to the WHOOP header region).
- **Add — bed/wake shown without total duration when total_duration is null.** Mount with `total_duration: null`, valid bed/wake. Assert times appear but `"6h"` is not in the header region.
- **Add — entire right-side strip omitted when total_duration AND bed/wake are all null.** No broken `"·"` or `"—:—"` artifacts.
- **Add — 12-hour formatting.** Use a known time and assert `"AM"` or `"PM"` appears in the bar header row (scope the query to the WHOOP header container).
- **Add — in-segment percentage label appears for wide segments.** Provide stages where Light is ~50% and assert a `"50%"` text node is rendered inside the bar segment.
- **Add — narrow segments suppress visible label but expose `title`.** Provide stages where Awake is ~2%. Assert no visible `"2%"` text node within the bar, but the segment element has a `title` attribute containing `"Awake"` and `"2%"`.
- **Update — comparison table no longer renders `(NN%)`.** Replace any existing `expect(... "(31%)")` (or similar parenthetical-percent) assertions with assertions that the cell contains only the bare duration string (e.g. `"1h 12m"`, `"22m"`) and explicitly assert `queryByText(/\(\d+%\)/)` returns null within the stage comparison table region.
- **Keep — existing assertions on `Δ` column, stage names, dot colors, and `—` placeholders** should continue to pass unchanged. Spot-check during the run.

## 9. Parallelism plan
Only two agents in play — no backend, no DB, no integration research.

```
phase 1 (single agent):
  - frontend-engineer  → edits SleepRecoveryDetailsCard.tsx (helpers, bar headers
                         with total + bed/wake, in-segment labels, simplified
                         table cells) and SleepRecoveryDetailsCard.test.tsx.

phase 2 (sequential, depends on phase 1):
  - test-runner        → runs vitest + npm run typecheck + npm run build.
  - code-reviewer + qa-verifier (parallel) → review the diff and confirm visuals.

NOT needed: integration-researcher, db-migrator, backend-engineer.
```

## 10. Risks and rollback
- **Risk: visual regression on narrow phones.** The new right-side strip is denser (`6h 48m · 11:14 PM ─── 6:42 AM`). On 320px-class screens it may wrap. Engineer should screenshot at 360px and 320px and shorten the separator (or drop the dashed connector to a single en-dash) if it wraps.
- **Risk: percentage-label threshold mis-tuned.** Some users' Awake or Deep is sub-5%. Mitigation: `title` attribute always present; threshold is a single literal we can tune.
- **Risk: stale string assertions.** Removing the `(NN%)` parenthetical will break any test that grepped for `"(31%)"`-style substrings — update in the same PR.
- **Risk: `toLocaleTimeString` locale drift.** CI nodes default to `en-US`, but `formatClockTime` should pass `"en-US"` explicitly so output is stable across machines.
- **Risk: `bed_time` / `wake_time` stored as naive local vs UTC `Z`.** Per `AGENTS.md`, Eight Sleep stores bed/wake as naive local. Browser `new Date(naive)` interprets as local time, which is correct for display. If WHOOP rows carry a `Z` suffix they'd be shifted by browser TZ — flag as a follow-up if observed during QA.
- **Rollback:** single-file revert of `SleepRecoveryDetailsCard.tsx` + its test file. No migration to undo.

---

Files touched (absolute paths):
- /home/user/Health-tracker/frontend/src/components/sleep/SleepRecoveryDetailsCard.tsx
- /home/user/Health-tracker/frontend/src/components/sleep/SleepRecoveryDetailsCard.test.tsx
