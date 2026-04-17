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
| `latency` | seconds | all nights | `sleepStart - presenceStart`, computed from UTC |
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

### Tests (50 total, all passing)
- `tests/test_clients/test_eight_sleep.py` (10) — auth flow, refresh
  rotation, 401 re-auth, env persistence helper.
- `tests/test_sync/test_eight_sleep_sync.py` (22) — field extraction under
  multiple trend-shape variants, timeseries tuple parsing, night-date
  alignment, tz conversion (DST-sensitive cases), wake-stats derivation.
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

## Frontend layout
- Routes wired in `frontend/src/App.tsx`: `/`, `/activities`, `/activities/:id`,
  `/sleep`, `/recovery`, `/training`, `/ask`.
- Dashboard includes `WeeklySummaryCards` (4-week strip).
- ActivityList has a Classification column + filter, Pace/HR + Relative
  Effort columns.
- ActivityDetail has:
  - Classification badge + Reclassify button at top
  - Metric cards (distance, duration, pace, power, elevation, work/kJ,
    relative effort)
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
Linear chain: `initial → laps_zones_enrichment (a1c4f9d2e8b0) → eight_sleep_extra_fields (c3e7b18f92a4) → classification (b2d5e0f3c1a7) → sleep_wake_events (d89f2a41e6c3)`.

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

- **Strand: strength session manual entry UI** — User wants to manually log
  sets/reps/weight for strength sessions (Strava has no concept of them).
  Scope discussed: new `strength_sets` table (exercise, reps, weight, rpe,
  timestamp, FK to activities), a simple form UI, progression chart later.
  Not started.
- **Strand: Whoop modernization** — User just set up a Whoop device. Scope:
  port `backend/clients/whoop.py` to the Strava client pattern (async,
  rate-limit parsing, typed exceptions). If kicking off a parallel agent,
  branch off `main` and avoid touching `sync_strava`, activities/summary
  routers, or frontend.
- **Classifier tuning** — Current distribution looks sensible after the
  `max_pace_zone ≥ 3` gate, but only ~415 of 1754 activities are enriched.
  Revisit once backfill completes.
- **Read rate limit header** — StravaClient doesn't parse
  `X-ReadRateLimit-Usage` separately. Cheap fix if we want to stop *before*
   429'ing instead of after.
- **`/api/summary/weekly` filter** — UI doesn't yet filter activity list by
  clicking into a weekly summary card. Obvious follow-up.
- **Tests** — Almost none for the new classifier / weekly summary / Strava
  sync rewrite. The Eight Sleep work added 50 unit tests across clients,
  sync, analytics, and correlations; the Strava side didn't.

## Ambient state you should know about

- `scripts/backfill_strava.py` was kicked off as a background process and
  may still be running (PID was 79610 at start; check `pgrep -f
  backfill_strava.py`). It's resumable, so killing it is safe.
- Enrichment progress last checked: ~415 / 1754 complete.
- The ~230MB streams bloat has already been purged from the DB.
- User cleared with multi-day backfill being fine.

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
```
