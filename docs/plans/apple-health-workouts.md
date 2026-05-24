# Apple Health Workouts Integration

## 1. Feature summary

Add a webhook-based ingestion path so the user's iOS Shortcut can POST Apple Health workouts directly into the Health Tracker API. Apple Health becomes the **canonical** source whenever the same workout also exists in Strava (loose match on type + start-time ±10 min). Workouts continue to land in the same UI list as today, with a small **Apple / Strava source badge** in the history feed. The schema is reshaped to a polymorphic `health_data_points` base table with a typed `workouts` subtype + `workout_laps` child, so future HealthKit data types (steps, sleep, etc.) plug in as new `data_type` values without further refactor.

## 2. Goal & non-goals

**Goal**
- Idempotent webhook for Apple Health workouts (workout + lap metrics).
- Cross-source dedup (Apple wins over Strava) at both Apple-ingest time and Strava-sync time.
- Source badge in the workout list.
- A schema shape that scales to other HealthKit `data_type`s without further migrations of the base table.

**Non-goals (this PR)**
- Ingesting non-workout HealthKit data (steps, HRV, sleep) — only the table shape needs to anticipate them.
- A native iOS app or HealthKit OAuth/server API (Apple does not offer one — see §5).
- Backfilling years of historical Apple Health data automatically; one-shot file export can be a follow-up.
- Changing the Whoop / Eight Sleep schemas.

## 3. Affected surfaces

| Surface | Change | Files |
|---|---|---|
| `backend/models/` | New polymorphic base + workout subtype + laps; mapping table | `backend/models/health_data_point.py` (new), `backend/models/workout.py` (new), `backend/models/__init__.py` (export) |
| `backend/models/activity.py` | Add `source` + `external_id` + `superseded_by_id` columns (back-compat shim) | `backend/models/activity.py` |
| `backend/clients/` | No external HTTP client; payload parser lives in `services/` | n/a |
| `backend/routers/` | New webhook endpoint + shared-secret auth dep | `backend/routers/apple_health.py` (new), `backend/main.py` (register) |
| `backend/services/` | Ingest service, dedup service, activity-type mapping | `backend/services/apple_health_ingest.py` (new), `backend/services/workout_dedup.py` (new), `backend/services/sport_mapping.py` (new) |
| `backend/services/sync.py` | After Strava upsert, run dedup against any existing Apple Health workouts in window | `backend/services/sync.py` |
| `backend/config.py` | `apple_health.ingest_token` env-backed setting | `backend/config.py` |
| `alembic/` | New revision off current head | `alembic/versions/<rev>_apple_health_workouts.py` (new) |
| `frontend/src/api/` | `appleHealth.ts` (optional; only manual-trigger endpoints if added later); update `ActivitySummary` for `source`/`external_id` | `frontend/src/api/activities.ts`, `frontend/src/api/appleHealth.ts` (optional) |
| `frontend/src/components/history/` | Source badge in event card | `frontend/src/components/history/HistoryEventCard.tsx`, `frontend/src/lib/historyEvents.ts` |
| `frontend/src/components/activity/` | Source badge in activity header | `frontend/src/components/activity/ActivityHeader.tsx` |
| `tests/` | New test files for client/parser, dedup, router, mapping | `tests/test_services/test_apple_health_ingest.py`, `tests/test_services/test_workout_dedup.py`, `tests/test_services/test_sport_mapping.py`, `tests/test_routers/test_apple_health.py` |
| `docs/decisions/` | ADR documenting Apple-canonical + polymorphic base | `docs/decisions/0002-apple-health-polymorphic-workouts.md` (new) |

## 4. Architecture overview

```
iOS Shortcut  ──POST──▶  /api/ingest/apple-health/workouts (X-Apple-Health-Token)
                              │
                              ▼
                  AppleHealthIngestService
                  ├─ parse payload (workout + events/laps)
                  ├─ upsert HealthDataPoint(source="apple_health", data_type="workout", external_id=HK UUID)
                  ├─ upsert Workout 1:1 child + WorkoutLap children
                  └─ WorkoutDedupService.match_against_strava(workout)
                        └─ find activities in [start-10m, start+10m] with mapped sport_type
                            → if hit: set strava activity.superseded_by_id = apple workout id

Strava sync  (services/sync.py phase A upsert)
                              │
                              ▼
              WorkoutDedupService.match_against_apple(new strava row)
                        └─ find Apple Health workouts in same window + mapped type
                            → if hit: set this strava row's superseded_by_id immediately
```

**Single-source canonical view**: `/api/activities` continues to be the unified workout list. We add a query param `?include_superseded=false` (default) so the default UI never sees a Strava row that has been superseded by an Apple Health workout.

## 5. Data model

### Decision: polymorphic with a typed subtype table

We keep the existing `activities` table (Strava-shaped, already wired into classifier, weather, locations, insights, scheduler) and **add two new tables** alongside it:

#### `health_data_points` (polymorphic base)
| col | type | notes |
|---|---|---|
| `id` | Integer PK | autoinc |
| `source` | String(32) NOT NULL, indexed | enum-ish: `apple_health`, `strava`, `whoop`, `eight_sleep` (extensible) |
| `data_type` | String(32) NOT NULL, indexed | `workout`, `steps`, `sleep`, `heart_rate`, … |
| `external_id` | String(128) NOT NULL | natural key per (source, data_type) — Apple HK UUID, Strava activity id as string, etc. |
| `start_time` | DateTime(tz=True) NOT NULL, indexed | aligned with how `activities.start_date` is stored (naive UTC per `time_utils`) |
| `end_time` | DateTime(tz=True) NULL | |
| `superseded_by_id` | Integer FK → `health_data_points.id` NULL, indexed | "the canonical row that replaced this one" |
| `raw_payload` | JSON NULL | original Shortcut payload / Strava blob |
| `created_at` | DateTime(tz=True) server_default `now()` | |
| `updated_at` | DateTime(tz=True) server_default `now()` onupdate `now()` | |

**Unique constraint**: `(source, data_type, external_id)`.
**Index**: `(data_type, start_time)` to make dedup window scans cheap.

#### `workouts` (typed subtype, 1:1 with health_data_points)
| col | type | notes |
|---|---|---|
| `id` | Integer PK, also FK → `health_data_points.id` ON DELETE CASCADE | "joined table inheritance" style |
| `activity_type` | String(48) NOT NULL, indexed | normalized: `run`, `ride`, `walk`, `hike`, `strength`, `swim`, … (output of `sport_mapping.normalize`) |
| `duration_s` | Integer NULL | |
| `active_energy_kcal` | Float NULL | |
| `distance_m` | Float NULL | |
| `avg_speed_mps` | Float NULL | |
| `avg_pace_s_per_km` | Float NULL | derived for runs/walks/hikes if speed missing |
| `avg_hr` | Float NULL | |
| `max_hr` | Float NULL | |
| `total_elevation_m` | Float NULL | |
| `activity_id` | Integer FK → `activities.id` NULL, indexed | back-link to the (deduped) Strava row, if any |

#### `workout_laps` (mirrors `activity_laps` shape)
| col | type | notes |
|---|---|---|
| `id` | Integer PK | autoinc |
| `workout_id` | Integer FK → `workouts.id` ON DELETE CASCADE, indexed | |
| `lap_index` | Integer NOT NULL | |
| `name` | String NULL | (e.g. "Lap 1") |
| `elapsed_time_s` | Integer NULL | |
| `moving_time_s` | Integer NULL | (≈ elapsed for HK; same value if events lack pauses) |
| `distance_m` | Float NULL | |
| `start_time` | DateTime(tz=True) NULL | |
| `avg_speed_mps` | Float NULL | |
| `max_speed_mps` | Float NULL | |
| `avg_hr` | Float NULL | |
| `max_hr` | Float NULL | |
| `avg_cadence` | Float NULL | |
| `total_elevation_m` | Float NULL | |
| `split` | Integer NULL | (km/mi index) |
| Uniq | `(workout_id, lap_index)` | matches `activity_laps` pattern |

This mirrors `ActivityLap` (`backend/models/activity.py:122-149`) field-for-field for the metrics we have. Strength sets remain in `strength_sets` for now; the engineer should reuse `StrengthSet` rather than overloading `workout_laps`.

### `activities` table — additive changes
Add three nullable columns (all `op.add_column`, SQLite-safe):
- `source` String(32) NULL, default-backfilled to `'strava'` for all existing rows.
- `external_id` String(128) NULL, default-backfilled to `str(strava_id)`.
- `superseded_by_id` Integer NULL, indexed, **no FK in the migration** (cross-table reference into `health_data_points`; we keep it as a plain int + assert at the service layer to stay SQLite-friendly and avoid a circular dep on the alembic head).

The Strava→`health_data_points` projection is **not** done in this PR. Existing Strava activities continue to live in `activities`; dedup walks both tables. This avoids a multi-thousand-row data migration on Railway and keeps classifier/insights paths untouched. ADR `0002-apple-health-polymorphic-workouts.md` records this.

### How it relates to existing tables
- `workouts.activity_id` → `activities.id` is the join when both sources exist.
- `activities.superseded_by_id` points at a `health_data_points.id` (the Apple HK row) when Apple wins.
- `SleepSession`, `Recovery`, `WhoopWorkout` are untouched.

### Backfill
- Populate `activities.source = 'strava'` and `activities.external_id = strava_id::text` for every existing row.
- No projection of Strava activities into `health_data_points` (see ADR).

## 6. External integration (REVISED — Health Auto Export)

**Decision change (2026-05-24):** Research (`docs/research/apple-health-shortcuts.md`) confirmed that plain iOS Shortcuts cannot read workout records from Apple Health — only scalar samples. User has chosen **Health Auto Export (HAE)** as the ingestion path. HAE is a paid iOS app (~$8 one-time IAP) that exposes a "REST API Export" automation: on workout end, it POSTs a JSON payload to our backend.

### Auth & transport
- Method: shared-secret token via `X-Apple-Health-Token` header.
- Storage: env var `APPLE_HEALTH_INGEST_TOKEN`, surfaced through `backend/config.py` as `AppleHealthSettings`.
- Compare in constant time (`hmac.compare_digest`).
- 401 on missing/wrong; 503 if header present but token blank in env (misconfig signal).

### Sync model
- Push from HAE (iOS app, in the background, triggered by HKObserverQuery on workout writes).
- Single-user. No polling.
- HAE sends one POST per export event; payload contains a `data.workouts: [...]` array (may carry one OR many workouts in a single POST — engineer must handle batch).
- Idempotent: `(source='apple_health', data_type='workout', external_id=HAE workout id)` is the natural key. HAE's `id` field is documented to be the HKWorkout UUID stringified. Replay = upsert (replace lap rows wholesale).

### Expected payload shape (Health Auto Export)

HAE's documented JSON shape (per `github.com/Lybron/health-auto-export/wiki/API-Export---JSON-Format`):

```json
{
  "data": {
    "workouts": [
      {
        "id": "B6D2A7F1-3C8E-4A21-9F0B-1E5C7D8A2B3F",
        "name": "Running",
        "start": "2026-05-24 13:14:00 -0400",
        "end":   "2026-05-24 14:02:35 -0400",
        "duration": 2915.0,
        "activeEnergyBurned": { "qty": 412.3, "units": "kcal" },
        "totalEnergy":         { "qty": 488.0, "units": "kcal" },
        "distance":            { "qty": 8043.6, "units": "m" },
        "avgHeartRate":        { "qty": 154, "units": "count/min" },
        "maxHeartRate":        { "qty": 178, "units": "count/min" },
        "minHeartRate":        { "qty":  92, "units": "count/min" },
        "stepCount":           { "qty": 7821, "units": "count" },
        "stepCadence":         { "qty": 162, "units": "count/min" },
        "flightsClimbed":      { "qty": 8,   "units": "count" },
        "elevationUp":         { "qty": 64.0, "units": "m" },
        "avgSpeed":            { "qty": 2.76, "units": "m/s" },
        "maxSpeed":            { "qty": 4.21, "units": "m/s" },
        "location": "Outdoor",
        "heartRateData": [
          { "date": "2026-05-24 13:14:01 -0400", "qty": 124, "units": "count/min" },
          { "date": "2026-05-24 13:14:02 -0400", "qty": 128, "units": "count/min" }
        ],
        "heartRateRecovery": [
          { "date": "2026-05-24 14:03:35 -0400", "qty": 142, "units": "count/min" }
        ],
        "route": [
          { "lat": 40.7128, "lon": -74.0060, "altitude": 12.4, "timestamp": "2026-05-24 13:14:00 -0400" }
        ]
      }
    ]
  }
}
```

Notes for the parser:
- All numeric fields are wrapped as `{"qty": ..., "units": "..."}`. The parser must unwrap and validate units (reject if `distance.units != "m"`, etc., OR normalize — recommend reject for v1 to fail fast; HAE settings let the user pick metric).
- Timestamps: `"2026-05-24 13:14:00 -0400"` — space-separated, with offset. `datetime.strptime("%Y-%m-%d %H:%M:%S %z")` handles this. Convert to UTC, strip tzinfo to match `time_utils` convention.
- `name` is the display string (`"Running"`, `"Cycling"`, `"Pool Swim"`, etc.) — `sport_mapping.APPLE_TO_NORMALIZED` keys must be the lowercased display strings, NOT `HKWorkoutActivityType...` constants.
- `heartRateData[]` can be very large (per-second). Store the array as-is in `health_data_points.raw_payload` JSON, but do NOT derive `workout_laps` from it in v1. Derive laps from time-based splits (every 1 km for runs/walks/hikes, every 5 km for rides, every 100 m for swims). This is consistent with what we'd do for Strava when laps are absent.
- `route[]` similarly stored in `raw_payload`; no separate `workout_route` table in v1 (future feature).
- `location` is informational; we don't model indoor/outdoor explicitly in v1 (the `activities` table has an `is_indoor` boolean — engineer may copy it through if the field exists).

### Sport mapping (HAE display strings → normalized)

```python
APPLE_TO_NORMALIZED = {
    "running": "run",
    "outdoor run": "run",
    "indoor run": "run",
    "cycling": "ride",
    "outdoor cycle": "ride",
    "indoor cycle": "ride",
    "walking": "walk",
    "hiking": "hike",
    "pool swim": "swim",
    "open water swim": "swim",
    "traditional strength training": "strength",
    "functional strength training": "strength",
    "yoga": "yoga",
    "high intensity interval training": "hiit",
    "hiit": "hiit",
    "elliptical": "elliptical",
    "rowing": "row",
    "core training": "strength",
    "mixed cardio": "cardio",
}
```

Lookup must lowercase + strip the incoming `name`. Unknown values pass through as `"other"` (don't 422 — preserve the workout).

### Rate limits / error model
- No external rate limit (we own the endpoint).
- 200 on success; 401 bad token; 422 schema; on batch payload with mixed success, return per-workout result list.
- No retries server-side; HAE retries on network failure when its automation runs.
- Response shape: `{"results": [{"external_id": "...", "workout_id": 42, "dedup_matched_activity_id": 17, "lap_count": 3, "status": "created" | "updated"}, ...]}`.

## 7. Backend tasks (revised for HAE)

Ordered, each small enough for one agent run:

1. **Config**
   - Add `AppleHealthSettings` to `backend/config.py`: `ingest_token: str = ""` with prefix `APPLE_HEALTH_`.
   - Wire into `Settings` like the other sub-settings.
2. **Sport mapping module** (`backend/services/sport_mapping.py`)
   - `APPLE_TO_NORMALIZED: dict[str, str]` — lowercased display strings (see §6).
   - `STRAVA_TO_NORMALIZED: dict[str, str]` — Strava `sport_type` values (`Run`, `TrailRun`, `Ride`, `WeightTraining`, etc.).
   - `normalize_apple(name: str) -> str | None` — lowercases + strips before lookup; returns `"other"` for unknowns.
   - `normalize_strava(t: str) -> str | None`.
   - `same_activity(apple_name: str, strava_type: str) -> bool` — compares after normalization.
3. **Models**
   - Create `backend/models/health_data_point.py` (`HealthDataPoint`).
   - Create `backend/models/workout.py` (`Workout`, `WorkoutLap`), joined-table style with `HealthDataPoint`.
   - Add `source`, `external_id`, `superseded_by_id` columns to `Activity` in `backend/models/activity.py`.
   - Export from `backend/models/__init__.py`.
4. **HAE payload parser** (`backend/services/apple_health_parser.py`)
   - Pydantic models for the HAE payload shape (`HAEBatch`, `HAEWorkout`, `HAEQty`).
   - `HAEQty` is the wrapped `{"qty": float, "units": str}` shape; provide `.as_meters()`, `.as_kcal()`, etc. helpers that validate units and raise on mismatch.
   - `parse_hae_datetime(s: str) -> datetime` — handles `"YYYY-MM-DD HH:MM:SS ±HHMM"`, returns naive UTC.
   - One workout → an internal `ParsedWorkout` dataclass that the ingest service consumes.
5. **Dedup service** (`backend/services/workout_dedup.py`)
   - `match_apple_against_strava(db, workout) -> Activity | None` — query `activities` where `start_date` in `[workout.start_time − 10m, workout.start_time + 10m]` AND normalized sport matches; if found, set `activity.superseded_by_id = workout.id`.
   - `match_strava_against_apple(db, activity) -> Workout | None` — symmetric.
   - Pure functions: take `db` + row, persist via passed session, no commit (caller commits).
6. **Ingest service** (`backend/services/apple_health_ingest.py`)
   - `ingest_workouts(db, batch: HAEBatch) -> list[dict]`: iterate `batch.data.workouts`, for each:
     - upsert `HealthDataPoint(source='apple_health', data_type='workout', external_id=hae_workout.id)` + `Workout` 1:1 child.
     - Derive `workout_laps` via time-based splits (1 km for run/walk/hike, 5 km for ride, 100 m for swim — fall back to no laps if no distance). Replace laps wholesale on re-post.
     - Store full HAE workout JSON in `raw_payload`.
     - Call `workout_dedup.match_apple_against_strava`.
     - Append result dict `{"external_id", "workout_id", "dedup_matched_activity_id", "lap_count", "status"}`.
7. **Auth dependency** (`backend/routers/apple_health.py`)
   - `verify_apple_health_token(x_apple_health_token: str | None = Header(None))` FastAPI dependency using `hmac.compare_digest`.
8. **Router** (`backend/routers/apple_health.py`)
   - `POST /workouts` → accepts HAE batch, calls ingest service, returns `{"results": [...]}`.
   - `POST /ping` — returns `{"ok": true}` for the user to test HAE connectivity without writing data.
9. **Wire router** in `backend/main.py`: `app.include_router(apple_health.router, prefix="/api/ingest/apple-health", tags=["apple-health"])`.
10. **Strava sync hook** — in `backend/services/sync.py::_strava_phase_a`, after each new `Activity` is added, call `workout_dedup.match_strava_against_apple(self.db, activity)`. Wrap in `try/except` so a dedup failure never breaks Strava sync.
11. **Activity router updates** — `backend/routers/activities.py`:
    - Add `include_superseded: bool = Query(False)` to `list_activities`; when `False`, filter `Activity.superseded_by_id.is_(None)`.
    - Add `source` and `external_id` to `_activity_summary`.
    - Extend `/api/activities` to also surface Apple-only workouts (those without a Strava `activity_id`). Engineer choice: either UNION at SQL level or two passes + merge in Python. Document the choice in the ADR. The response shape stays as `ActivitySummary[]` — Apple workouts map their fields onto the same shape, with `source: "apple_health"`.

## 8. Frontend tasks

1. **API types** (`frontend/src/api/activities.ts:13`)
   - Add `source: "apple_health" | "strava"` and `external_id: string` to `ActivitySummary` (both nullable to be safe while migration backfills).
2. **History event** (`frontend/src/lib/historyEvents.ts:105` `activityToEvent`)
   - Pass `source` through into the `HistoryEvent` (extend `EventMetric`/`HistoryEvent` shape with `sourceBadge?: "apple" | "strava"`).
3. **Badge in card** (`frontend/src/components/history/HistoryEventCard.tsx`)
   - Render a small pill next to the title: filled green Strava logo / Apple logo. Use existing `lucide-react` style; an `Apple` icon exists.
4. **Badge on activity detail** (`frontend/src/components/activity/ActivityHeader.tsx`)
   - Same pill in the header.
5. **(Optional) `frontend/src/api/appleHealth.ts`** — only if we add manual-trigger endpoints (e.g. a ping button in Settings). Not required for v1.
6. **Tests** — add `Dashboard.test.tsx` / `History.test.tsx` cases verifying badge rendering for both sources.

## 9. Migration tasks

- Revision name: `apple_health_workouts`.
- Parent (current head): `c2f7a4e91b85`. Verify with `alembic heads` before writing.
- New revision file: `alembic/versions/<rev>_apple_health_workouts.py`.

**Upgrade steps** (all SQLite-safe — `op.add_column` over `batch_alter_table` per AGENTS.md):
1. `op.create_table("health_data_points", …)` with columns/indexes from §5.
2. `op.create_table("workouts", …)` with FK `id → health_data_points.id`.
3. `op.create_table("workout_laps", …)` with FK `workout_id → workouts.id` and the `(workout_id, lap_index)` unique.
4. `op.add_column("activities", sa.Column("source", sa.String(32), nullable=True))`.
5. `op.add_column("activities", sa.Column("external_id", sa.String(128), nullable=True))`.
6. `op.add_column("activities", sa.Column("superseded_by_id", sa.Integer(), nullable=True))`.
7. `op.create_index("ix_activities_superseded_by_id", "activities", ["superseded_by_id"])`.
8. **Data backfill** (use `op.execute` with raw SQL, both SQLite + Postgres compatible):
   - `UPDATE activities SET source = 'strava' WHERE source IS NULL`.
   - `UPDATE activities SET external_id = CAST(strava_id AS TEXT) WHERE external_id IS NULL`.

**Downgrade**: reverse in inverse order; drop tables, drop columns. (Plain `op.drop_column` works fine on Postgres; for SQLite, accept the limitation — this is consistent with how other migrations in this repo treat downgrades.)

**Compat note**: do **not** add a CHECK constraint for `source` enum; instead enforce in app code so SQLite downgrades don't break. Indices are plain B-tree; both Postgres and SQLite accept them.

## 10. Tests to add

| File | What it covers |
|---|---|
| `tests/test_services/test_sport_mapping.py` | `normalize_apple`, `normalize_strava`, `same_activity` truth table (Run/TrailRun/VirtualRun match HKRunning; Ride family matches HKCycling; WeightTraining vs HKTraditionalStrengthTraining; mismatched → False). |
| `tests/test_services/test_apple_health_ingest.py` | Pydantic schema validation; upsert (first POST creates, second POST updates, no dup laps); lap parsing from `laps`, from `events`, from neither (falls back to time-based or no laps); idempotency by `external_id`. |
| `tests/test_services/test_workout_dedup.py` | Apple ingest dedups against an existing Strava `Activity` in window → sets `activity.superseded_by_id`; outside the 10-min window → no match; different normalized sport → no match; Strava sync dedups against existing Apple workout → sets `superseded_by_id` immediately. |
| `tests/test_routers/test_apple_health.py` | 401 when header missing or wrong; 200 happy path; 422 invalid payload; replay of same `external_id` returns existing workout id; `/ping` works without writing data. |
| `tests/test_routers/test_activities.py` (extend) | `list_activities` excludes superseded rows by default; `?include_superseded=true` returns them. `_activity_summary` carries `source` + `external_id`. |
| `tests/test_sync/test_strava_sync.py` (extend) | Strava phase A run that creates a new activity matching an existing Apple workout sets `superseded_by_id` on the new row. |
| `frontend/src/components/history/HistoryEventCard.test.tsx` (new) | Renders Apple badge for `source: "apple_health"`, Strava badge for `source: "strava"`, no badge when missing. |

## 11. Parallelism plan

```
phase 1 (parallel):
  - integration-researcher  → answers the six open questions in §6
  - db-migrator             → writes the Alembic revision (§9) + ADR 0002

phase 2 (parallel, depends on phase 1):
  - backend-engineer        → models, sport_mapping, dedup service,
                              ingest service, router, config, sync hook,
                              activities router updates
  - frontend-engineer       → ActivitySummary type, source badge, tests

phase 3 (sequential):
  - test-runner             → pytest + npm run typecheck + npm run build
  - code-reviewer           → review the full diff
  - PR open                 → against main
```

## 12. Risks & rollback

| Risk | Mitigation |
|---|---|
| **Migration on Railway Postgres fails partway** (highest risk). New tables + 3 added columns + 2 UPDATE backfills on possibly many `activities` rows. | Each `op.add_column` is independent and nullable; backfill UPDATEs are idempotent. Rollback: `alembic downgrade -1` to drop the new tables and columns. |
| Plain iOS Shortcuts can't expose `WorkoutEvents` → no lap data. | The schema still works (laps are optional). Document fallback to even time-based splits. Researcher confirms before engineer writes the parser. |
| Dedup false-positives (Strava + Apple disagree on activity type for same workout). | 10-min window AND same normalized sport. Normalizer is conservative (`Run`-family only matches `HKRunning`; `WeightTraining` only matches `HKTraditionalStrengthTraining`/`HKFunctionalStrengthTraining`). Manual override by clearing `superseded_by_id` is a follow-up. |
| Shared-secret token leaks in logs. | Token never appears in URLs; FastAPI logger redacts headers by default. The middleware in `backend/main.py:79` logs only path + method, not headers. Verify in a test. |
| Existing dashboards / insights query `activities` directly and start showing only half the workouts after dedup hides superseded rows. | We do not delete data — `superseded_by_id` is a filter only. Pass `include_superseded=True` from any code path that needs the unfiltered set (notably scheduler enrichment in `backend/scheduler.py`). |
| Apple Health UUID changes when a workout is edited on the watch. | Treat `external_id` as opaque; if a "new" UUID arrives within the dedup window for a workout we already have, we'll create a second `Workout` row and dedup it against itself. Document as a known nuance; revisit if it bites the user. |

**Rollback plan**
1. Revert the PR (Railway redeploys).
2. `alembic downgrade -1` to drop `workout_laps`, `workouts`, `health_data_points` and remove the three activity columns.
3. The dedup state on existing `activities` (`superseded_by_id`) is dropped with the column; original Strava rows remain unchanged.
