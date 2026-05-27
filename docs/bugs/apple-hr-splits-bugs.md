# Diagnosis: Apple Health workout detail — HR streams missing + splits ignore unit preference

## 1. Symptoms restated

**Bug 1 — HR stream data missing.** On `/activities/:id?source=apple_health` for a May 25 "Outdoor Run", the Analysis card (HR + Pace toggle pills) renders the "No stream data available." fallback at `frontend/src/components/activity/AnalysisChart.tsx:282-286`. The user expects the per-sample HR curve (and pace curve when the Pace toggle is on) to render the same way it does for Strava-sourced runs. They report it used to work for Apple Health workouts and stopped working.

**Bug 2 — Splits row distance is metric (1000 m) while pace is per-mile.** The user's unit preference in Settings is `imperial` (`frontend/src/components/settings/PreferencesCard.tsx:36-44`, persisted via `useUnits` to `localStorage` key `ht.units`). The splits table for this Apple run displays "1000 m" in the Dist column for every full lap, and "874 m" for the trailing remainder, while the Pace column shows 9:46 (which is min/mi). The caption "Auto-split — Apple Health did not provide lap markers" is shown by `SplitsTable.tsx:35-37`. Expected: each row's distance should be "1.00 mi" (with a final remainder in yards or a fractional mile), since the user is on imperial.

## 2. Reproduction (read-only)

**Bug 1 read-only repro.**
- Existing test `tests/test_routers/test_activities.py::test_streams_for_apple_returns_empty_dict_when_no_series` pins the behavior: when `raw_payload` lacks `heartRateData` (and lacks per-sample `route[*].speed`), `GET /api/activities/{id}/streams` returns `{}` with status 200. The frontend then enters the empty-state branch at `AnalysisChart.tsx:282-286`. The Apple-source auto-fetch path is at `ActivityDetail.tsx:103-112`.

**Bug 2 read-only repro.**
- `backend/services/apple_health_ingest.py::_derive_laps` always uses `_SPLIT_METERS["run"] = 1000.0` (line 43). For an 8.87 km / 5.51 mi run the function returns 8 full laps of 1000.0 m plus a remainder lap of ~874 m. These are persisted to `workout_laps`.
- `backend/services/apple_workout_detail.py::_workout_lap_dict` emits `lap.distance = lap.distance_m` unchanged (line 141).
- `frontend/src/components/activity/utils.ts::distanceToDisplay` (line 72-87) on imperial returns "1000 m" for 1000-meter input because 1000 < METERS_PER_MILE (1609.344) falls into the "Anything under a mile → meters" branch. Pace is correctly min/mi because `paceShort(... units="imperial")` divides 1609.344 m by `avg_speed_mps`. The two formatters disagree because the underlying lap distance was synthesized in metric and nothing converts it.

## 3. Root cause — file:line evidence

### Bug 1 root cause

**Most likely:** the workout's `raw_payload` on Railway does NOT contain the `heartRateData` array, so `_maybe_apple_streams` falls through to its empty-series return, the streams endpoint sends `{}`, and the chart renders the empty state.

Code path:

- `backend/routers/activities.py:710-797` `_maybe_apple_streams`: `hr_series = payload.get("heartRateData")` (line 744). If missing OR not a non-empty list, `streams["heartrate"]` and `streams["time"]` are never set. Returns `{}` (line 797).
- `backend/routers/activities.py:525-529`: when `source=apple_health`, the route returns `apple_streams` directly — `{}` reaches the client as 200.
- `frontend/src/api/activities.ts:143-151` `fetchActivityStreams`: returns `{}`.
- `frontend/src/components/ActivityDetail.tsx:79-90` `handleLoadStreams`: `setStreams(s)` — `streams` is now `{}` (truthy).
- `frontend/src/components/activity/AnalysisChart.tsx:56-85`: `chartData = streams.time.map(...)` where `streams.time` is `undefined`, so `time` defaults to `[]`, `chartData = []`.
- `AnalysisChart.tsx:282-286`: `{streams && chartData.length === 0}` → renders "No stream data available."

### Bug 2 root cause

**Backend always synthesizes splits in fixed metric buckets, unconditionally.** No part of the path reads a user unit preference; the unit preference is frontend-only.

- `backend/services/apple_health_ingest.py:42-48` defines `_SPLIT_METERS = {"run": 1000.0, "walk": 1000.0, "hike": 1000.0, "ride": 5000.0, "swim": 100.0}`. No imperial variant, no preference read.
- `_derive_laps` (line 204-267) divides `parsed.distance_m` into chunks of `split_m = 1000.0` for runs, with a trailing remainder lap.
- `backend/services/apple_workout_detail.py:124` sets `detail["splits_synthetic"] = bool(workout.laps)`.
- `frontend/src/components/activity/SplitsTable.tsx:63` displays `distanceWithUnit(lap.distance, units)`. For 1000 m input with `units="imperial"`, `distanceToDisplay` returns `{value:"1000", unit:"m"}` because 1000 is under the mile threshold.

## 4. Ranked hypotheses

### Bug 1

**H1 (most likely).** HAE export config doesn't include `heartRateData` for this workout. Backend writes `raw_payload` without it; streams endpoint correctly returns `{}`; frontend correctly renders empty state. Implicated: `backend/routers/activities.py:744`, `backend/services/apple_health_parser.py:107`, `frontend/src/components/activity/AnalysisChart.tsx:282-286`. Falsify with Railway query on `raw_payload::jsonb -> 'heartRateData'`.

**H2 (plausible, second).** `heartRateData` is present but in a scalar `{qty, units}` shape rather than a list. `_maybe_apple_streams` only handles the list shape; the dict shape is silently dropped at `backend/routers/activities.py:744-775`. `derive_hr_samples_from_raw_payload` in `hr_zones.py:229-278` already handles both shapes — this is an inconsistency, not parity.

**H3 (speculative).** Date format diverges from `"YYYY-MM-DD HH:MM:SS ±HHMM"` and strptime raises per entry. Less likely to cause empty stream (fallback values are appended).

### Bug 2

**H1 (single, confirmed).** Backend hard-codes 1 km splits; no concept of user unit preference; frontend displays "1000 m" because the input falls under the imperial "render in meters" branch.

## 5. Recommended fix

### Bug 1 — defensive two-pronged fix (no Railway DB access available)

Since H1 and H2 cannot be distinguished without a DB query, implement both. Both are independently useful.

1. **Backend** (`backend/routers/activities.py:744`): mirror `derive_hr_samples_from_raw_payload`'s dual-shape handling. When `heartRateData` is a scalar dict `{qty, units}` (Aggregate-workout-data mode), still surface something. Single-sample series won't chart meaningfully, but at least the absence isn't silent.
2. **Frontend** (`frontend/src/components/activity/AnalysisChart.tsx:282-286`): when `source === 'apple_health'` and `streams === {}`, render an Apple-specific empty-state message that points the user at HAE's export settings ("Workout Heart Rate Data" toggle). This is the more user-visible fix and helps if H1 is correct.

**Regression tests:**
- `tests/test_routers/test_activities.py` — `test_streams_for_apple_handles_scalar_heartrate_dict_shape` (assert dict-shape doesn't crash and either returns single-sample stream or `{}` consistently).
- `frontend/src/components/activity/AnalysisChart.test.tsx` — assert Apple-specific empty-state copy renders when `source="apple_health"` and `streams={}`.

### Bug 2 — backend + frontend coordinated fix (no migration)

Adopt the request-time binning route. DB stays system-agnostic.

1. **Backend** (`backend/services/apple_workout_detail.py`): accept a `units` parameter and re-bin laps from totals (mile splits for imperial, km for metric). Drop dependence on the stored `workout_laps` rows for synthetic splits, OR continue storing metric laps in DB and re-bin only when serializing for `units=imperial`.
2. **Backend** (`backend/routers/activities.py`): plumb a `units: Literal["metric", "imperial"]` query parameter from the activity detail GET endpoint through to `apple_workout_detail`.
3. **Frontend** (`frontend/src/api/activities.ts:138` `fetchActivity`): append `?units=<pref>` from `useUnits()`.
4. **Frontend** (`frontend/src/components/ActivityDetail.tsx:36-39`): pass `units` into `fetchActivity`.
5. **Frontend** (`frontend/src/components/activity/SplitsTable.tsx:35-37`): soften the caption — current copy ("Apple Health did not provide lap markers") implies a failure; reality is HAE/Shortcuts cannot expose lap markers at all (per `docs/research/apple-health-shortcuts.md:14-30`).

**Regression tests:**
- `tests/test_services/test_apple_workout_detail.py` — `test_apple_detail_returns_imperial_mile_splits_when_units_imperial`, asserting a 5.51 mi run yields 5 mile laps + remainder when `units="imperial"` and 8 km laps + remainder when `units="metric"`.
- `tests/test_routers/test_activities.py` — `test_get_apple_activity_passes_units_query_param`.
- Frontend (`frontend/src/components/activity/__tests__/SplitsTable.test.tsx` if it exists or co-located) — assert imperial-pref renders "1.00 mi" rows.

## 6. Out-of-scope items spotted (NOT fixing in this PR)

- `backend/models/*.py` use `from sqlalchemy.dialects.sqlite import JSON` despite Postgres in prod. Cosmetic.
- `frontend/src/components/ActivityDetail.tsx:103-112` auto-fetches Apple streams unconditionally; could gate on `streams_cached`.
- `backend/routers/activities.py:519-523` duplicates the `("strava", "apple_health")` literal set with the shoe endpoint at 295-323.
- `backend/services/apple_health_parser.py:107` `extra="allow"` is untested for the series + extras combo.
