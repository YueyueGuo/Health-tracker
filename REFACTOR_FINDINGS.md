# Refactor Findings And Next Steps

Current as of the backend snapshot/time-utils refactor pass on April 23, 2026.

## Current Baseline

- GitHub default branch is `main`.
- Local verification after the latest refactor pass:
  - `.venv/bin/ruff check .` -> passed
  - `.venv/bin/python -m pytest` -> 291 passed, no `datetime.utcnow()` warnings
  - `npm run typecheck` -> passed
  - `npm run build` -> passed, with Vite's existing large bundle warning
- Current worktree includes uncommitted refactor changes plus this handoff file.
- `REFACTOR_FINDINGS.md` is a handoff/planning file and is currently untracked unless staged explicitly.

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
- `backend/services/training_metrics.py` still returns plain dicts for public API stability, but now validates assembled payloads against the snapshot models before returning.
- Added `backend/services/time_utils.py` with explicit helpers:
  - `local_today()`
  - `utc_now()`
  - `utc_now_naive()`
- Added optional `today` parameters to training metrics, sleep analytics, correlations, and legacy metrics functions where deterministic date windows matter.
- Replaced backend/test `datetime.utcnow()` call sites with explicit helpers, including activity feedback timestamps, insight cache timestamps, insight tests, scheduler-job tests, and activity-feedback tests.
- Made daily recommendation cache-signal construction explicit via `daily_recommendation_cache_signal()`.
- Added regression tests for explicit `today` injection, snapshot contract validation, cache-signal shape, and time helper behavior.

## Remaining Findings

### 1. Backend Snapshot And Insights Modules Are Still Too Large

Files:

- `backend/services/training_metrics.py`
- `backend/services/insights.py`
- `backend/services/snapshot_models.py`

Current state:

- `training_metrics.py` is still large and assembles training load, sleep, recovery, latest workout, goals, baselines, RPE, feedback, environmental context, and recent activity snapshots.
- `insights.py` is still about 603 lines and contains Pydantic LLM response schemas, schema transformation, cache helpers, provider fallback orchestration, prompts, and public methods.
- Snapshot payloads now validate against Pydantic models in `snapshot_models.py`, but public API boundaries intentionally still return plain dicts.
- The frontend still mirrors nested insight snapshot shapes manually in `frontend/src/api/insights.ts`.

Recommended next steps:

- Split `training_metrics.py` into focused modules, for example:
  - `training_load_snapshot.py`
  - `sleep_recovery_snapshot.py`
  - `workout_snapshot.py`
  - `goals_feedback_snapshot.py`
- Keep `get_full_snapshot()` as a thin composition layer.
- Consider generating or documenting frontend insight types from `snapshot_models.py`.

Suggested PR size: Medium.

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
- `LatestWorkoutSnapshot.laps`, `weather`, `pre_workout_sleep`, and `recent_activities` still use `any`.
- There are still no generated or backend-sourced frontend contracts.

Recommended next steps:

- Define typed interfaces for:
  - `WorkoutLapSnapshot`
  - `WorkoutWeatherSnapshot`
  - `PreWorkoutSleepSnapshot`
  - `RecentActivitySnapshot`
- Replace remaining API-level `any` in `insights.ts`.
- After backend Pydantic snapshot models exist, consider schema generation or at least a manual type-sync checklist.

Suggested PR size: Medium. Best after backend snapshot models.

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

### 5. Legacy Chat Analysis Path May Be Redundant

Files:

- `backend/services/analysis.py`
- `backend/routers/chat.py`
- `frontend/src/api/chat.ts`
- `frontend/src/components/ChatPanel.tsx`

Current state:

- `analysis.py` builds markdown context independently from the structured insights path.
- `insights.py` + `training_metrics.py` now contain the richer, cached, structured LLM snapshot path.
- Chat endpoints are still useful for free-form Q&A, but daily briefing/workout analysis may duplicate newer `/api/insights/*` behavior.

Recommended next steps:

- Decide whether to:
  - keep free-form `/api/chat/ask` but route daily briefing/workout analysis through the structured insight snapshots, or
  - explicitly deprecate legacy `/api/chat/daily-briefing` and `/api/chat/workout/{id}` once UI no longer depends on them.
- Add tests around whichever chat behavior remains.

Suggested PR size: Small to medium, depending on deprecation strategy.

### 6. Frontend Test Coverage Is Still Missing

Files/areas:

- No `frontend/src/**/*.test.*` or Vitest setup currently exists.

Risk:

- API helper behavior, hooks, and location forms are covered only by TypeScript/build checks.
- UI regressions in Settings, Activity Detail, and dashboard cards can slip through.

Recommended next steps:

- Add Vitest + React Testing Library.
- Start with low-maintenance tests for:
  - `api/http.ts` error parsing and 204 handling
  - `useDebouncedLocationSearch`
  - `useCurrentPosition` geolocation unavailable/error paths
  - `LocationSearchForm` basic pick flow

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

Status: mostly complete; module splitting remains.

Completed:

- Add snapshot Pydantic models.
- Add `time_utils.py`.
- Replace `datetime.utcnow()` usages and add deterministic date tests.

Remaining:

- Split `training_metrics.py`.
- Decide whether to expose snapshot schemas for frontend type-sync.

Verification:

- `.venv/bin/ruff check .`
- `.venv/bin/python -m pytest`

### PR 2: Frontend Type Tightening And Tests

Goal: make frontend contracts safer after the API split.

Scope:

- Replace remaining `any` in `frontend/src/api/insights.ts`.
- Add Vitest + React Testing Library.
- Test `api/http.ts` and the location hooks/forms.

Verification:

- `npm run typecheck`
- `npm run build`
- frontend test command once added

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

### PR 4: Legacy Chat/Insights Consolidation

Goal: remove duplicate LLM context paths.

Scope:

- Decide whether legacy chat briefing/workout endpoints should call structured insight snapshots or be deprecated.
- Add tests for whichever behavior remains.

## Suggested Prompt For Next Session

```text
Please read REFACTOR_FINDINGS.md and implement the next refactor PR: backend snapshot models and time utilities. Keep public API responses stable, eliminate datetime.utcnow warnings, run Ruff and pytest, and update this handoff file with what changed.
```
