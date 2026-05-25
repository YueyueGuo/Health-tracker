# Apple Health Workout Detail View

## 1. Feature summary

Apple Health workouts (ingested via Health Auto Export into `health_data_points` + `workouts` + `workout_laps`) currently have no detail page — the history feed deliberately suppresses the click target for Apple-only rows (`frontend/src/lib/historyEvents.ts:157-170`). This feature wires Apple workouts into the existing `/activities/:id` detail view so the same overall metrics, HR-zone histogram, pace-zone histogram, derived splits, and analysis chart show up — gracefully degrading the sections Apple cannot populate (power zones, GPS-driven pace zones, true lap markers). The user gets one detail UI for both sources and stops being confronted with non-clickable Apple rows in the history.

## 2. Affected surfaces

| Surface | Change | Files |
|---|---|---|
| `backend/routers/activities.py` | Route `GET /activities/{id}` to Apple `Workout` when no Strava `Activity` matches the id; add a builder analogous to `_activity_summary` that hydrates HR zones, derived splits, and weather (if linked) | `backend/routers/activities.py` (existing) |
| `backend/services/hr_zones.py` | Add a pure helper that synthesizes a `zones_data`-shaped HR bucket list from a sample series + user max HR / LTHR | `backend/services/hr_zones.py` (existing) |
| `backend/services/` | New small service that turns an Apple `Workout` (+ its `WorkoutLap` rows + `raw_payload.heartRateData`) into the same dict shape `_activity_summary` returns | new: `backend/services/apple_workout_detail.py` |
| `backend/services/sport_mapping.py` | Add `normalized_to_strava_view(name)` helper so the frontend's existing `Run/Ride/Strength` switch in `ActivityDetail.tsx` can be driven from Apple's normalized `activity_type` ("run" → "Run", "ride" → "Ride", "strength" → "WeightTraining") | `backend/services/sport_mapping.py` (existing) |
| `backend/routers/activities.py` | `GET /activities/{id}/streams` — return cached HR / velocity stream from `raw_payload.heartRateData` (and `route[]` if present) when the id resolves to an Apple workout; never call Strava | same router file |
| `frontend/src/api/activities.ts` | Extend `ActivityDetail` typing with two optional flags: `zones_synthetic?: boolean` (derived, not sensor-based) and `splits_synthetic?: boolean`; widen `source` already exists | `frontend/src/api/activities.ts` |
| `frontend/src/components/activity/ZonesBar.tsx` | Render a "Synthetic — computed from raw HR samples" subtitle when `sensor_based === false` on the HR zone entry; hide power-zone card outright for Apple | `frontend/src/components/activity/ZonesBar.tsx` |
| `frontend/src/components/activity/SplitsTable.tsx` | Render "Auto-split every 1 km / 5 km" caption when laps are derived (no per-lap HR); already tolerant of nulls | `frontend/src/components/activity/SplitsTable.tsx` |
| `frontend/src/components/activity/AnalysisChart.tsx` | When `source === "apple_health"`, change the "Fetched on demand from Strava" copy and disable the lazy-load button (streams come pre-cached from `raw_payload`); hide Power toggle when no watts | `frontend/src/components/activity/AnalysisChart.tsx` |
| `frontend/src/components/activity/ActivityDetailRide.tsx` / `ActivityDetailRun.tsx` | No structural changes — they already degrade gracefully on null power/cadence/elevation | unchanged |
| `frontend/src/lib/historyEvents.ts` | Remove the `isAppleOnly` short-circuit so Apple cards become clickable | `frontend/src/lib/historyEvents.ts` (lines 157-170) |
| `alembic/` | **None.** All Apple data already lives in `health_data_points` / `workouts` / `workout_laps` + the `raw_payload` JSON column | n/a |
| Tests | New router + service tests; new frontend tests for synthetic-zone caption + apple-routed click target | `tests/test_routers/test_activities.py`, new `tests/test_services/test_apple_workout_detail.py`, new `tests/test_services/test_hr_zones_apple.py`, frontend test additions |

## 3. Data model

**No new tables, no new columns.** Everything we need is already present:

* `workouts` (id, activity_type, duration_s, distance_m, avg_speed_mps, avg_hr, max_hr, active_energy_kcal, total_elevation_m, activity_id) — `backend/models/workout.py:30-66`
* `workout_laps` (workout_id, lap_index, distance_m, elapsed_time_s, avg_speed_mps, avg_hr, max_hr, …) — `backend/models/workout.py:69-98`
* `health_data_points.raw_payload` (JSON) — preserves HAE `heartRateData`, `route`, `stepCadence`, etc. — `backend/models/health_data_point.py:73-75` and `backend/services/apple_health_parser.py:104-107`
* `user_profile.payload` — already carries `maxHr` and `lthr` strings (`backend/routers/profile.py:120,194`) which we read for HR-zone synthesis

**Relationship to existing tables.** When an Apple workout has won dedup against a Strava activity, `workouts.activity_id` points at the Strava row; we use that link to surface the linked Strava activity's `weather` snapshot and `WeatherSnapshot` row (read-only). When `activity_id` is NULL (Apple-only), weather is omitted.

**ID space.** Both Strava `Activity` and Apple `Workout` rows use the same `int` PK space conceptually but live in different tables. `activity_feed.py:81` already uses `health_data_points.id` as the row's `id` in `_apple_workout_summary`, and history cards link via `/activities/${a.id}` (`frontend/src/lib/historyEvents.ts:170`). So a single integer arrives at the detail endpoint — the router must check both tables.

**Open question for the researcher**: is there a real risk of an Activity.id colliding with a HealthDataPoint.id? Both are integer autoincrement PKs in independent tables. Spec answer: yes, ids overlap. Disambiguation strategy: query Activity first; if it returns a row, treat as Strava. Otherwise query `HealthDataPoint` filtered by `source='apple_health' AND data_type='workout'`. If both happen to share the same numeric id, **Strava wins for routing**, because history cards for Apple-wins-dedup rows route via the Apple `health_data_point.id` and there is no Strava row at that exact integer (Strava ids are in `Activity.id`, a disjoint sequence). Confirm by walking the existing `list_activity_feed` output — Apple-wins cards point at `dp.id`, never `activity.id`.

**Backfill needs.** None — the only data we read already lives in rows ingested by `apple_health_ingest.py`.

## 4. External integration

**None.** This is entirely an internal stitching feature — no new Apple-side calls, no new auth, no Strava calls.

Open questions worth a researcher pass before code lands:

* **HAE `heartRateData` shape.** Parser comments at `backend/services/apple_health_parser.py:91-95` document that HAE emits per-minute time series `[{date, qty, units, source}, ...]` when the user disables "Aggregate workout data". Verify on a real HAE export that the series cadence is dense enough to drive a meaningful HR-time chart and zone histogram. If the series is sparse (e.g. per-minute only), we accept a coarser zone bucket count.
* **HAE `route` / GPS shape.** Same parser note implies route may be present but is not parsed into typed columns in v1. Confirm whether HAE actually ships per-second lat/lng/speed/elevation arrays. If yes, we can compute a velocity stream for runs (drives the pace-zone histogram and the Analysis chart's secondary line). If not, the run detail view will hide the pace section and show only HR.
* **HAE `stepCadence` shape.** Same — series vs scalar. If present we can light up the run cadence metric.
* **Power.** HAE on Apple Watch does **not** expose cycling power. Confirm with a current HAE export. Assumption: power zone card stays hidden for all Apple rides.
* **Max HR / LTHR.** Confirm the profile field aliases (`backend/routers/profile.py:120,194` use `maxHr` and `lthr` strings) so the HR-zone synthesizer reads from the right keys.

## 5. Backend tasks

1. **(service)** Create `backend/services/apple_workout_detail.py` with:
   * `async def get_apple_workout_detail(db, hdp_id) -> dict | None` — fetches the `HealthDataPoint` + joined `Workout` + ordered `WorkoutLap` rows; returns a dict in the same shape `_activity_summary` returns, plus `laps`, `zones`, `weather`, `streams_cached`, `hr_drift`, `pace_hr_decoupling` (None for Apple), `power_hr_decoupling` (always None), `raw_data`.
   * Maps `Workout` fields → `ActivitySummary` fields the same way `_apple_workout_summary` already does (`backend/routers/activities.py:368-430`); reuse that helper.
   * Maps each `WorkoutLap` → `ActivityLap`-shaped dict (lap_index, distance, elapsed_time, moving_time, average_speed=avg_speed_mps, average_heartrate=avg_hr, max_heartrate=max_hr, total_elevation_gain=total_elevation_m, average_cadence=avg_cadence, average_watts=None, pace_zone=None, hr_zone=None).
   * Calls a new `synthesize_hr_zones_from_samples()` helper (see step 3) to build the `zones` entry when both raw HR samples and the user's max HR are available; otherwise `zones=None`.
   * Adds two flag fields on the response: `zones_synthetic: bool` and `splits_synthetic: bool`.
2. **(service)** In `backend/services/hr_zones.py`, add:
   * `def synthesize_hr_zones_from_samples(samples: list[float], *, max_hr: int, lthr: int | None = None) -> dict | None` — produces a 5-bucket distribution matching the existing `zones_data` entry shape (`{"type": "heartrate", "distribution_buckets": [...], "sensor_based": False, "points": N}`). Default zone breakpoints: `0.5/0.6/0.7/0.8/0.9` of max HR (consistent with Strava's typical 5-bucket default; LTHR-anchored variant if LTHR present).
   * `def derive_hr_samples_from_raw_payload(raw_payload: dict) -> list[float] | None` — extracts a flat float list from the HAE `heartRateData` field (either scalar HAEQty → single-element list, or series → one float per entry).
3. **(router)** In `backend/routers/activities.py:115-172`, modify `get_activity`:
   * Query `Activity` first.
   * On miss, query `HealthDataPoint` by id, filtering `source='apple_health' AND data_type='workout'`; on hit, delegate to the new `apple_workout_detail` service and return its dict.
   * On miss in both, 404.
4. **(router)** In `backend/routers/activities.py:274-317` (`get_activity_streams`):
   * Same lookup pattern. For Apple, return `{"heartrate": [...], "time": [...], "velocity_smooth": [...]}` reconstructed from `raw_payload` (HAE `heartRateData` time series → `heartrate` + `time` arrays; HAE `route` if present → `velocity_smooth`).
   * Never call Strava; if the payload has no series, return `{}` (the chart already degrades).
5. **(router)** In `backend/routers/activities.py:213-243` (`classify_activity`):
   * Add an early-return when the id resolves to an Apple workout. Classifier is a Strava-only feature; return `{"classified": False, "reason": "apple_health workouts are not classified yet"}`.
6. **(service helper)** Add `normalized_to_strava_view(name: str) -> str` in `backend/services/sport_mapping.py` so the apple detail's `sport_type` field returns CamelCase that the frontend's `classifyActivity()` (used in `ActivityDetail.tsx:144`) already handles ("Run", "Ride", "WeightTraining", "Walk", "Hike"). Today `_apple_workout_summary` passes Apple's lowercase normalized form ("run", "ride") which frontend `classifyActivity` does not recognize — currently shipped as a latent bug worth fixing in the same PR.
7. **(router) RPE write path**: `PATCH /activities/{id}/feedback` (`backend/routers/activities.py:175-210`) currently writes to `Activity`. Either:
   * (a) keep it Strava-only and the frontend RPE card hides for Apple, OR
   * (b) extend the patch handler to write to a new column on `HealthDataPoint` / `Workout`.
   Recommend **(a) for v1**: keep scope tight, defer RPE for Apple. Frontend hides `RPECard` when `source === "apple_health"`.

## 6. Frontend tasks

1. **(types)** `frontend/src/api/activities.ts:95-104` — add `zones_synthetic?: boolean`, `splits_synthetic?: boolean` to `ActivityDetail`. Extend `ZoneDistribution.sensor_based` (already optional, line 91).
2. **(routing)** `frontend/src/lib/historyEvents.ts:157-172` — remove the `isAppleOnly` branch; always emit `navigateTo: /activities/${a.id}`.
3. **(ActivityDetail container)** `frontend/src/components/ActivityDetail.tsx` — no structural change beyond passing through `activity.source` (it already does). The sport-view switch at line 144 will start working for Apple rows once the backend returns CamelCase sport_type.
4. **(ZonesBar)** `frontend/src/components/activity/ZonesBar.tsx` — under the HR heading, render a small "computed from raw HR samples" sub-caption when the zone entry has `sensor_based === false`. Power-zone entry is already filtered out by `totalSeconds > 0` so it'll vanish naturally for Apple.
5. **(SplitsTable)** `frontend/src/components/activity/SplitsTable.tsx` — show "Auto-split — Apple Health did not provide lap markers" caption when the parent passes `splits_synthetic=true`. Avg-HR cell already handles null with em-dash.
6. **(AnalysisChart)** `frontend/src/components/activity/AnalysisChart.tsx:136-153` — branch the copy on `source`. For Apple: "Per-sample heart rate from Apple Health." Hide the Power toggle when `mode === "ride"` and `streams.watts` is empty.
7. **(RPECard)** `frontend/src/components/ActivityDetail.tsx:108-114` — wrap with `{activity.source !== "apple_health" && <RPECard … />}`. Mirror the same gate for `LocationPicker` (lines 115-120) and the workout-insight panel (lines 122-128).
8. **(SourceBadge tests)** Existing test at `frontend/src/components/activity/SourceBadge.test.tsx` already covers the apple case; just confirm.

## 7. Migration tasks

**None.** No schema changes. All data already lands via the existing `37d57cfdb27d_apple_health_workouts.py` migration. Confirm current head is `37d57cfdb27d` before merge (the AGENTS.md doc still names `c2f7a4e91b85`, which is stale — a separate-and-prior migration not in this branch's chain).

## 8. Tests to add

Backend
* `tests/test_services/test_apple_workout_detail.py` (new)
  * Returns None for unknown id
  * Returns dict in `_activity_summary` shape for Apple-only row (no linked `Activity`)
  * Returns dict including derived laps for run/ride/walk; empty laps for "other"
  * Returns `zones=None` when no `heartRateData` series and no `avg_hr`
  * Returns synthesized HR zones (5 buckets, `sensor_based=False`) when series present
  * `sport_type` is CamelCase ("Run", "Ride", "WeightTraining")
* `tests/test_services/test_hr_zones_apple.py` (new)
  * `synthesize_hr_zones_from_samples`: 5 buckets summing to N, breakpoints at max_hr * (0.5, 0.6, 0.7, 0.8, 0.9)
  * Empty samples → None
  * LTHR-anchored variant when LTHR present
* `tests/test_routers/test_activities.py` (extend)
  * `GET /activities/{id}` resolves to Apple workout when the id is a HealthDataPoint id; 404 when neither
  * `GET /activities/{id}/streams` returns reconstructed `{heartrate, time}` from `raw_payload.heartRateData`
  * `POST /activities/{id}/classify` returns `{"classified": False, ...}` for Apple
* `tests/test_routers/test_activities_feedback.py` (extend) — `PATCH …/feedback` returns 4xx for Apple (or 200 no-op — pick one in step 5)

Frontend
* `frontend/src/lib/historyEvents.test.ts` — update the two assertions that expect `navigateTo: null` for Apple rows; they should now produce links
* `frontend/src/components/activity/ZonesBar.test.tsx` (new or extend) — "computed from raw HR samples" caption when `sensor_based=false`
* `frontend/src/components/ActivityDetail.test.tsx` (extend existing at `frontend/src/components/ActivityDetail.test.tsx`) — render Apple detail; assert RPE / LocationPicker / Insight panels are hidden

## 9. Parallelism plan

```
phase 1 (parallel):
  - integration-researcher  → answer Section 4 open questions
                              (HAE heartRateData / route shape, watch power)
  - backend-engineer A      → implement Section 5 tasks 1, 2, 6
                              (apple_workout_detail service + hr-zone synth
                               + sport_mapping helper) — pure functions,
                               easy to test in isolation
  - frontend-engineer A     → Section 6 tasks 1, 2, 7
                              (types, history routing, hiding RPE/Location/Insight)

phase 2 (parallel, depends on phase 1):
  - backend-engineer B      → Section 5 tasks 3, 4, 5
                              (router wiring for detail, streams, classify)
  - frontend-engineer B     → Section 6 tasks 3, 4, 5, 6
                              (ZonesBar caption, SplitsTable caption,
                               AnalysisChart copy)

phase 3 (sequential):
  - test-runner             → pytest + frontend typecheck + frontend tests
  - code-reviewer
```

Migration agent is not needed for this feature.

## 10. Recommended approach

**Option (a): extend the existing `/activities/{id}` endpoint to be source-agnostic.** Justification:

* The frontend already routes Apple-wins-dedup rows to `/activities/${dp.id}` and Apple-only rows would join the same URL once the click-through is unblocked — so the frontend is already source-agnostic.
* `_apple_workout_summary` already exists for the list endpoint (`backend/routers/activities.py:368-430`); detail just needs to do the same trick plus laps/zones/streams.
* The alternative ("add a parallel `/apple-workouts/{id}` endpoint and a shared component") doubles the URL surface and forces every consumer (history cards, future deep-links from chat insights) to know which source they're dealing with, which the system has already decided to keep opaque at the frontend layer.

The cost is one router that branches on table-lookup miss — small, contained, and matches the existing list-feed pattern.

## 11. Gap analysis: data sufficiency by detail section

| Detail-page section | Apple data status | Notes |
|---|---|---|
| Header (name, sport, date, source badge) | **Sufficient as-is** | `_apple_workout_summary` already maps these; small fix: emit CamelCase `sport_type` so the `Run`/`Ride`/`Strength` switch in `ActivityDetail.tsx:144` resolves correctly. |
| Overall metrics: distance / time / pace or speed / HR avg+max / calories / elevation | **Sufficient as-is** | All present on `workouts` (distance_m, duration_s, avg_speed_mps, avg_hr, max_hr, total_elevation_m, active_energy_kcal). |
| Overall metrics: power | **Insufficient** | HAE / Apple Watch does not expose cycling power. Section degrades — `average_power` is None and the `Power` metric cell is already conditional in `ActivityDetailRide.tsx:95`. |
| Overall metrics: cadence | **Sufficient with transformation** | HAE emits `stepCadence`; needs unit normalization. Only populated when present. |
| Overall metrics: TSS / suffer_score | **Insufficient** | Apple has no equivalent. Already conditional in `ActivityDetailRide/Run.tsx:103`. |
| Weather strip | **Sufficient with link** | Available only when `workouts.activity_id` points at a Strava row that already enriched weather. Apple-only workouts have no weather snapshot. |
| Analysis chart (HR + secondary line) | **Sufficient with transformation** | HR series comes from `raw_payload.heartRateData` (when HAE "Aggregate workout data" is off). Pace series from `raw_payload.route` if present, otherwise hide secondary. Power line always hidden. Re-shaped to look like Strava streams. Replace the "Fetched on demand from Strava" copy. |
| HR zone histogram | **Sufficient with transformation** | Compute the 5-bucket distribution from raw HR samples using user `maxHr` (and optional `lthr`) from `user_profile`. Mark with `sensor_based=false` so UI can disclose. |
| Pace zone histogram | **Sufficient with transformation, with caveat** | Only feasible when HAE ships per-sample velocity (via `route[]`); otherwise hide. No user-configurable pace zones today, so use distance-bucketed pace thresholds (e.g. by training-level defaults). Open question for researcher. |
| Power zone histogram | **Insufficient** | No power data; hide the entire power-zone card. `ZonesBar.tsx` already filters zero-total entries, so emitting nothing is enough. |
| Lap splits | **Sufficient with transformation** | `workout_laps` already populated by `apple_health_ingest._derive_laps` (1 km / 5 km synthetic splits). No per-lap HR or power per the current derivation. Render with "auto-split" caption. Future improvement: re-attribute HR samples to each lap window. |
| RPE / user notes | **Out of scope for v1** | RPE column lives on `activities`, not on `workouts`. Hide the card for Apple rows; track as a follow-up. |
| Workout insight (LLM) | **Out of scope for v1** | Insights pipeline is keyed on Strava activity ids and gated by `enrichment_status == 'complete'`. Hide for Apple. |
| Drift / decoupling metrics (HR drift, pace-HR, power-HR) | **Sufficient with transformation for HR drift; otherwise out of scope** | `compute_hr_drift` reads from `activity_streams` keyed by `Activity.id`; we'd need a variant that reads from a reconstructed series. Defer all three to a follow-up. |

## 12. Risks and rollback

* **Risk: id collision between `activities.id` and `health_data_points.id`.** Both are independent autoincrement integers. Mitigation: detail router tries `Activity` first, then falls back to Apple. History cards for Apple rows already navigate using `health_data_points.id` — the only ambiguous path is a direct URL hit where the same numeric id exists in both tables, which would resolve to the Strava row (existing behavior). Acceptable trade-off; document in a code comment.
* **Risk: large `raw_payload` blobs.** `health_data_points.raw_payload` may contain per-second `heartRateData` arrays. Reconstructing streams reads the whole row each detail call. Mitigation: stream endpoint is already lazy and only invoked on user click. No additional caching needed at v1 scale.
* **Risk: Apple workouts without HR samples render an empty zones card.** Existing `ZonesBar` already returns null on empty buckets — no regression.
* **Production: Railway.** No migration, no env-var change, no third-party calls. Rollback is "revert the PR" — no DB state to unwind.
* **Rollback plan**: single PR; revert reverts both backend router branching and frontend history-link change. The frontend `isAppleOnly` short-circuit reappears and Apple rows go back to non-clickable. No data loss.

## 13. Files of interest (read paths)

* `/home/user/Health-tracker/backend/routers/activities.py:115` — `get_activity` (the Strava-only detail endpoint to extend)
* `/home/user/Health-tracker/backend/routers/activities.py:274` — `get_activity_streams` (lazy Strava streams endpoint to extend)
* `/home/user/Health-tracker/backend/routers/activities.py:368` — `_apple_workout_summary` (existing list-shape mapper to reuse)
* `/home/user/Health-tracker/backend/services/activity_feed.py:62-105` — Apple feed query pattern to mirror
* `/home/user/Health-tracker/backend/services/apple_health_ingest.py:204-267` — synthetic-lap derivation already in place
* `/home/user/Health-tracker/backend/services/apple_health_parser.py:91-126` — HAE shape, including `heartRateData` / `route` preservation note
* `/home/user/Health-tracker/backend/services/hr_zones.py:33-95` — existing zone bucket shape + summarizer (template for synthesis helper)
* `/home/user/Health-tracker/backend/models/workout.py` — `Workout`, `WorkoutLap`
* `/home/user/Health-tracker/backend/models/health_data_point.py` — polymorphic anchor + `raw_payload`
* `/home/user/Health-tracker/backend/services/sport_mapping.py:24-87` — needs the new `normalized_to_strava_view` helper
* `/home/user/Health-tracker/frontend/src/components/ActivityDetail.tsx:143-157` — sport-view switch driven by CamelCase
* `/home/user/Health-tracker/frontend/src/components/activity/ZonesBar.tsx` — HR / pace / power renderer (degrades empty)
* `/home/user/Health-tracker/frontend/src/components/activity/SplitsTable.tsx` — null-safe already
* `/home/user/Health-tracker/frontend/src/components/activity/AnalysisChart.tsx:136-153` — copy + lazy-fetch UI to adjust
* `/home/user/Health-tracker/frontend/src/lib/historyEvents.ts:157-172` — the `isAppleOnly` short-circuit to remove
* `/home/user/Health-tracker/frontend/src/api/activities.ts:95-104` — `ActivityDetail` typing
* `/home/user/Health-tracker/alembic/versions/37d57cfdb27d_apple_health_workouts.py` — current head; no new migration needed
