# Refactor Findings And Next Steps

Current as of the frontend test-harness pass on April 23, 2026.

## Current Baseline

- GitHub default branch is `main`.
- Current branch checked during this audit: `main`.
- PR #5 (`codex/split-insight-modules`) was merged into `main` as merge commit `7fbd082`.
- Backend verification after the latest module-split refactor:
  - `.venv/bin/ruff check .` -> passed
  - `.venv/bin/python -m pytest` -> 291 passed, no `datetime.utcnow()` warnings
- Frontend verification after the latest insight type-tightening/module-split pass:
  - `npm test` -> passed (Vitest, 21 tests)
  - `npm run typecheck` -> passed
  - `npm run build` -> passed, with Vite's existing large bundle warning
- Local `main` was fast-forwarded to `origin/main` after PR #5. Any
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
- Current frontend test count from this slice: 21 passing.

## Remaining Findings

### 1. Snapshot Contracts Are Still Manual Across Backend And Frontend

Files:

- `backend/services/snapshot_models.py`
- `frontend/src/api/insights.ts`

Current state:

- Backend snapshot assembly is split into focused modules and validates against `snapshot_models.py`.
- Public API boundaries intentionally still return plain dicts.
- The frontend mirrors nested insight snapshot shapes manually in `frontend/src/api/insights.ts`; there is still no generated contract pipeline or documented type-sync checklist.

Recommended next steps:

- Add a lightweight type-sync checklist for `snapshot_models.py` -> `frontend/src/api/insights.ts`.
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
- Some routers and sync modules still call `date.today()` / `datetime.now(timezone.utc)` directly where they are not currently warning or where external API semantics need a smaller follow-up pass.

Recommended next steps:

- Continue replacing direct wall-clock calls opportunistically where it improves determinism.
- Add local/UTC midnight-boundary tests if route-level date behavior becomes user-visible.

Suggested PR size: Small to medium.

### 3. Frontend Types Are Better But Still Not Complete

Files:

- `frontend/src/api/insights.ts`
- `frontend/src/api/activities.ts`
- chart and card components that still consume nested API payloads

Current state:

- `ActivityDetail.weather` and `raw_data` now use `Record<string, unknown>`.
- Dashboard/recovery/sleep chart `any` usage was reduced.
- `frontend/src/api/insights.ts` no longer has API-level `any` placeholders for insight snapshots.
- There are still no generated or backend-sourced frontend contracts.

Recommended next steps:

- After backend Pydantic snapshot models exist, consider schema generation or at least a manual type-sync checklist.
- Continue opportunistically replacing component-level `any` catch/style helper annotations outside the insight API layer.

Suggested PR size: Small to medium.

### 4. Settings And Location UI Are Partially Decomposed, But Not Done

Files:

- `frontend/src/pages/Settings.tsx`
- `frontend/src/components/LocationPicker.tsx`
- `frontend/src/components/GoalsSection.tsx`

Current state:

- Shared search and GPS flows were extracted.
- `Settings.tsx` still owns saved-location list, row mutation logic, add-location mode state, and advanced raw-coordinate form.
- `GoalsSection.tsx` still owns add form, table, row mutations, and local formatting.
- `LocationPicker.tsx` is smaller but still owns saved-picker state and attach/detach orchestration.

Recommended next steps:

- Extract:
  - `LocationSettingsSection`
  - `LocationRow`
  - `AddLocation`
  - `AdvancedLocationForm`
  - `SavedLocationPicker`
- Consider hooks:
  - `useLocations()`
  - `useLocationMutations()`
- Consider decomposing `GoalsSection` into `GoalRow`, `GoalForm`, and `useGoals()`.

Suggested PR size: Medium.

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

### 6. Frontend Test Coverage Exists, But Is Still Thin

Files/areas:

- `frontend/src/api/http.test.ts`
- `frontend/src/hooks/useDebouncedLocationSearch.test.tsx`
- `frontend/src/hooks/useCurrentPosition.test.tsx`
- `frontend/src/components/location/LocationSearchForm.test.tsx`
- `frontend/src/components/location/GpsLocationForm.test.tsx`
- `frontend/src/components/LocationPicker.test.tsx`
- `frontend/src/components/GoalsSection.test.tsx`

Risk:

- Shared HTTP behavior and the extracted location hooks/forms now have regression coverage.
- UI regressions in Settings, Activity Detail, and dashboard cards can slip through.

Recommended next steps:

- Expand the new Vitest setup to cover:
  - `Settings` location CRUD flows
  - one or two dashboard cards that consume nested API payloads
  - `ActivityDetail` detail-page composition around lazy API states

Suggested PR size: Small.

### 7. Bundle Size Warning Still Exists

Current state:

- `npm run build` passes but Vite warns the main chunk is larger than 500 kB.

Recommended next steps:

- Add route-level lazy loading for heavier pages:
  - `/activities/:id`
  - `/sleep`
  - `/training`
  - `/strength`
  - `/strength/new`
- Consider chart/vendor chunk splitting for Recharts.

Suggested PR size: Small to medium.

### 8. Stashes And Old Remote Branches Still Need A Human Decision

Current preserved stashes:

- `cleanup-save-strava-quota-edit`
- `strength-entry-redesign WIP`

Remaining remote branches:

- `origin/claude/finish-pr-review-Kbf99`
- `origin/claude/interesting-archimedes-16548a`
- `origin/oz/elevation-enrichment`

Recommended next steps:

- Inspect each stash before deleting:
  - `git stash show -p stash@{0}`
  - `git stash show -p stash@{1}`
- Decide whether to keep, apply, or drop each stash.
- Compare remote branches to `main` before deleting:
  - `git log --oneline main..origin/<branch>`
  - `git diff --stat main..origin/<branch>`

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

Remaining:

- Decide whether to expose or generate snapshot schemas for frontend type-sync.

Verification:

- `.venv/bin/ruff check .`
- `.venv/bin/python -m pytest`

### PR 2: Frontend Type Tightening And Tests

Goal: make frontend contracts safer after the API split.

Status: mostly complete; shared-surface tests exist now.

Scope:

- Add or document a frontend/backend snapshot type-sync checklist.
- Expand the new Vitest setup into a few more high-signal frontend flows.

Verification:

- `npm test`
- `npm run typecheck`
- `npm run build`

### PR 3: Settings/Goals Decomposition

Goal: make settings easier to extend for phone-location PWA work.

Scope:

- Extract location settings section/rows/forms.
- Extract goals row/form/hooks.
- Keep `/settings` layout as composition only.

Verification:

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
Please read REFACTOR_FINDINGS.md and implement the next refactor PR: decompose Settings and location/goals UI into smaller components/hooks without changing behavior. Run frontend test/build checks and update this handoff file with what changed.
```
