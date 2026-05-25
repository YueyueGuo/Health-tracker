# Diagnosis: Home page "latest activity" misses Apple Health workouts

## 1. Symptom

A run uploaded from Apple Health shows up correctly at the top of the
**History** tab but never replaces the older workout on the **Home**
dashboard's "Recent Activity" card. The user expects the Home card to
mirror what History considers the newest workout across all sources;
instead, Home appears stuck on the most recent Strava activity. The bug
is not refresh/cache related — even after forcing a Home reload it
still shows the older Strava workout.

## 2. Reproduction (read-only)

1. Seed an `Activity` row from Strava with `start_date = T-2 days`,
   `enrichment_status = "complete"`.
2. Seed a `HealthDataPoint` (`source="apple_health"`,
   `data_type="workout"`) + `Workout` child with `start_time = T-1 hour`
   and no `activity_id` set (Apple-only).
3. `GET /api/dashboard/history?days=30` → the Apple workout sorts first
   (`backend/services/activity_feed.py:107-110`).
4. `GET /api/insights/latest-workout?summary_only=true` → returns the
   Strava activity from T-2 days
   (`backend/services/workout_snapshot.py:40-45`).

## 3. Root cause

**Hypothesis 1 (confirmed): Home endpoint queries only the Strava
`activities` table; Apple Health workouts live in `health_data_points`
+ `workouts`.**

- `backend/services/workout_snapshot.py:40-45` — `_get_latest_completed_activity`
  selects only from `Activity`:
  ```python
  query = (
      select(Activity)
      .where(Activity.enrichment_status == "complete")
      .order_by(Activity.start_date.desc())
      .limit(1)
  )
  ```
- Apple Health ingest writes a separate row family:
  `backend/services/apple_health_ingest.py:108-148` creates a
  `HealthDataPoint(source="apple_health", data_type="workout", ...)`
  plus a `Workout` child. Nothing in that path touches `Activity`.
- The History page uses `backend/services/activity_feed.list_activity_feed`,
  which explicitly merges Strava `Activity` rows (with
  `superseded_by_id IS NULL`) and Apple `Workout` rows — see
  `backend/services/activity_feed.py:50-105`.
- Commit history confirms a half-finished migration: `b4a5985`
  ("History page now shows Apple Health workouts") was a sibling fix;
  the equivalent change for the Home page was never made.

**Sub-mechanism (also covered by the fix): the Home query at
`workout_snapshot.py:42` does not filter `superseded_by_id IS NULL`.**
If an Apple workout deduped over a Strava activity
(`backend/services/workout_dedup.py:96` sets
`Activity.superseded_by_id = data_point.id`), Home would currently
return the *losing* Strava row.

**Hypothesis 2 (tightly coupled — fix must address simultaneously):
`LatestWorkoutSnapshot` Pydantic contract is Strava-shaped.**

- `backend/services/snapshot_models.py:140-169` declares
  `strava_id: int` (required).
- `workout_snapshot.py:201` hard-codes `"strava_id": activity.strava_id`.
- Apple rows have no `strava_id` → `validate_snapshot` will raise unless
  `strava_id` is made `int | None`.

## 4. Fix plan

### Backend

1. **`backend/services/workout_snapshot.py`**
   - Extend `_get_latest_completed_activity` so it considers both a
     canonical `Activity` row (`superseded_by_id IS NULL`,
     `enrichment_status == "complete"`) and an Apple
     `HealthDataPoint`/`Workout` pair. Return whichever has the later
     start time.
   - In `get_latest_workout_snapshot`, branch on the returned object:
     build the existing Strava payload, or an Apple-shaped payload that
     mirrors the keys `_apple_workout_summary` (in `activity_feed.py`)
     produces, with Strava-only fields set to `None`.

2. **`backend/services/snapshot_models.py`**
   - `strava_id: int | None` on `LatestWorkoutSnapshot`.
   - Add `source: Literal["strava", "apple_health"]` so consumers can
     branch deterministically.

### Frontend

3. **`frontend/src/api/insights.ts`** — type sync only.
   - `strava_id: number | null`.
   - Add `source: "strava" | "apple_health"` if added on the backend.

(No changes needed in `routers/insights.py` or `YesterdayActivityCard.tsx`
— the card already reads `name`, `sport_type`, `distance_m`,
`moving_time_s`, `avg_hr`, `total_elevation_m`, `calories` which the
Apple summary mapper already populates.)

### Migration required?

**No.** Pure read-path fix. `Activity.superseded_by_id` and
`HealthDataPoint`/`Workout` tables already exist.

## 5. Regression tests

- **`tests/test_services/test_workout_snapshot.py`** (new) or extend
  `tests/test_services/test_training_metrics.py`:
  - `test_latest_workout_snapshot_returns_apple_when_newer`: Strava
    `Activity` at `T-2d` + Apple `HealthDataPoint`/`Workout` at `T-1h`.
    Assert snapshot tracks the Apple workout, `strava_id is None`,
    `source == "apple_health"`.
  - `test_latest_workout_snapshot_returns_strava_when_newer`: reverse
    timestamps. Assert snapshot tracks the Strava row.
  - `test_latest_workout_snapshot_ignores_superseded_strava`: Strava
    activity with `superseded_by_id` set + winning Apple workout.
    Assert Apple workout returned, not superseded Strava row.
  - `test_latest_workout_snapshot_apple_only_no_strava`: only an Apple
    workout in the DB; should return the Apple workout (not `None`).
- **`tests/test_services/test_snapshot_contract_drift.py`** — will pick
  up the contract changes automatically.

## 6. Out-of-scope cleanup spotted

(Recorded only; not in this fix.)

- `YesterdayActivityCard.tsx:87` hard-codes the badge label as
  `"Strava + Strength"` / `"Strava"`. Once Apple workouts can land
  here, this will mis-label them. Copy issue, separate fix.
- The historical-comparison block in `workout_snapshot.py:143-185` is
  gated on `Run/TrailRun/VirtualRun`. Apple workouts have
  `classification_type=None`, so the gate fails-closed cleanly — but
  it's an implicit Strava-only dependency worth a comment.
- `LatestWorkoutSnapshot` could converge on the `(source, external_id)`
  pattern History already uses, instead of carrying a flat `strava_id`.
