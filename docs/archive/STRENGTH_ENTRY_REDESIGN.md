# Strength Entry Redesign — Design Doc

Scope decision for the `stash@{1}` / `strength-entry-redesign WIP` + `origin/claude/interesting-archimedes-16548a` extraction. Written April 2026.

## Baseline correction

The earlier refactor notes and auto-memory both asserted that live/retro
entry modes + per-set HR attachment already shipped. They did not at the
time this design doc was written. That work lived on
`origin/claude/interesting-archimedes-16548a` and had not yet merged to
`main`. Current `main` at that point had:

- `frontend/src/pages/StrengthEntry.tsx` — flat row-based table; manual
  `set_number` on every row; no timestamps.
- `backend/models/strength.py::StrengthSet` — no `performed_at` column.
- No `backend/services/strength_hr.py`, no HR fields in the session
  summary payload.

The design below assumes that baseline and sequences the two stale sources
as three phased PRs.

## Source 1: `stash@{1}` (pure frontend + CSS)

UX ideas in the stash, each judged against current `main`:

| Idea | Survives? | Notes |
|---|---|---|
| Exercise-grouped **cards** instead of one flat table | ✅ keep | Matches how lifters think ("3 sets of squat, 4 of row"). Makes auto-numbering trivial. |
| Auto-numbered sets within each card | ✅ keep | Removes the manual `set_number` input. Still populated client-side before POST, so backend schema is unchanged. |
| Stepper buttons (±1 reps, ±2.5 kg) | ✅ keep | Big tap targets for gym-floor entry. Pure UI. |
| Prior-performance line per exercise ("Last (Mar 15): 3×5 @ 80 kg · est 1RM 92.7 kg") | ✅ keep | Uses existing `GET /api/strength/progression/{name}` — no new endpoint. |
| Pre-fill from last session button | ⏸ defer | Useful but needs a clear policy for clobbering in-progress rows. Next PR. |
| Draft persistence to `localStorage` | ⏸ defer | Versioning, expiry, cross-tab sync — enough surface area for its own PR. |
| "Save & keep going" mode | ⏸ defer | Minor polish; revisit once cards ship. |
| Mobile-responsive notes-spans-row grid | ✅ keep | Small CSS win; lands with cards. |

Nothing in the stash conflicts with current types or API modules — all the
ideas are frontend-local.

## Source 2: `origin/claude/interesting-archimedes-16548a` (full stack)

| Idea | Survives? | Notes |
|---|---|---|
| `strength_sets.performed_at` column (nullable datetime, naive local) | ✅ keep — **PR 2** | Required for per-set HR slicing and for live-mode stamping. Safe additive migration. |
| Live vs Retro mode toggle | ✅ keep — **PR 2/3** | Lives cleanly on top of the card redesign: "Log set" button lives in the card header / row when mode is live. |
| Rest-timer chip (seconds since last `performed_at`) | ✅ keep — **PR 2/3** | 1 Hz `setInterval`, scoped to live mode. |
| Auto-append next row + focus reps on log | ✅ keep — **PR 2/3** | Maps naturally to cards: "log set" on the last row in the active card adds a new row and focuses its reps input. |
| `backend/services/strength_hr.py` (`_slice_hr_for_set`, `attach_hr_to_sets`, decimator) | ✅ keep — **PR 3** | Read-only: reads cached `activity_streams`, never triggers Strava fetch. Matches the "streams stay lazy" architectural rule. 45 s window, skips 0/None dropouts. |
| `session_summary` emits `hr_curve`, `activity_start_iso`, per-set `avg_hr`/`max_hr` | ✅ keep — **PR 3** | Purely additive to the existing response. Retro sessions render without these fields. Snapshot contract drift test does not cover `/strength` payloads, so keep the `frontend/src/api/strength.ts` types in sync manually. |
| Per-set HR pills + HR curve chart in session detail | ✅ keep — **PR 4** | Gate on `hr_curve != null`; retro sessions stay unchanged. |
| HR zones + cardiac drift helpers in `backend/services/training_metrics.py` (`summarize_hr_zones`, `assign_lap_hr_zones`, `compute_hr_drift`) + `ActivityDetail` auto-stream loading | ⛔ **out of scope** | Separate slice at the time; avoid auto-stream loading because the current architecture keeps Strava streams lazy. |

Conflicts with current `main`:

- The branch imports `fetchActivities` from `../api/client`. Main has
  since split the API barrel; the correct import is
  `../api/activities`. Re-apply carefully.
- Error handling used `catch (e: any)`; we now use `getErrorMessage(e, …)`
  from `utils/errors`.
- Live DB at one point sat on a revision Alembic didn't know about (see
  `memory/alembic_vs_create_all_drift.md`). The `performed_at` migration
  needs a drop-and-retry path if the existing dev DB has already seen
  the column applied via raw SQL.

## Phasing

**PR 1 (this PR) — frontend UX redesign, no schema change.**
- Replace the flat-table `StrengthEntry` with exercise-grouped cards.
- Auto-number sets within each card; compute `set_number` client-side.
- Stepper buttons for reps and weight.
- Prior-performance line per exercise (uses existing progression API).
- Keep date picker + Strava activity link dropdown.
- Update `StrengthEntry.test.tsx` to match the new shape.

**PR 2 — backend `performed_at` + live mode plumbing.**
- Alembic migration adding nullable `strength_sets.performed_at`.
- Router + service accept/round-trip `performed_at`.
- StrengthEntry gains a Live/Retro toggle, per-row "Log set" button,
  and a rest-timer chip. Retro path unchanged.

**PR 3 — backend HR attachment.**
- New `backend/services/strength_hr.py` (45 s window, decimator, cached
  streams only).
- `session_summary` emits `hr_curve`, `activity_start_iso`, per-set
  `avg_hr`/`max_hr` when available.
- Frontend `strength.ts` types grow the new optional fields.

**PR 4 — frontend HR curve + per-set pills in session detail.**
- Add Recharts HR chart above the exercise tables, gated on
  `hr_curve != null`.
- Per-set avg/max HR pill column in the session detail table.

Deferred (not in this design): `localStorage` drafts, "Save & keep going",
pre-fill from last session. Revisit after PR 4.

## Success criteria for PR 1

- Existing `createStrengthSession` POST payload shape is unchanged.
- Existing `fetchStrengthExercises` + `fetchActivities` usage preserved.
- `StrengthEntry.test.tsx` still asserts the save-error fallback path.
- `npm run typecheck`, `npm run build`, and backend `pytest` all pass.
