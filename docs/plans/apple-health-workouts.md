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

## 6. External integration

### Auth & transport (locked)
- Method: shared-secret token via `X-Apple-Health-Token` header.
- Storage: env var `APPLE_HEALTH_INGEST_TOKEN`, surfaced through `backend/config.py` as `AppleHealthSettings`.
- Compare in constant time (`hmac.compare_digest`).
- 401 on missing/wrong; 403 if header present but token blank in env (misconfig signal).

### Sync model (locked)
- Push from iOS Shortcut. Single-user. No polling.
- Idempotent: `(source='apple_health', data_type='workout', external_id=HK UUID)` is the natural key. Replay = upsert (update mutable fields, do **not** create duplicate laps — replace lap rows wholesale, mirroring Strava enrichment in `backend/services/sync.py:247-253`).

### Expected payload shape (the Shortcut must produce this)
The Shortcut **must** flatten what the iOS "Health" actions expose to JSON. Documented contract:

```json
{
  "workout": {
    "uuid": "B6D2…",
    "activity_type": "HKWorkoutActivityTypeRunning",
    "start": "2026-05-24T13:14:00-04:00",
    "end":   "2026-05-24T14:02:35-04:00",
    "duration_s": 2915,
    "active_energy_kcal": 412.3,
    "distance_m": 8043.6,
    "avg_hr": 154,
    "max_hr": 178,
    "total_elevation_m": 64.0,
    "source_name": "Apple Watch",
    "device": "Apple Watch Series 9"
  },
  "events": [
    { "type": "lap", "start": "...", "end": "..." },
    { "type": "segment", "start": "...", "end": "..." }
  ],
  "laps": [
    {
      "index": 1,
      "start": "2026-05-24T13:14:00-04:00",
      "duration_s": 360,
      "distance_m": 1000,
      "avg_hr": 152,
      "max_hr": 168,
      "avg_speed_mps": 2.78
    }
  ]
}
```

The ingest service must accept payloads with **either** a `laps` array (preferred) **or** an `events` array (it then derives even time-based splits per km/mi). If neither is present, the workout is stored without laps.

### Open questions for `integration-researcher`
The user explicitly chose plain iOS Shortcuts (not Health Auto Export). The plan must be validated on these points before the backend agent writes the parser:

1. **Does plain iOS Shortcuts expose per-lap data?** The "Find Workouts" / "Get Workout" actions are known to expose duration, energy, distance, HR. Confirm whether they also expose `WorkoutEvents` (lap/segment markers) or `WorkoutRoute` segments. If **not**, the contract above must drop the `events`/`laps` arrays and the engineer falls back to time-based splits derived server-side from total duration + distance.
2. **What is the canonical field name** the Shortcut output uses for the HKWorkout UUID? (Shortcuts sometimes surface it as `Identifier` rather than `UUID`.) The ingest service's parser key must match.
3. **HR / HR-series**: can Shortcuts pull average + max HR for a workout in one action, or does it require a separate "Find Health Samples" with predicate `Workout = …`? This determines whether the user's Shortcut needs one stage or two.
4. **Timezone**: do the timestamps come through as ISO8601 with offset, or as device-local naive strings? We store UTC-naive in `activities.start_date` (`backend/services/time_utils.py`). The parser must normalize consistently.
5. **HKWorkoutActivityType list**: confirm the canonical Apple enum strings (e.g. `HKWorkoutActivityTypeRunning` vs `Running`) Shortcuts emits, so `sport_mapping.py` keys are correct.
6. **Health Auto Export comparison**: even though we picked plain Shortcuts, document what HAE would have given us for laps/route — if plain Shortcuts can't do laps, this is the fallback to recommend to the user.

Researcher should produce a brief covering §1-§7 of `.claude/agents/integration-researcher.md` and answer the six questions above with citations.

### Rate limits / error model
- No external rate limit (we own the endpoint).
- 200 on success; 401 bad token; 422 schema; 409 if `external_id` exists but payload conflict (return existing id, idempotent).
- No retries server-side; Shortcuts auto-retries on network failure if the user configures it.

## 7. Backend tasks

Ordered, each small enough for one agent run:

1. **Config**
   - Add `AppleHealthSettings` to `backend/config.py`: `ingest_token: str = ""` with prefix `APPLE_HEALTH_`.
   - Wire into `Settings` like the other sub-settings (`backend/config.py:131-135`).
2. **Sport mapping module** (`backend/services/sport_mapping.py`)
   - `APPLE_TO_NORMALIZED: dict[str, str]` (e.g. `HKWorkoutActivityTypeRunning → "run"`).
   - `STRAVA_TO_NORMALIZED: dict[str, str]` (covers Strava `sport_type` values seen in code today, e.g. `Run`, `TrailRun`, `Ride`, `WeightTraining` etc.).
   - `normalize_apple(t: str) -> str | None`, `normalize_strava(t: str) -> str | None`.
   - `same_activity(apple_type: str, strava_type: str) -> bool`.
3. **Models**
   - Create `backend/models/health_data_point.py` (`HealthDataPoint`).
   - Create `backend/models/workout.py` (`Workout`, `WorkoutLap`), joined-table style with `HealthDataPoint`.
   - Add `source`, `external_id`, `superseded_by_id` columns to `Activity` in `backend/models/activity.py`.
   - Export from `backend/models/__init__.py`.
4. **Dedup service** (`backend/services/workout_dedup.py`)
   - `match_apple_against_strava(db, workout) -> Activity | None` — query `activities` where `start_date` in `[workout.start_time − 10m, workout.start_time + 10m]` AND normalized sport matches; if found, set `activity.superseded_by_id = workout.id`.
   - `match_strava_against_apple(db, activity) -> Workout | None` — symmetric; if found, set `activity.superseded_by_id = workout.id` (and optionally `workout.activity_id = activity.id` for the back-pointer).
   - Pure functions: take `db`, take the row, persist via passed session, no commit (caller commits).
5. **Ingest service** (`backend/services/apple_health_ingest.py`)
   - `ingest_workout(db, payload) -> dict`: validate (Pydantic model), upsert `HealthDataPoint` + `Workout`, parse laps from `payload.laps`, else derive from `payload.events`, else from total duration. Replace laps wholesale on re-post.
   - Calls `workout_dedup.match_apple_against_strava` after upsert.
   - Returns `{"workout_id": …, "external_id": …, "dedup_matched_activity_id": …|None, "lap_count": …}`.
6. **Auth dependency** (`backend/routers/apple_health.py`)
   - `verify_apple_health_token(x_apple_health_token: str | None = Header(None))` FastAPI dependency using `hmac.compare_digest`.
7. **Router** (`backend/routers/apple_health.py`)
   - `POST /workouts` → calls ingest service.
   - `POST /ping` (optional) — returns `{"ok": true}` for the user to test their Shortcut without writing data.
8. **Wire router** in `backend/main.py:117-155` block: `app.include_router(apple_health.router, prefix="/api/ingest/apple-health", tags=["apple-health"])`.
9. **Strava sync hook** — in `backend/services/sync.py::_strava_phase_a`, after each new `Activity` is added (around line 187), call `workout_dedup.match_strava_against_apple(self.db, activity)`. Wrap in `try/except` so a dedup failure never breaks Strava sync.
10. **Activity router updates** — `backend/routers/activities.py:38`:
    - Add `include_superseded: bool = Query(False)` to `list_activities`; when `False`, filter `Activity.superseded_by_id.is_(None)`.
    - Add `source` and `external_id` to `_activity_summary` (line 286).
    - Add a parallel `/api/workouts` (or extend `/api/activities`) endpoint that returns the union of Strava `Activity` rows and Apple Health `Workout` rows in one shape, both annotated with `source`. (Engineer choice — recommended: extend `/api/activities` so the existing UI keeps working unchanged. Document the choice in the ADR.)

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
