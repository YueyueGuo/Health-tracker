# CLAUDE.md

Context file for AI agents working on this repo. Reflects state as of the
workout-data-analysis work stream (April 2026).

## What this project is
A personal health tracker that pulls data from Strava, Eight Sleep, Whoop,
and OpenWeatherMap into a local SQLite DB, classifies workouts, and surfaces
it via a React dashboard + FastAPI backend. Also has Telegram/Discord bots
and an LLM analysis layer (Claude/GPT/Gemini).

Single-user, runs locally by default.

## High-level architecture

- **Backend**: FastAPI + SQLAlchemy (async) + Alembic. Single SQLite DB
  (`health_tracker.db`). WAL mode is on so the sync scheduler can write while
  the API reads.
- **Frontend**: React 19 + Vite + TypeScript + Recharts. Vanilla CSS with
  design tokens in `frontend/src/styles/globals.css` (`--bg`, `--bg-card`,
  `--accent`, etc.). No Tailwind, no UI kit.
- **Scheduler**: APScheduler in `backend/scheduler.py`, runs sync every
  `settings.sync_interval_hours` (default 2).
- **Integration clients**: `backend/clients/{strava,eight_sleep,whoop,weather}.py`.
  All async via httpx.

## Strava data pipeline (what we designed and built)

### Two-phase sync
`backend/services/sync.py::SyncEngine.sync_strava()`:

1. **Phase A** — list activities via `GET /athlete/activities`. Cheap (~1 call
   per 100 activities). Upserts summary rows with `enrichment_status='pending'`.
   Incremental anchor: `after = max(start_date) - 7 days` (7-day buffer so
   late watch uploads aren't missed).
2. **Phase B** — for each `pending` row, fetch `GET /activities/{id}` (detail,
   which embeds `laps`) + `GET /activities/{id}/zones`. Populate all fields,
   insert `ActivityLap` rows, store `zones_data` JSON, mark `complete`. Stops
   cleanly when rate-limited. On a per-activity exception → mark `failed` and
   continue.

Streams are **NOT** fetched by the sync loop. They're lazy via
`GET /api/activities/{id}/streams`, which fetches-and-caches per activity.
That's why the DB stays small.

### Rate limiting
`backend/clients/strava.py`:

- Parses `X-Ratelimit-Usage`/`X-Ratelimit-Limit` on every response.
- Module-level `_quota_state` shared across all client instances.
- `StravaClient.quota_exhausted(fraction=0.95)` returns True at 95% of either
  reported limit. Strava's default is 100/15min + 1000/day for the
  read-only limit, but the authenticated app we use is on 200/15min + 2000/day.
- On 429 → raises `StravaRateLimitError` so the sync loop stops cleanly.

**Known gap**: we don't parse the separate `X-ReadRateLimit-Usage` header.
Strava has a distinct *read* rate limit (100/15min) that can hit before the
overall counter hits 95% of 200. Low priority; the backfill handles it by
sleeping 15min when it gets a 429.

### Schema (see `backend/models/activity.py`)

`activities` columns worth knowing:
- `enrichment_status` ∈ {pending, complete, failed} + `enrichment_error`, `enriched_at`
- `classification_type` ∈ {easy, tempo, intervals, race, recovery, endurance, mixed} (nullable)
- `classification_flags` (JSON) — `is_long`, `has_speed_component`, `has_warmup_cooldown`, `is_hilly`
- `classified_at`
- `device_watts` — True if power came from a meter, False if Strava estimated
- `workout_type` — raw Strava int (1 = race for runs, 11 = race for rides)
- `available_zones`, `zones_data` (JSON)
- `kilojoules`, `weighted_avg_power`, `suffer_score`

`activity_laps` is one row per lap (runs get 5–14, rides get 1, strength gets 1).
Has `start_index`/`end_index` which map into the streams array for later
per-lap zoom-ins.

`activity_streams` is still populated but only lazily.

### Scripts
- `scripts/backfill_strava.py` — full-history resumable backfill. Runs Phase
  A once, then loops Phase B + 15-min sleep cycles until quota exhausted or
  complete. State lives in `enrichment_status` so ctrl-C + re-run is safe.
  `--no-list` skips Phase A; `--batch N` caps per-iteration.
- `scripts/purge_streams.py` — wipes the old eager-stream bloat and VACUUMs.
  Backs up the DB file first. One-shot, already run.
- `scripts/classify_all.py` — bulk classify/reclassify. `--force` overrides
  existing classifications. Useful after threshold tweaks in the classifier.

## Workout classifier (`backend/services/classifier.py`)

Rules-based, interpretable. Not ML. Swap to ML later when labeled data exists.

### Taxonomy

Mutually exclusive types:
- **Runs**: `easy`, `tempo`, `intervals`, `race`
- **Rides**: `recovery`, `endurance`, `tempo`, `mixed`, `race`
- **Other** (strength/yoga/hike/etc.): `None` — classifier returns None

Orthogonal flags (zero or more):
- **Runs**: `is_long` (duration ≥90min or distance ≥16km), `has_speed_component`
  (easy run with any lap at pace_zone ≥4), `has_warmup_cooldown`
- **Rides**: `is_long` (≥2h or ≥50km), `is_hilly` (>15m/km elevation)

### Key rules
- `is_auto_splits` check: if all non-final lap distances are ~1 mile (or ~1km
  for metric users), it's auto-splits, not manual laps. Used to prevent
  misclassifying steady runs as structured.
- Intervals requires `max_pace_zone ≥ 4` AND `not is_auto_splits` AND
  `usable_laps ≥ 3`. Fallback on `speed_cv ≥ 0.15` also requires
  `max_pace_zone ≥ 3` — otherwise walks/stop-and-go jogs (high CV, all zone 1)
  get miscalled as intervals. This fix was tuned against real data; see the
  backfilled classifier distribution.

### Integration
- Called automatically at the end of every Phase B enrichment in
  `sync_strava`. Failures are logged but don't abort enrichment (raw data is
  more valuable than the derived label).
- `POST /api/activities/{id}/classify` reclassifies a single activity.

## Weekly summary (`backend/services/weekly_summary.py` + `routers/summary.py`)

- `GET /api/summary/weekly?weeks=N` → N weeks newest-first.
- `GET /api/summary/week?date=YYYY-MM-DD` → single ISO week.
- Week boundary is ISO (Monday–Sunday).
- Per week: `totals`, `by_sport`, `run_breakdown` by classification, `flags`
  (`has_long_run`, `has_speed_session`, `has_tempo`, `has_long_ride`),
  `notable` (longest/hardest activity IDs), and `enrichment_pending` /
  `classification_pending` so the UI can show a "backfill still running"
  hint.

Rendered on the Dashboard as the "Recent Weeks" strip.

## Eight Sleep pipeline

### Three-host API + OAuth-style auth
`backend/clients/eight_sleep.py` talks to three distinct hosts (the consumer
mobile app does the same):
- `auth-api.8slp.net/v1/tokens` — password + refresh token grants
- `client-api.8slp.net/v1/users/{id}/{trends,intervals}` — sleep data
- `app-api.8slp.net/v2/users/me` — profile (rarely needed; userId usually
  comes straight from the auth response)

First run exchanges `EIGHT_SLEEP_EMAIL` + `EIGHT_SLEEP_PASSWORD` for an
access + refresh token (`grant_type=password`). Subsequent runs use only the
refresh token (`grant_type=refresh_token`). Refresh tokens rotate on every
call and are persisted back to `.env` via a `_persist_env_var()` helper that
rewrites a single `KEY=value` line in place.

**Gotcha #1** — refresh-grant responses don't echo `userId`. Only password
grants do. That means a process that only sees the refresh token has no
idea who the user is. Fix: we also persist `EIGHT_SLEEP_USER_ID` to `.env`.
When both cache and refresh response lack the id, `_get_user_id()` forces
a one-shot password grant to recover it.

**Gotcha #2** — the baked-in `EIGHT_SLEEP_CLIENT_ID` / `CLIENT_SECRET`
defaults in `backend/config.py` are the **public** credentials shipped with
the Eight Sleep consumer mobile app. They're not secrets; they're the only
way to talk to the API. Overridable via env but rarely needed.

### Sync module
`backend/services/eight_sleep_sync.py` is the isolated sync logic.
`SyncEngine.sync_eight_sleep()` is a 5-line delegator. This split exists
so Strava-branch edits to `services/sync.py` don't conflict with Eight
Sleep work. Keep it that way if you need to rework either pipeline.

Data model:
- Trend row (`/trends`) → aggregated per-night metrics (scores, durations,
  `tnt` count, `sleepStart`/`sleepEnd`). Always available, even for 3-year-old
  nights.
- Interval (`/intervals`) → rich per-night data: `stages` array, `timeseries`
  (HR/HRV/resp/tempBedC/tnt), `stageSummary`. Eight Sleep only returns these
  for **roughly the last 2 weeks** — archive nights don't get them.

The sync joins by keying intervals on their **wake date** (evening bedtime
shifts forward one day). Handles the 3-year backfill in 90-day chunks;
stops after 2 consecutive empty windows.

### Column semantics & gotchas
Extended `SleepSession` columns (see `backend/models/sleep.py`):

| Column | Units | Coverage | Notes |
|---|---|---|---|
| `total_duration`, `deep_sleep`, `rem_sleep`, `light_sleep`, `awake_time` | min | all nights | From top-level trend fields (`deepDuration` etc.) |
| `sleep_score` | 0-100 | all nights | = `sleepQualityScore` |
| `sleep_fitness_score` | 0-100 | all nights | = trend `score` (composite); `sleepFitnessScore` is NOT a real API field |
| `tnt_count` | count | all nights | Trend scalar; not a count of `tnt` timeseries |
| `latency` | seconds | all nights | **Pre-sleep only.** Recent nights: first `awake` chunk from the stages array (preferring `stageSummary.awakeBeforeSleepDuration` when provided). Archive nights: falls back to `sleepStart - presenceStart` from the trend row. Never includes mid-night wakes (those roll up into `waso_duration`). |
| `bed_time`, `wake_time` | datetime | all nights | **Naive local wall-clock** (see tz below) |
| `avg_hr`, `hrv`, `respiratory_rate`, `bed_temp` | varies | **recent ~2 weeks only** | From interval `timeseries` |
| `wake_count` | count | recent only | Mid-night awakenings; first awake chunk = latency, NOT counted |
| `waso_duration` | min | recent only | Prefers `stageSummary.wasoDuration` over our own sum |
| `out_of_bed_count`, `out_of_bed_duration` | count / min | recent only | Eight Sleep distinguishes "awake in bed" from "out of bed" |
| `wake_events` | JSON | recent only | `[{type: "awake"\|"out", duration_sec, offset_sec}, ...]` chronological |

**Gotcha #3: timezones.** Eight Sleep returns timestamps with `Z` (UTC).
We store `bed_time`/`wake_time` as **naive local** datetimes using
`interval.timezone` (falls back to `EIGHT_SLEEP_TIMEZONE` from settings).
See `_to_local()` / `_resolve_tz()` in `eight_sleep_sync.py`. Don't strip
the `Z` and store UTC as naive — that's what the first version did and
every bedtime looked 4-5 hours late.

**Gotcha #4: HRV.** Intervals expose both `timeseries.hrv` (Eight's
proprietary index, often 100-500) and `timeseries.rmssd` (standard RMSSD
in ms, 30-80 range). We store RMSSD in the `hrv` column because that's
what every other fitness platform uses. Don't switch without checking.

**Gotcha #5: timeseries shape.** Values are `[[iso_ts, v1], [iso_ts, v2], ...]`
tuples, not raw numbers. `_series_mean()` handles both shapes for
compatibility.

### Migrations
- `c3e7b18f92a4` — adds `sleep_fitness_score`, `tnt_count`, `latency`.
- `d89f2a41e6c3` — adds `wake_count`, `waso_duration`, `out_of_bed_count`,
  `out_of_bed_duration`, `wake_events`.

### Analytics & correlations
- `backend/services/sleep_analytics.py` — pure functions:
  `get_rolling_averages`, `get_sleep_debt`, `get_best_worst_nights`,
  `get_consistency_metrics` (uses **circular statistics** on bed/wake times
  so midnight-crossing bedtimes don't falsely show as inconsistent).
- `backend/services/correlations.py` — Pearson r between 5 sleep metrics ×
  5 activity metrics, joined by `activity.start_date_local.date() == sleep.date`.
  Requires ≥ 8 paired samples; returns `null` for sparse pairs. Filters out
  activities with `moving_time < 600` or missing `average_hr`.

Endpoints:
- `GET /api/sleep/analytics/rolling?days=30`
- `GET /api/sleep/analytics/debt?target_hours=8.0&days=14`
- `GET /api/sleep/analytics/best-worst?days=90&top_n=5`
- `GET /api/sleep/analytics/consistency?days=30`
- `GET /api/correlations/sleep-vs-activity?days=60&sport_type=Run`

### Scripts
- `scripts/backfill_eight_sleep.py` — full-history backfill. `--days N` for
  bounded window, otherwise walks back in 90-day chunks. Idempotent:
  unique `(source, date)` constraint + update-on-diff so ctrl-C + re-run
  is safe. Took ~40 seconds to pull 3 years of history against the live API.
- `scripts/backfill_sleep_latency.py` — one-shot: recomputes `latency`
  from existing `raw_data.interval.stages` using the pre-sleep-only
  logic in `_wake_stats`. Idempotent; skips rows that lack interval
  stages. Already run against the historical data; future nightly syncs
  populate the new shape directly.

### Tests (54 total, all passing)
- `tests/test_clients/test_eight_sleep.py` (10) — auth flow, refresh
  rotation, 401 re-auth, env persistence helper.
- `tests/test_sync/test_eight_sleep_sync.py` (26) — field extraction under
  multiple trend-shape variants, timeseries tuple parsing, night-date
  alignment, tz conversion (DST-sensitive cases), wake-stats derivation,
  pre-sleep latency extraction (+ `stageSummary.awakeBeforeSleepDuration`
  preference, trend-fallback for archive nights).
- `tests/test_sync/test_sleep_analytics.py` (9) — rolling / debt / best-worst
  / consistency, including circular-stats edge cases.
- `tests/test_sync/test_correlations.py` (9) — join logic, sparse-pair
  null return, known-value r=±1 cases, sport_type filter.

### `.env` keys for this pipeline
```
EIGHT_SLEEP_EMAIL=              # required for first run
EIGHT_SLEEP_PASSWORD=           # can be removed after first successful auth
EIGHT_SLEEP_TIMEZONE=America/New_York
EIGHT_SLEEP_REFRESH_TOKEN=      # auto-persisted
EIGHT_SLEEP_USER_ID=            # auto-persisted
EIGHT_SLEEP_CLIENT_ID=          # optional; defaults to public app credentials
EIGHT_SLEEP_CLIENT_SECRET=      # optional; defaults to public app credentials
```
## Elevation / altitude enrichment
Added in PR #1 (merged as `b7e661c`). User lives at sea level; this pipeline
surfaces when a workout happened at altitude so HR/pace shifts on travel
weeks are legible.
### Concept split
- `activities.total_elevation` — elevation **gained** during the workout
  (already existed; from Strava `total_elevation_gain`).
- `activities.base_elevation_m` — **altitude above sea level** where the
  workout happened. New. Canonical value used by the classifier and
  correlations.
### Four-path derivation (`backend/services/elevation_sync.py`)
Precedence for `base_elevation_m`:
1. **Strava `elev_low_m`** — authoritative, watch-recorded. Extracted from
   the detail response in `_apply_detail_to_activity` and also available
   in `raw_data` for every already-enriched activity (hence Phase 1 of
   the backfill needs zero new API calls).
2. **Attached `UserLocation`** via `activities.location_id` — user picked
   a saved place on the activity.
3. **Open-Meteo elevation API** lookup by `start_lat`/`start_lng` — free,
   no key. Used when the watch didn't record altitude but the phone still
   captured coords.
4. **Default `UserLocation`** (`is_default=True`) — auto-applies to
   activities with no coords AND no explicit attachment. Typical indoor
   strength session at home.
`elevation_enriched` mirrors `weather_enriched` as the worklist key. Once
flipped True we don't re-evaluate — even if `base_elevation_m` ended up
NULL (no default location at the time). Attaching a location later calls
`recompute_for_activity` directly.
### User locations
New `user_locations` table + `backend/routers/locations.py`:
- `GET /api/locations` — list saved places
- `GET /api/locations/search?q=...` — proxies Open-Meteo's free geocoding
  (no key). Returns name + lat/lng + elevation in one shot for landmark
  queries, so the common path needs no follow-up elevation call.
- `POST /api/locations` — create. Accepts `{name, lat, lng, elevation_m?}`
  OR `{name, from_activity_id}` (derive coords/elevation from an existing
  Strava activity). Missing elevation resolved via Open-Meteo.
- `PATCH /api/locations/{id}`, `DELETE /api/locations/{id}`,
  `POST /api/locations/{id}/set-default`.
- `POST /api/activities/{id}/location` / `DELETE` — attach/detach
  (triggers `recompute_for_activity`). Mounted under `/api/activities`
  even though it lives in `routers/locations.py`, for REST consistency.
Invariant: at most one row has `is_default=True`. Enforced in code (via
`_clear_other_defaults`) rather than a partial unique index so SQLite
doesn't fight us.
### Classifier tier flags
`backend/services/classifier.py` adds a tiered altitude flag (at most one
per activity, orthogonal to workout type):
- `altitude_low` — ≥ 610 m (~2,000 ft). Tuned conservatively for a
  sea-level athlete.
- `altitude_moderate` — ≥ 1,500 m (~5,000 ft).
- `altitude_high` — ≥ 2,500 m (~8,200 ft).
Wired into both `_run_flags` and `_ride_flags` via `_altitude_flag()`.
Coexists with `is_long`, `is_hilly`, etc.
### Correlations
`base_elevation_m` added to `ACTIVITY_METRICS` in
`backend/services/correlations.py`. Sparse by design (sea-level workouts);
the existing `MIN_PAIRED_SAMPLES=8` gate returns null cells until enough
altitude data exists to compute Pearson r.
### Client (`backend/clients/elevation.py`)
Two Open-Meteo endpoints, both free and no-key:
- `api.open-meteo.com/v1/elevation` — point lookup.
- `geocoding-api.open-meteo.com/v1/search` — name search, returns
  elevation inline.
Mirrors the weather client pattern: self-throttled at ~4 req/sec,
module-level `_quota_state`, 429 → typed `ElevationRateLimitError`.
`is_configured=True` always.
### Backfill (`scripts/backfill_elevation.py`)
Two phases, resumable via `elevation_enriched`:
1. **Phase 1 — Strava promotion.** Re-reads `Activity.raw_data` and
   populates `elev_high_m`/`elev_low_m`/`base_elevation_m` from the
   cached Strava detail blob. **Zero API calls.** Runs in seconds.
   Covered 1,512 / 1,754 activities on the initial run.
   - **Pagination gotcha**: the query filters on
     `elevation_enriched == False` and flips that flag as we go, so using
     OFFSET would skip unprocessed rows. The script re-queries the first
     `page_size` rows each iteration instead. If a full page passes
     without progress, we stop to avoid looping forever on indoor rows.
2. **Phase 2 — Open-Meteo fallback.** Coords-only gaps + default-location
   application. `--phase1-only`, `--dry-run`, `--batch`, `--max-calls`
   flags mirror `backfill_weather.py` for consistency.
### Frontend
- `frontend/src/components/ActivityDetail.tsx` — new Base Altitude metric
  card gated at `base_elevation_m >= 610` with tier subtext. Kept
  separate from the existing "Elevation Gain" card.
- `frontend/src/components/LocationPicker.tsx` — shown on activity detail
  when `start_lat`/`start_lng` are null. Three entry paths, **no raw
  coords required**: pick-saved / search-by-name / use-current-location
  (`navigator.geolocation`).
- `frontend/src/pages/Settings.tsx` (route `/settings`) — list + add (all
  three paths above + an advanced raw-coords form) + rename + delete +
  set-default. Tier thresholds mirrored in a small constant at the top of
  `ActivityDetail.tsx`; keep in sync with classifier constants if they
  ever change.
- `ClassificationBadge` humanizes `altitude_low` / `altitude_moderate` /
  `altitude_high`.
### Tests (29 new, all passing)
- `tests/test_clients/test_elevation.py` (9) — elevation happy path, 429,
  missing-key null, geocoding search + malformed-record skipping.
- `tests/test_sync/test_elevation_sync.py` (13) — each of the four
  derivation paths, default-location fallback, enrichment idempotency,
  rate-limit mid-loop, `recompute_for_activity`, `extract_elev_from_raw`.
- `tests/test_sync/test_classifier_altitude.py` (7) — tier boundaries,
  flag coexistence with `is_long` / `is_hilly`, ride vs run.
### Migration
- `a7e2c5f8b1d3` — adds `elev_high_m`, `elev_low_m`, `base_elevation_m`,
  `elevation_enriched`, `location_id` to `activities`; creates
  `user_locations`.
### Phase 1 backfill state (as of merge)
- **1,512 / 1,754 activities enriched** via Phase 1 (cached `raw_data`).
- **242 still pending** `elevation_enriched=False`:
  - 62 `complete` indoor rows with no GPS (waiting on a default location
    to be set, then Phase 2 to pick them up).
  - 180 `pending` Strava rows (will be handled on the next Strava
    enrichment pass).
- Reclassify pass ran on 756 activities; altitude flags applied where
  relevant. Top elevation in the DB: 4,680 m (Kilimanjaro summit, July
  2025).
- **Phase 2 was intentionally skipped** — without a default `UserLocation`
  it would flip the 62 indoor rows to `enriched=True` with `base=NULL`,
  preventing a future default from retroactively applying. When the user
  sets a home default via `/settings`, re-run `backfill_elevation.py`.
## Frontend layout
- Routes wired in `frontend/src/App.tsx`: `/`, `/activities`, `/activities/:id`,
  `/sleep`, `/recovery`, `/training`, `/ask`, `/settings`,
  `/strength`, `/strength/new`.
- Dashboard includes `WeeklySummaryCards` (4-week strip).
- ActivityList has a Classification column + filter, Pace/HR + Relative
  Effort columns.
- ActivityDetail has:
  - Classification badge + Reclassify button at top
  - Metric cards (distance, duration, pace, power, elevation gain, work/kJ,
    relative effort, **base altitude** — gated ≥ 610 m)
  - **LocationPicker** shown when the activity has no GPS coords (search /
    current location / pick-saved)
  - Laps table with pace-zone row tinting
  - Time-in-zone bar charts (HR / pace / power — whichever are available)
  - "Load Streams" button (lazy) → uses `/api/activities/{id}/streams`
- `ClassificationBadge` component is reusable; map of types to colors lives
  in globals.css.
- `Sleep.tsx` (route `/sleep`) renders sleep-score line chart, stacked-stages
  bar chart, a recent-nights table with per-night wake-event timeline, and a
  30/60/90-day range selector. All data comes from `frontend/src/api/sleep.ts`
  typed fetchers hitting `/api/sleep` + `/api/sleep/analytics/*`. Uses
  Recharts consistent with the rest of the frontend.

## Alembic
Linear chain: `initial → laps_zones_enrichment (a1c4f9d2e8b0) → eight_sleep_extra_fields (c3e7b18f92a4) → classification (b2d5e0f3c1a7) → sleep_wake_events (d89f2a41e6c3) → strength_sets (e4a9b1c3d5f7) → whoop_workouts (f5a1c7b2d4e9) → elevation_and_user_locations (a7e2c5f8b1d3)`.

New migrations that add nullable columns should use plain `op.add_column`
(not `batch_alter_table`) — SQLite does ADD COLUMN as metadata-only, which is
safe to run while the backfill scheduler is writing.

## Working conventions

- Single-user local app. `.env` in repo root; never committed.
- `health_tracker.db`, `*.db-shm`, `*.db-wal`, `*.bak` all in `.gitignore`.
- Backend: Python 3.11+. `pyproject.toml` is authoritative for deps.
- Frontend: React 19. `npm run typecheck` and `npm run build` should be clean
  before committing frontend changes.
- Commit messages include `Co-Authored-By: Oz <oz-agent@warp.dev>` per Warp
  convention.
- When working in parallel with another agent, each agent should be on its
  **own branch**. We hit a merge conflict once because two agents pushed to
  the same branch.

## Open work / things to pick up

- **Elevation — Phase 2 follow-up.** Backfill Phase 2 was skipped
  intentionally. Once a default `UserLocation` is set via `/settings`,
  re-run `python scripts/backfill_elevation.py` to resolve the 62 indoor
  activities and 180 pending-Strava rows.
- **Phone-location PWA.** The `user_locations` + `location_id` schema is
  the foundation. Add `navigator.geolocation` → `POST /api/location/ping`
  → `location_pings` table → nightly timestamp-join to activities missing
  coords. See the elevation plan doc in Warp Drive for the sketch.
- **`/api/correlations/altitude-vs-effort`** — dedicated endpoint pairing
  `base_elevation_m` against HR / suffer_score / pace for same-sport
  activities. Low priority; the existing sleep-vs-activity matrix now
  includes `base_elevation_m` so the signal already surfaces there.
- **Classifier tuning** — Current distribution looks sensible after the
  `max_pace_zone ≥ 3` gate. Most activities now enriched (1,512 / 1,754
  after elevation work). Revisit if specific sport mixes look off.
- **Read rate limit header** — StravaClient doesn't parse
  `X-ReadRateLimit-Usage` separately. Cheap fix if we want to stop *before*
   429'ing instead of after.
- **`/api/summary/weekly` filter** — UI doesn't yet filter activity list by
  clicking into a weekly summary card. Obvious follow-up.
- **Strava-side tests** — Classifier, weekly summary, Strava sync rewrite
  still under-tested. Elevation work added 29 tests (29 passing); Eight
  Sleep work added 50. Strava side still catching up.

## Ambient state you should know about
- `scripts/backfill_strava.py` was kicked off as a background process and
  may still be running (PID was 79610 at start; check `pgrep -f
  backfill_strava.py`). It's resumable, so killing it is safe.
- Enrichment progress last checked: ~415 / 1754 complete. Note: the
  elevation backfill ran against whatever subset was enriched at that
  time; re-running `backfill_elevation.py --phase1-only` is safe and
  picks up newly-enriched rows.
- The ~230MB streams bloat has already been purged from the DB.
- **Elevation backfill state:** 1,512 / 1,754 `elevation_enriched=True`;
  62 indoor + 180 pending-Strava still `False`. Phase 2 deferred until a
  default `UserLocation` is set (see the elevation section above).
- User cleared with multi-day backfill being fine.

## Dashboard insights (LLM-powered)

Three endpoints, all under `/api/insights/*`:
- `GET /training-metrics` — raw snapshot (ACWR, monotony, strain, sleep
  debt, recovery trend, latest workout) for debugging.
- `GET /daily-recommendation?refresh=bool&model=str` — structured LLM
  output with intensity pill, suggestion, rationale, concerns,
  confidence. Cached per-day (24h TTL) keyed on inputs hash.
- `GET /latest-workout?activity_id=int&refresh=bool&model=str` —
  per-activity insight (headline, takeaway, notable segments,
  vs_history, flags). Cached per-activity_id (no TTL).

Key files:
- `backend/services/training_metrics.py` — deterministic snapshot
  builders (no LLM). `_get_latest_completed_activity(activity_id=X)`
  requires `enrichment_status == "complete"` even when an ID is passed
  explicitly — never feed a pending row (no laps, no weighted power) to
  the LLM.
- `backend/services/insights.py` — Pydantic schemas
  (`DailyRecommendation`, `WorkoutInsight`), cache helpers,
  `_call_llm_structured()` with fallback chain + self-correcting retry,
  `_maybe_unwrap()` to handle models that wrap responses in a single
  top-level key.
- `backend/services/llm_providers.py` — added `query_structured()` on
  each provider: Anthropic (tool-use), OpenAI (`json_schema` strict →
  `json_object` fallback, narrowed to `openai.BadRequestError`), Gemini
  (inlined schema + `response_schema` hint). `_pydantic_schema()` in
  `insights.py` inlines `$defs`/`$ref` recursively (providers especially
  Gemini don't follow refs) AND forces every `object` subschema to set
  `additionalProperties: false` + list all properties in `required`.
  Without that, OpenAI strict `json_schema` mode rejects the payload on
  fields like `concerns`/`notable_segments`/`flags` that Pydantic marks
  optional via `default_factory`, silently wasting a round-trip before
  the `json_object` fallback.

Config (`backend/config.py` → `LLMSettings`):
- `dashboard_model` (default `claude-haiku`).
- `dashboard_fallback_models` (default `["claude-sonnet", "gpt-4o-mini"]`).
  Accepts comma-separated env var.

### Enrichment drain scheduler job

`_run_strava_enrichment_drain()` in `backend/scheduler.py` runs every
20 minutes. No-ops when no activities have `enrichment_status="pending"`
and skips when `StravaClient.daily_quota_exhausted()` is True. Calls
`SyncEngine._strava_phase_b(limit=batch)` directly — does NOT re-list.
Wired into the uvicorn lifespan (`backend/main.py`) alongside the
existing `sync_all` job.

**Only the Strava client is constructed** (EightSleep/Whoop/Weather
are passed as `None` to `SyncEngine`). Phase B doesn't touch them, and
instantiating them every 20 min triggered needless Eight Sleep token
refreshes. Errors inside the drain are logged with `logger.exception`
so stack traces land in the log.

### Tests (33 total, all passing)
- `tests/test_services/test_training_metrics.py` (17) — training-load
  snapshot shape and math (ACWR, monotony, strain, days-since-hard,
  latest-workout snapshot, sleep/recovery snapshot).
- `tests/test_services/test_insights.py` (11) — LLM layer with all
  providers mocked: happy path, cache hit/miss, refresh, fallback chain,
  all-fail-raises, validation-error retry, schema tightening walk
  (every object has `additionalProperties: false` + all keys required),
  pending-id gate (never runs LLM against a non-complete row).
- `tests/test_services/test_scheduler_jobs.py` (5) — drain guards:
  no-op when pending=0, skip when daily quota hit, phase-B runs when
  quota ok.

**Total repo test count: 148 passing** (Eight Sleep 54 + elevation 29
+ dashboard/scheduler 33 + other suites).

## Quick commands cheatsheet

```bash
# Check backfill progress
sqlite3 health_tracker.db "SELECT enrichment_status, COUNT(*) FROM activities GROUP BY enrichment_status"

# Classification distribution
sqlite3 health_tracker.db "SELECT classification_type, COUNT(*) FROM activities WHERE enrichment_status='complete' GROUP BY classification_type ORDER BY 2 DESC"

# Sync quota snapshot
curl http://localhost:8000/api/sync/status | jq '.strava_quota, .strava_enrichment'

# Reclassify everything after a threshold change
python scripts/classify_all.py --force
# Resume backfill in background
nohup .venv/bin/python -u scripts/backfill_strava.py --no-list > backfill.log 2>&1 & disown
# Elevation backfill — Phase 1 only (no API calls, ~few seconds)
python scripts/backfill_elevation.py --phase1-only
# Elevation backfill — full (Phase 1 + Open-Meteo fallback + default location)
python scripts/backfill_elevation.py
# Elevation distribution sanity-check
sqlite3 health_tracker.db "SELECT COUNT(*), ROUND(AVG(base_elevation_m),1), ROUND(MAX(base_elevation_m),1), COUNT(CASE WHEN base_elevation_m >= 610 THEN 1 END) FROM activities WHERE base_elevation_m IS NOT NULL"
```
