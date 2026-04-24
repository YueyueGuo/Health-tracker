# Refactor Findings And Next Steps

Current as of the strength-entry-redesign / HR-attachment / snapshot-drift /
manual-cleanup pass on April 24, 2026.

## Current Baseline

- GitHub default branch is `main`.
- Local workspace was clean on `main` tracking `origin/main` after PR #13
  merged as `94937dc`.
- Latest broad verification from the refactor sprint:
  - Backend targeted time-helper suite: 113 passed.
  - Frontend Vitest suite: 31 passed.
  - Frontend typecheck: passed.
  - Frontend build: passed with route chunks and no previous >500 kB warning.
- CI exists in `.github/workflows/ci.yml` and runs backend Ruff + pytest and
  frontend typecheck + build.

## Original Findings

Short version of the queue this refactor sprint worked through:

- PATCH clear-null semantics for goals and locations were ambiguous.
- Ruff cleanup and CI were missing from the refactor baseline.
- Frontend API calls were concentrated in an overloaded `client.ts`.
- Settings, goals, and location UI were too large and duplicated search/GPS
  flows.
- Dashboard insight snapshot contracts were implicit and easy to drift.
- Backend date/time handling mixed direct wall-clock calls with business logic.
- Insight and training snapshot modules were too large.
- Frontend insight and activity payload types were loose.
- Frontend test coverage existed only in small pockets.
- Legacy chat analysis duplicated newer structured insights.
- Vite build warned about a large frontend bundle.
- Preserved stashes and old remote branches needed audit before cleanup.

## Resolved

### PATCH Semantics

- `backend/routers/goals.py` now uses `payload.model_fields_set`, so explicit
  `{"description": null}` clears the description while omitted fields stay
  unchanged.
- `backend/routers/locations.py` now uses `payload.model_fields_set`, so
  explicit `{"elevation_m": null}` clears elevation while omitted elevation
  stays unchanged.
- Regression coverage lives in:
  - `tests/test_routers/test_goals.py`
  - `tests/test_routers/test_locations.py`

### Ruff And CI

- `.venv/bin/ruff check .` was made clean during the sprint.
- CI now runs backend Ruff + pytest and frontend typecheck + build on
  pushes/PRs to `main`.

### Frontend API Refactor

- Added shared HTTP helper: `frontend/src/api/http.ts`.
- Split the overloaded API barrel into domain modules:
  - `activities.ts`
  - `chat.ts`
  - `dashboard.ts`
  - `recovery.ts`
  - `summary.ts`
  - `sync.ts`
  - plus the existing feedback, goals, insights, locations, sleep, strength,
    and weather modules.
- `frontend/src/api/client.ts` is now only a compatibility barrel. New UI
  imports should use domain modules directly.

### Location And Settings UI

- Shared location search and GPS flows now live in:
  - `frontend/src/hooks/useDebouncedLocationSearch.ts`
  - `frontend/src/hooks/useCurrentPosition.ts`
  - `frontend/src/components/location/LocationSearchForm.tsx`
  - `frontend/src/components/location/GpsLocationForm.tsx`
  - `frontend/src/components/location/SavedLocationPicker.tsx`
- Settings is now composition around `GoalsSection` and
  `LocationSettingsSection`.
- Goal and location CRUD were decomposed into smaller hooks/components:
  - `useGoals.ts`
  - `useLocations.ts`
  - `components/settings/*`
- `LocationPicker.tsx` reuses the shared saved-location picker and location
  hook.

### Snapshot Contracts And Insight Module Split

- Added backend Pydantic snapshot contracts in
  `backend/services/snapshot_models.py`.
- Snapshot builders still return dicts for public API stability, but now
  validate assembled payloads before returning.
- Added an explicit backend/frontend snapshot type-sync checklist to:
  - `backend/services/snapshot_models.py`
  - `frontend/src/api/insights.ts`
- Split training and insight logic into focused modules:
  - `training_load_snapshot.py`
  - `sleep_recovery_snapshot.py`
  - `workout_snapshot.py`
  - `goals_feedback_snapshot.py`
  - `insight_schemas.py`
  - `insight_prompts.py`
  - `insight_cache.py`
- Preserved stable public imports from `backend.services.training_metrics` and
  `backend.services.insights`.

### Date And Time Handling

- Added `backend/services/time_utils.py` with:
  - `local_today()`
  - `utc_now()`
  - `utc_now_naive()`
- Eliminated backend/test `datetime.utcnow()` call sites.
- Added deterministic `today` parameters where analytics windows need them.
- Route-level user-visible windows now use shared helpers:
  - sleep list
  - recovery list and `/today`
  - insight feedback stats
  - weekly summary defaults
  - free-form analysis context
- Sync/client/classifier call sites with clear semantics now use shared
  helpers:
  - Strava sync logs, enrichment timestamps, and mutable-list lookback.
  - Eight Sleep local-date windows and sync logs.
  - Whoop default UTC windows.
  - Classifier persisted timestamps.
- Remaining direct wall-clock calls are tests or deliberate non-date-window
  code such as token-expiry checks.

### Frontend Types And Tests

- Tightened insight API types in `frontend/src/api/insights.ts`.
- `ActivityDetail.weather` and `raw_data` now use `Record<string, unknown>`.
- Removed remaining non-test frontend `any` escapes in the main chat, strength,
  sleep, and weekly-summary surfaces.
- Added Vitest + React Testing Library.
- Current frontend coverage includes:
  - shared HTTP helper
  - location hooks/forms
  - `LocationPicker`
  - `GoalsSection`
  - `Settings`
  - `ActivityDetail` lazy insight/stream states
  - `ChatPanel` error fallback
  - `StrengthEntry` save errors
  - `Dashboard`
  - `TrainingLoad`
- `TrainingLoad.tsx` treats the backend no-activity training-load payload
  (zero-valued CTL/ATL/TSB with empty `daily_load`) as a no-data state instead
  of rendering blank chart shells.

### Legacy Chat Consolidation

- Removed unused `/api/chat/daily-briefing`.
- Removed `/api/chat/workout/{id}` and rewired Activity Detail workout analysis
  to `/api/insights/latest-workout?activity_id={id}`.
- `AnalysisEngine` now handles free-form Q&A only.
- Frontend `chat.ts` now exposes only `askQuestion` and
  `fetchAvailableModels`.
- `tests/test_routers/test_chat.py` covers the remaining chat endpoints and
  404s for removed paths.

### Bundle Splitting

- `frontend/src/App.tsx` now lazy-loads route components with `React.lazy()`
  and wraps route elements in `Suspense`.
- `npm run build` now emits route chunks and no longer reports the previous
  >500 kB chunk warning.

### Snapshot Contract Drift Test

Evaluated a full Pydantic → TypeScript codegen pipeline (OpenAPI export,
`json-schema-to-typescript`, `datamodel-code-generator`). Rejected for this
repo: the snapshot surface is ~21 small interfaces, the API returns plain
dicts (not Pydantic responses) so OpenAPI export would not cover it
cleanly, and generated types would still need a hand-written wrapper layer
for the fetcher helpers.

Landed a lightweight drift detector instead:

- `tests/test_services/test_snapshot_contract_drift.py` parses
  `frontend/src/api/insights.ts` and asserts each `SnapshotModel` subclass
  (plus `DailyRecommendation`, `NotableSegment`, `WorkoutInsight`) has a
  same-named TS interface with identical field names.
- Backend models intentionally inlined or internal-only
  (`DailyLoadPoint`, `DailyRecommendationCacheSignal`) are listed in
  `INLINED_OR_INTERNAL` with a reason.
- The test catches the most common drift ("added a field on one side,
  forgot the other") without a codegen toolchain. Types and nullability
  are still covered by the manual checklists in both files.

### Stash And Old Branch Audit And Cleanup

- Dropped `stash@{0}` / `cleanup-save-strava-quota-edit` — it removed the
  Strava Phase B pre-loop quota guard, which we want to keep. The 429 catch
  on the actual call is belt-and-suspenders, not a replacement.
- Deleted `origin/claude/finish-pr-review-Kbf99` and
  `origin/oz/elevation-enrichment` after `git cherry` confirmed every commit
  had an equivalent already on `main`.
- Kept as reference:
  - `stash@{0}` (was `stash@{1}`) / `strength-entry-redesign WIP` — original
    source of the live-mode ideas; the useful parts landed in PRs #16 / #19
    / #20, but the stash still has raw notes worth skimming before the next
    strength iteration.
  - `origin/claude/interesting-archimedes-16548a` — HR-zone / lap-zone /
    cardiac-drift ideas. Strength live/retro slice was extracted; the
    HR-zones slice is still open (see "Still Remaining" below).

### Strength Entry Redesign Extraction

Source material:

- `stash@{0}` (was `stash@{1}`) / `strength-entry-redesign WIP`
- `origin/claude/interesting-archimedes-16548a`

Landed as a three-PR stack against `main` on 2026-04-24:

- PR #16 / ``yy/strength-performed-at-live-mode`` — adds a nullable
  ``performed_at`` naive-local column to ``strength_sets``, a Live/Retro mode
  toggle on ``StrengthEntry``, a rest timer, and a "Log set" action that
  stamps ``performed_at`` in live mode.
- PR #19 (re-created from closed PR #17) / ``yy/strength-hr-attachment`` —
  new ``backend/services/strength_hr.py`` with 45s lookback + decimation to
  ~300 points. ``session_summary`` conditionally merges per-set ``avg_hr`` /
  ``max_hr`` and a top-level ``hr_curve`` / ``activity_start_iso`` when the
  linked Strava activity's ``time`` + ``heartrate`` streams are already
  cached. Invariant: read-only against ``activity_streams``, never triggers
  a Strava fetch.
- PR #20 (re-created from closed PR #18) / ``yy/strength-hr-ui`` — new
  ``StrengthHrChart`` Recharts line chart with a ``ReferenceDot`` at each
  logged set's offset, plus per-set ``.hr-pill`` HR column in the session
  detail tables.

Tests: 18 new ``test_strength_hr`` tests + 3 new ``test_strength`` tests
covering the merge path and round-trip of ``performed_at``.

## Still Remaining

### 1. HR Zones / Cardiac Drift Follow-Up

Source material:

- `origin/claude/interesting-archimedes-16548a`

Current state:

- The old branch contains HR-zone, lap-zone, cardiac-drift, and insight-context
  ideas that may still be valuable.
- It is too stale to merge wholesale.
- Be careful with any Activity Detail auto-stream-loading behavior because the
  current architecture intentionally keeps Strava streams lazy.
- The strength slice of this branch has already been extracted (see the
  Resolved section above); this item is the remaining non-strength ideas.

Recommended next step:

- Plan a backend-first HR-zone/cardiac-drift slice, then wire frontend display
  separately if the backend shape proves useful.

## Suggested Prompt For Next Session

```text
Please read REFACTOR_FINDINGS.md and pick up the only remaining item: plan a backend-first HR-zone / cardiac-drift slice by mining ideas from origin/claude/interesting-archimedes-16548a. Start with a short design doc listing which ideas survive against the current lazy-stream architecture, then land a focused first PR (backend shape + tests) before touching the frontend.
```
