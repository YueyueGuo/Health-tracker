# Refactor Findings And Next Steps

Current as of the parallel maintenance follow-up pass on April 24, 2026.

## Current Baseline

- GitHub default branch is `main`.
- Current branch checked during this audit: `main`.
- PR #5 (`codex/split-insight-modules`) was merged into `main` as merge commit `7fbd082`.
- PR #6 (`yy/chat-insights-consolidation`) was merged into `main` as commit `db12365`.
- PR #7 (`codex/frontend-tests-and-coverage`) was merged into `main` as merge commit `63fdd6a`.
- Backend verification after the latest module-split refactor:
  - `.venv/bin/ruff check .` -> passed
  - `.venv/bin/python -m pytest` -> 291 passed, no `datetime.utcnow()` warnings
- Frontend verification after the latest insight type-tightening/module-split pass:
  - `npm test` -> passed (Vitest, 21 tests)
  - `npm run typecheck` -> passed
  - `npm run build` -> passed, with Vite's existing large bundle warning
- Local `main` was fast-forwarded to `origin/main` after PR #7. Any
  uncommitted changes after this point are documentation/memory-file updates.

Preserved stashes from the consolidation pass, not inspected in this refactor pass:

- `stash@{0}`: `cleanup-save-strava-quota-edit`
- `stash@{1}`: `strength-entry-redesign WIP`

Remaining remote branches intentionally left alone during consolidation:

- `origin/claude/finish-pr-review-Kbf99`
- `origin/claude/interesting-archimedes-16548a`
- `origin/oz/elevation-enrichment`

## Completed In This Refactor Sprint

### PATCH Semantics

- `backend/routers/goals.py` now uses `payload.model_fields_set` so explicit `{"description": null}` clears the description while omitted fields stay unchanged.
- `backend/routers/locations.py` now uses `payload.model_fields_set` so explicit `{"elevation_m": null}` clears elevation while omitted elevation stays unchanged.
- Added regression tests:
  - `tests/test_routers/test_goals.py`
  - `tests/test_routers/test_locations.py`

### Ruff Cleanup

- `.venv/bin/ruff check .` is clean.
- Removed unused imports.
- Fixed `WeatherSnapshot` annotation visibility in `backend/models/activity.py`.
- Renamed ambiguous `l` loop variables in classifier/Strava tests.

### CI

- Added `.github/workflows/ci.yml`.
- CI runs backend Ruff + pytest and frontend typecheck + build.
- CI uses Python 3.11 and Node 22.

### Frontend API Refactor

- Added shared HTTP helper: `frontend/src/api/http.ts`.
- It centralizes:
  - `/api` base URL
  - FastAPI `{detail: ...}` error parsing
  - 204/205 no-content handling
  - JSON `Accept`/`Content-Type` behavior
  - optional 404 handling via `fetchOptionalJson`
- Split the overloaded `frontend/src/api/client.ts` into domain modules:
  - `activities.ts`
  - `chat.ts`
  - `dashboard.ts`
  - `recovery.ts`
  - `summary.ts`
  - `sync.ts`
  - existing `feedback.ts`, `goals.ts`, `insights.ts`, `locations.ts`, `sleep.ts`, `strength.ts`, `weather.ts`
- `client.ts` is now only a compatibility barrel. No UI components currently import it directly.

### Location UI Refactor

- Added reusable hooks:
  - `frontend/src/hooks/useDebouncedLocationSearch.ts`
  - `frontend/src/hooks/useCurrentPosition.ts`
- Added reusable forms:
  - `frontend/src/components/location/LocationSearchForm.tsx`
  - `frontend/src/components/location/GpsLocationForm.tsx`
- `Settings.tsx` and `LocationPicker.tsx` now share the search and GPS flows.

### Small Type Cleanup

- Tightened `useApi` error handling and dependency typing.
- Removed several component-level `any` annotations in dashboard/recovery/sleep chart code now that domain API types flow through.

### Backend Snapshot Contracts And Time Utilities

- Added `backend/services/snapshot_models.py` with Pydantic contracts for the dashboard insight input snapshots:
  - training load, sleep, recovery, latest workout, goals, baselines, recent RPE, feedback, environmental context, recent activities, full snapshot, and the daily recommendation cache signal.
- Snapshot builders still return plain dicts for public API stability, but now validate assembled payloads against the snapshot models before returning.
- Added `backend/services/time_utils.py` with explicit helpers:
  - `local_today()`
  - `utc_now()`
  - `utc_now_naive()`
- Added optional `today` parameters to training metrics, sleep analytics, correlations, and legacy metrics functions where deterministic date windows matter.
- Replaced backend/test `datetime.utcnow()` call sites with explicit helpers, including activity feedback timestamps, insight cache timestamps, insight tests, scheduler-job tests, and activity-feedback tests.
- Made daily recommendation cache-signal construction explicit via `daily_recommendation_cache_signal()`.
- Added regression tests for explicit `today` injection, snapshot contract validation, cache-signal shape, and time helper behavior.

### Backend Snapshot And Insights Module Split

- `backend/services/training_metrics.py` is now a 112-line compatibility facade plus `get_full_snapshot()` composition layer.
- Extracted focused snapshot builders:
  - `training_load_snapshot.py`
  - `sleep_recovery_snapshot.py`
  - `workout_snapshot.py`
  - `goals_feedback_snapshot.py`
- `backend/services/insights.py` is now a 329-line orchestration module.
- Extracted insight support modules:
  - `insight_schemas.py`
  - `insight_prompts.py`
  - `insight_cache.py`
- Preserved the existing `backend.services.training_metrics` and `backend.services.insights` public import surfaces used by routers/tests.

### Frontend Insight Type Tightening

- Replaced remaining API-level `any` placeholders in `frontend/src/api/insights.ts`.
- Added typed frontend mirrors for latest-workout laps, weather, pre-workout sleep, historical comparison, recent activities, goals, baselines, recent RPE, feedback summary, and environmental context.
- Updated `FullSnapshot` so it now includes the richer backend snapshot fields instead of only the original training/sleep/recovery/latest/recent-activity subset.

### Frontend Test Harness And Shared Coverage

- Added Vitest + React Testing Library to the frontend toolchain.
- Added `npm test` in `frontend/package.json`.
- Added shared test setup via `frontend/src/test/setup.ts`.
- Added focused frontend tests for:
  - `frontend/src/api/http.ts`
  - `frontend/src/hooks/useDebouncedLocationSearch.ts`
  - `frontend/src/hooks/useCurrentPosition.ts`
  - `frontend/src/components/location/LocationSearchForm.tsx`
  - `frontend/src/components/location/GpsLocationForm.tsx`
  - `frontend/src/components/LocationPicker.tsx`
  - `frontend/src/components/GoalsSection.tsx`
  - `frontend/src/components/ActivityDetail.tsx`
  - `frontend/src/pages/Settings.tsx`
- Current frontend test count from this slice: 25 passing.

### Snapshot Type Sync Checklist And ActivityDetail Follow-Up

- Added an explicit snapshot type-sync checklist to:
  - `backend/services/snapshot_models.py`
  - `frontend/src/api/insights.ts`
- Tightened `LatestWorkoutSnapshot.classification_flags` in `snapshot_models.py` from `list[Any]` to `list[str]` to match the actual payload and the frontend contract.
- `frontend/src/components/ActivityDetail.tsx` now uses shared `getErrorMessage()` handling for lazy insight/stream errors instead of local `any` catches.
- Added `frontend/src/components/ActivityDetail.test.tsx` covering:
  - lazy latest-workout insight loading
  - lazy stream loading
  - surfaced error states for both lazy actions
- Verification after this pass:
  - `npm test` -> 25 passed
  - `npm run typecheck` -> passed
  - `npm run build` -> passed, with Vite's existing large bundle warning
  - `.venv/bin/python -m pytest tests/test_services/test_insights.py tests/test_services/test_training_metrics.py` -> 44 passed

### Backend Route Date/Time Follow-Up

- Replaced a small user-visible batch of direct wall-clock calls with
  `backend/services/time_utils.py` helpers:
  - `backend/routers/sleep.py` now anchors the list cutoff to `local_today()`.
  - `backend/routers/recovery.py` now anchors list and `/today` lookups to
    `local_today()`.
  - `backend/routers/insights.py` now anchors feedback stats to `local_today()`.
  - `backend/services/weekly_summary.py` now defaults `weekly_summaries()` to
    `local_today()` instead of UTC date.
  - `backend/services/analysis.py` now uses `utc_now()` for recent activity
    context and `local_today()` for sleep/recovery context.
- Added focused midnight-boundary tests for route/service behavior where a UTC
  date rollover could otherwise shift the visible local window:
  - `tests/test_routers/test_sleep.py`
  - `tests/test_routers/test_recovery.py`
  - `tests/test_routers/test_insights_feedback.py`
  - `tests/test_services/test_weekly_summary.py`
- Verification after this pass:
  - `.venv/bin/python -m pytest tests/test_routers/test_sleep.py tests/test_routers/test_recovery.py tests/test_routers/test_insights_feedback.py tests/test_services/test_weekly_summary.py` -> 31 passed
  - `.venv/bin/ruff check backend/routers/sleep.py backend/routers/recovery.py backend/routers/insights.py backend/services/weekly_summary.py backend/services/analysis.py tests/test_routers/test_sleep.py tests/test_routers/test_recovery.py tests/test_routers/test_insights_feedback.py tests/test_services/test_weekly_summary.py` -> passed

### Settings / Goals / Location Decomposition

- `frontend/src/pages/Settings.tsx` is now a composition-only page that renders `GoalsSection` plus a new `LocationSettingsSection`.
- Extracted new hooks:
  - `frontend/src/hooks/useGoals.ts`
  - `frontend/src/hooks/useLocations.ts`
- Extracted goal UI pieces:
  - `frontend/src/components/settings/GoalForm.tsx`
  - `frontend/src/components/settings/GoalRow.tsx`
- Extracted location settings UI pieces:
  - `frontend/src/components/settings/LocationSettingsSection.tsx`
  - `frontend/src/components/settings/LocationRow.tsx`
  - `frontend/src/components/settings/AddLocation.tsx`
  - `frontend/src/components/settings/AdvancedLocationForm.tsx`
- Extracted shared location picker UI:
  - `frontend/src/components/location/SavedLocationPicker.tsx`
- Added shared frontend error helper:
  - `frontend/src/utils/errors.ts`
- `frontend/src/components/LocationPicker.tsx` now reuses `useLocations()` and `SavedLocationPicker` while preserving the existing attach/create/detach behavior.
- Verification after this pass:
  - `npm test` -> 25 passed
  - `npm run typecheck` -> passed
  - `npm run build` -> passed, with Vite's existing large bundle warning

### Frontend Catch / Tooltip Type Cleanup

- Removed the remaining non-test frontend `any` escapes in current app code:
  - `ChatPanel.tsx`
  - `Strength.tsx`
  - `StrengthEntry.tsx`
  - `Sleep.tsx`
  - `WeeklySummaryCards.tsx`
- Extended `frontend/src/utils/errors.ts` so `getErrorMessage()` accepts an optional fallback while still keeping `unknown` at call sites.
- Replaced the custom CSS variable `as any` style escapes in `WeeklySummaryCards.tsx` with a typed helper.
- Replaced the loose `StagesTooltip` payload typing in `Sleep.tsx` with an explicit tooltip-entry type plus numeric coercion helper.
- Added focused frontend tests for the touched error-handling flows:
  - `frontend/src/components/ChatPanel.test.tsx`
  - `frontend/src/pages/StrengthEntry.test.tsx`
- Verification after this pass:
  - `npm test -- --run src/components/ChatPanel.test.tsx src/pages/StrengthEntry.test.tsx src/components/ActivityDetail.test.tsx src/pages/Settings.test.tsx` -> 6 passed
  - `npm run typecheck` -> passed

### Dashboard Frontend Coverage

- Added focused Vitest coverage for dashboard payload consumers:
  - `frontend/src/components/Dashboard.test.tsx`
  - `frontend/src/components/TrainingLoad.test.tsx`
- `Dashboard.test.tsx` verifies nested overview payload rendering for weekly
  stats, latest sleep, latest recovery, imperial distance conversion, sport
  breakdown pluralization, and the sync/reload path.
- `TrainingLoad.tsx` now treats the backend's no-activity training-load payload
  (zero-valued CTL/ATL/TSB series with no daily load) as a real no-data state
  instead of rendering blank chart shells.
- `TrainingLoad.test.tsx` verifies chart-ready CTL/ATL/TSB and daily-load
  transformations plus weekly-volume table rendering and the backend-shaped
  no-training-data state.
- Verification after this pass:
  - `npm test -- --run src/components/Dashboard.test.tsx src/components/TrainingLoad.test.tsx` -> 4 passed
  - `npm test` -> 31 passed
  - `npm run typecheck` -> passed
  - `npm run build` -> passed, with Vite's existing large bundle warning

### Route-Level Bundle Splitting

- `frontend/src/App.tsx` now lazy-loads route components with `React.lazy()`
  and wraps each route element in `Suspense` using the existing `.loading`
  style.
- Verification after this pass:
  - `npm run typecheck` -> passed
  - `npm run build` -> passed, and the previous large chunk warning is gone
    after Vite emits route chunks plus a shared chart chunk below the warning
    threshold.

### Backend Sync/Client Time Helper Cleanup

- Replaced clear sync/client/classifier wall-clock calls with shared helpers:
  - `backend/services/sync.py` uses `utc_now()` for sync logs/enrichment
    timestamps and `utc_now_naive()` once per Strava Phase A list pass for
    mutable-lookback comparisons.
  - `backend/services/eight_sleep_sync.py` and
    `backend/clients/eight_sleep.py` use `local_today()` for Eight Sleep
    local-date windows and `utc_now()` for sync-log timestamps.
  - `backend/services/whoop_sync.py` uses `utc_now()` for default Whoop UTC
    sync windows.
  - `backend/services/classifier.py` uses `utc_now()` for persisted
    classification timestamps.
- Added focused helper-injection coverage for:
  - Strava Phase A mutable lookback behavior.
  - Classifier persisted timestamp shape.
  - Eight Sleep incremental sync windows and recent-sleep client windows.
  - Whoop default sync windows.
- Verification after this pass:
  - `.venv/bin/python -m pytest tests/test_sync/test_strava_sync.py tests/test_sync/test_classifier.py tests/test_sync/test_eight_sleep_sync.py tests/test_sync/test_whoop_sync.py tests/test_clients/test_eight_sleep.py` -> 113 passed
  - `.venv/bin/ruff check` on touched backend/test files -> passed
  - `git diff --check` -> passed
- Intentionally left Eight Sleep token-expiry `time.time()` calls alone because
  those are auth-lifecycle checks rather than date-window behavior.

### Stash And Old Branch Audit

- Audited preserved stashes and old remote branches read-only.
- Recommendations:
  - `stash@{0}` / `cleanup-save-strava-quota-edit`: drop. It removes the
    Strava Phase B quota guard, which current docs/code intentionally keep.
  - `stash@{1}` / `strength-entry-redesign WIP`: keep for now as reference.
    Mine ideas into a fresh strength-entry redesign PR rather than applying it
    directly.
  - `origin/claude/finish-pr-review-Kbf99`: delete. It appears merged by patch
    equivalence.
  - `origin/oz/elevation-enrichment`: delete. It appears already merged.
  - `origin/claude/interesting-archimedes-16548a`: keep as reference. It has
    valuable but stale HR-zone/cardiac-drift and strength live/retro ideas that
    should be extracted into fresh PRs, not merged wholesale.
- Audit was based on the existing local remote-tracking refs; fetch before
  deleting remote branches if time has passed.

## Remaining Findings

### 1. Snapshot Contracts Are Still Manual Across Backend And Frontend

Files:

- `backend/services/snapshot_models.py`
- `frontend/src/api/insights.ts`

Current state:

- Backend snapshot assembly is split into focused modules and validates against `snapshot_models.py`.
- Public API boundaries intentionally still return plain dicts.
- The frontend mirrors nested insight snapshot shapes manually in `frontend/src/api/insights.ts`.
- A lightweight type-sync checklist now lives in both `snapshot_models.py` and `frontend/src/api/insights.ts`, but there is still no generated contract pipeline.

Recommended next steps:

- Consider generating JSON Schema/TypeScript types from the backend Pydantic models if this surface changes often.

Suggested PR size: Small.

### 2. Date And Time Handling Still Needs A Shared Pattern

Files/areas:

- `backend/services/training_metrics.py`
- `backend/services/sleep_analytics.py`
- `backend/services/correlations.py`
- `backend/services/metrics.py`
- `backend/routers/activities.py`
- tests under `tests/test_services` and `tests/test_routers`

Current state:

- `backend/services/time_utils.py` now centralizes `local_today()`, `utc_now()`, and `utc_now_naive()`.
- `datetime.utcnow()` has been eliminated from backend/tests; pytest now runs without those deprecation warnings.
- Core analytics date-window functions now accept optional `today` parameters for deterministic tests.
- Sleep, recovery, feedback stats, weekly summary defaults, and free-form
  analysis context now use shared helpers for user-visible date windows.
- Sync/client/classifier call sites with clear semantics now use
  `local_today()`, `utc_now()`, and `utc_now_naive()`.
- Remaining direct wall-clock calls are mostly in tests or deliberately
  non-date-window code such as token-expiry checks.

Recommended next steps:

- Continue replacing direct wall-clock calls opportunistically if new
  user-visible date windows appear.

Suggested PR size: Small to medium.

### 3. Frontend Types Are Better But Still Not Complete

Files:

- `frontend/src/api/insights.ts`
- `frontend/src/api/activities.ts`
- chart and card components that still consume nested API payloads

Current state:

- `ActivityDetail.weather` and `raw_data` now use `Record<string, unknown>`.
- Current app code no longer has non-test frontend `any` escapes in the main remaining chat/strength/sleep/weekly-summary surfaces.
- `frontend/src/api/insights.ts` no longer has API-level `any` placeholders for insight snapshots.
- `ActivityDetail.tsx` no longer uses local `any` catches for lazy insight/stream error handling.
- There are still no generated or backend-sourced frontend contracts.

Recommended next steps:

- After backend Pydantic snapshot models exist, consider schema generation or at least a manual type-sync checklist.
- Keep tightening nested payload typings opportunistically as new chart/card surfaces are touched.

Suggested PR size: Small to medium.

### 4. Settings And Location UI Decomposition — DONE

Files touched:

- `frontend/src/pages/Settings.tsx`
- `frontend/src/components/GoalsSection.tsx`
- `frontend/src/components/LocationPicker.tsx`
- `frontend/src/components/settings/*`
- `frontend/src/components/location/SavedLocationPicker.tsx`
- `frontend/src/hooks/useGoals.ts`
- `frontend/src/hooks/useLocations.ts`
- `frontend/src/utils/errors.ts`

What changed:

- `Settings.tsx` now delegates saved-location loading/rendering to `LocationSettingsSection`, leaving the page itself as layout composition only.
- Goal CRUD was decomposed into `GoalForm`, `GoalRow`, and `useGoals()`.
- Location settings CRUD was decomposed into `AddLocation`, `AdvancedLocationForm`, `LocationRow`, `LocationSettingsSection`, and `useLocations()`.
- `LocationPicker.tsx` now reuses the extracted saved-location picker and shared locations hook.
- Shared `getErrorMessage()` handling removes repeated local `extractMessage()` helpers from the refactored surfaces.

### 5. Legacy Chat Analysis Path Consolidation — DONE

Files touched:

- `backend/routers/chat.py`
- `backend/services/analysis.py`
- `frontend/src/api/chat.ts`
- `frontend/src/components/ActivityDetail.tsx`
- `README.md`
- `tests/test_routers/test_chat.py` (new, 5 tests)

What changed:

- Removed `/api/chat/daily-briefing` (unused by the UI) and
  `/api/chat/workout/{id}` (previously only used by ActivityDetail).
- Rewired the ActivityDetail "Analyze This Workout" button to
  `/api/insights/latest-workout?activity_id={id}`, which returns the
  richer structured `WorkoutInsight` payload (headline, takeaway,
  notable segments, vs-history, flags) and is cached per-activity.
  Added a `WorkoutInsightView` subcomponent to render it.
- Trimmed `AnalysisEngine` to just the free-form `query()` path plus
  its context/formatting helpers. Unused `_build_workout_context` and
  `_build_daily_context` paths (and the associated `ActivityStream` /
  `WeatherSnapshot` imports) are gone.
- Removed `fetchDailyBriefing` / `fetchWorkoutAnalysis` from
  `frontend/src/api/chat.ts`; only `askQuestion` and
  `fetchAvailableModels` remain.
- Added 5 router tests covering `/chat/ask` happy path + model
  override, `/chat/models`, and 404s for the removed endpoints.

Only `/api/chat/ask` (free-form Q&A, still used by `ChatPanel`) and
`/api/chat/models` remain under `/api/chat`.

### 6. Frontend Test Coverage For Dashboard Cards — DONE

Files/areas:

- `frontend/src/api/http.test.ts`
- `frontend/src/hooks/useDebouncedLocationSearch.test.tsx`
- `frontend/src/hooks/useCurrentPosition.test.tsx`
- `frontend/src/components/location/LocationSearchForm.test.tsx`
- `frontend/src/components/location/GpsLocationForm.test.tsx`
- `frontend/src/components/LocationPicker.test.tsx`
- `frontend/src/components/GoalsSection.test.tsx`
- `frontend/src/components/ActivityDetail.test.tsx`
- `frontend/src/components/ChatPanel.test.tsx`
- `frontend/src/components/Dashboard.test.tsx`
- `frontend/src/components/TrainingLoad.test.tsx`
- `frontend/src/pages/Settings.test.tsx`
- `frontend/src/pages/StrengthEntry.test.tsx`

What changed:

- Shared HTTP behavior, Settings CRUD, extracted location hooks/forms, Activity Detail lazy API states, chat fallback errors, and strength-entry save errors now have regression coverage.
- Dashboard and TrainingLoad now cover the highest-risk nested dashboard payload
  consumers, including metric cards, chart-facing training-load data, weekly
  volume rows, and dashboard sync reload behavior.

### 7. Bundle Size Warning — DONE

Current state:

- Route-level lazy loading is in place in `frontend/src/App.tsx`.
- `npm run build` passes without the previous large chunk warning.

### 8. Stashes And Old Remote Branches — AUDITED

Current preserved stashes:

- `cleanup-save-strava-quota-edit`
- `strength-entry-redesign WIP`

Remaining remote branches:

- `origin/claude/finish-pr-review-Kbf99`
- `origin/claude/interesting-archimedes-16548a`
- `origin/oz/elevation-enrichment`

Recommended next steps:

- Drop `stash@{0}`.
- Keep `stash@{1}` as reference until a fresh strength-entry redesign slice
  captures the useful ideas.
- Delete `origin/claude/finish-pr-review-Kbf99` and
  `origin/oz/elevation-enrichment` after a fresh fetch confirms nothing new.
- Keep `origin/claude/interesting-archimedes-16548a` as reference for future
  HR-zone/cardiac-drift and strength live/retro slices.

Suggested PR size: No PR unless a stash contains desired code.

## Items Removed From The Old Findings

- Strava read-rate-limit parsing is no longer open. `backend/clients/strava.py` parses `X-ReadRateLimit-Usage` / `X-ReadRateLimit-Limit`, and `tests/test_clients/test_strava.py` covers the behavior.
- PATCH clear-null semantics for goals/locations are complete.
- Ruff is clean and enforced in CI.
- GitHub CI exists.
- Shared frontend HTTP/API plumbing is complete enough for now.

## Recommended Next PR Sequence

### PR 1: Backend Snapshot Models And Time Utilities

Goal: reduce backend/frontend contract drift and eliminate datetime warnings.

Status: complete enough for now; only optional generated-contract work remains.

Completed:

- Add snapshot Pydantic models.
- Add `time_utils.py`.
- Replace `datetime.utcnow()` usages and add deterministic date tests.
- Split `training_metrics.py`.
- Split `insights.py` into schemas/prompts/cache/orchestration.
- Replace route-level direct wall-clock calls for sleep/recovery/feedback stats,
  weekly summary defaults, and free-form analysis context.
- Add midnight-boundary tests for the touched user-visible windows.
- Replace sync/client/classifier wall-clock calls with shared helpers where
  semantics are clear.

Remaining:

- Decide whether to expose or generate snapshot schemas for frontend type-sync.

Verification:

- `.venv/bin/ruff check .`
- `.venv/bin/python -m pytest`

### PR 2: Frontend Type Tightening And Tests

Goal: make frontend contracts safer after the API split.

Status: complete enough for now; generated contracts remain optional future work.

Completed:

- Documented a frontend/backend snapshot type-sync checklist.
- Expanded Vitest coverage into high-signal `Settings` and `ActivityDetail` flows.
- Added dashboard payload-consumer coverage for `Dashboard` and `TrainingLoad`.

Remaining:

- Consider generated schema/type export if snapshot churn increases.

Verification:

- `npm test`
- `npm run typecheck`
- `npm run build`

### PR 3: Settings/Goals Decomposition

Goal: make settings easier to extend for phone-location PWA work.

Status: complete.

Completed:

- Extract location settings section/rows/forms.
- Extract goals row/form/hooks.
- Keep `/settings` layout as composition only.

Verification:

- `npm test`
- `npm run typecheck`
- `npm run build`
- Manual smoke test of `/settings` and `/activities/:id`

### PR 4: Legacy Chat/Insights Consolidation — DONE

Goal: remove duplicate LLM context paths.

Outcome:

- `/api/chat/daily-briefing` and `/api/chat/workout/{id}` removed;
  ActivityDetail now uses `/api/insights/latest-workout`.
- `AnalysisEngine` trimmed to free-form `query()` only.
- Frontend `chat.ts` slimmed to `askQuestion` + `fetchAvailableModels`.
- Added `tests/test_routers/test_chat.py` (5 tests).
- See finding 5 above for file-level details.

## Suggested Prompt For Next Session

```text
Please read REFACTOR_FINDINGS.md and implement the next remaining refactor slice: evaluate whether generating frontend snapshot types from backend Pydantic models is worth it, keep the first pass small, and either land a lightweight schema export/type-generation proof or document why the manual checklist is enough for now.
```
