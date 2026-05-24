# Health & Fitness Tracker — Architecture Audit (audit-001-initial)

*Read-only architecture audit conducted by the `architecture-auditor` agent. No
code changes. Findings are cited with file:line references throughout.*

---

## 1. Architecture overview

### High-level structure

```
[Browser PWA] ──HTTPS──► [Railway service: one container]
                          ├── FastAPI (uvicorn) /api/*
                          ├── Static React build from /frontend/dist (served by FastAPI)
                          └── APScheduler (in-process, async) — periodic sync_all + Strava enrichment drain
                                  │
                                  ▼
                          [Railway Postgres] (or local SQLite for dev)
                                  ▲
                                  │
[Strava] [Eight Sleep] [Whoop] [OpenWeatherMap | Open-Meteo]
       (httpx async pull, OAuth/refresh; weather optional/no-key default)
```

Single-container deploy. Frontend and backend share an origin (`/api/*` for
API; `/*` serves `index.html` + `/assets`). See `backend/main.py:170-182` and
`Dockerfile:18,27`. Health check: `GET /api/health` (`railway.toml:6`).

### Top-level folders

| Folder | Purpose / contents |
|---|---|
| `backend/` | FastAPI app: `main.py` (lifespan + routers + SPA serving), `config.py` (pydantic-settings), `database.py` (async engine, `init_db`, `_ensure_compat_schema`), `scheduler.py` (APScheduler jobs), `clients/` (Strava/Whoop/Eight Sleep/Weather/Elevation/Open-Meteo HTTP clients), `models/` (SQLAlchemy 2 ORM, 14 modules), `routers/` (16 routers), `services/` (sync engines + classifier + analytics + insights + LLM providers + snapshot builders) |
| `frontend/` | Vite + React 19 + TS. `src/App.tsx` (lazy routes), `src/api/*` (typed fetch wrappers around shared `http.ts`), `src/components/`, `src/pages/` (Record, History, Profile, Settings), `src/lib/queryCache.ts` (TanStack Query). All API calls use `/api` relative paths (`frontend/src/api/http.ts:1`) so CORS is not exercised when same-origin. |
| `tests/` | pytest, async. `test_clients/`, `test_routers/`, `test_services/`, `test_sync/`, `test_database.py`. No `test_api/` content (empty `__init__.py` only). Uses in-memory SQLite throughout. |
| `alembic/` | 15 migrations forming a DAG (one merge revision at `c2f7a4e91b85`); head is `f9c2e1a45b80` (`_oauth_tokens`). `env.py` reads `sqlalchemy.url` from the ini file, not the environment. |
| `scripts/` | Standalone Python utilities (`setup_db.py`, `initial_sync.py`, `backfill_strava.py`, etc.). Not invoked by Railway. |
| `deploy/` | **Mac-mini-only** launchd plist template + `install.sh`/`update.sh`. References `~/Library/LaunchAgents`, `launchctl`, Tailscale. Not used by Railway. |
| `docs/` | Has `archive/` only. No `decisions/` (CLAUDE.md asks for one). |
| `.github/workflows/ci.yml` | Ruff + pytest + frontend typecheck + frontend build. No deployment job, no Alembic. |
| Root files | `Dockerfile` (multi-stage Node→Python; CMD = uvicorn only), `railway.toml` (healthcheck only), `alembic.ini` (SQLite URL hardcoded), `pyproject.toml`, `.env.example` (has a duplicated `TAILSCALE_HOSTNAME=` line — see `.env.example:59` and `:63`). |

### Where each integration lives

| Integration | Client | Sync logic | OAuth callback | Tokens stored at |
|---|---|---|---|---|
| Strava | `backend/clients/strava.py` | `backend/services/sync.py:_strava_phase_a/_strava_phase_b` (two-phase) | `backend/routers/auth.py:50-67` `/api/auth/strava/callback` | `oauth_tokens` table + `.env` (best-effort) |
| Eight Sleep | `backend/clients/eight_sleep.py` | `backend/services/eight_sleep_sync.py` | None — username/password grant or persisted refresh token | `.env` only (`_persist_env_var`), NOT in `oauth_tokens` |
| Whoop | `backend/clients/whoop.py` | `backend/services/whoop_sync.py` | `backend/routers/auth.py:86-196` `/api/auth/whoop/callback` | `oauth_tokens` table + `.env` (best-effort) |
| OpenWeatherMap | `backend/clients/weather.py` | `backend/services/sync.py:sync_weather` | n/a (API key only) | `OPENWEATHERMAP_API_KEY` env var |
| Open-Meteo (default) | `backend/clients/openmeteo.py` | same `sync_weather` (chosen via `backend/clients/__init__.py:get_weather_client`) | n/a | n/a |

### Manual weight training entry path

- **Frontend form**: `frontend/src/pages/Record.tsx` (route `/record`,
  registered in `frontend/src/App.tsx:34`). Builds `StrengthSetInput[]` and
  calls `createStrengthSession({ date, activity_id, sets })` in
  `frontend/src/pages/Record.tsx:449`. The fetch helper is
  `createStrengthSession` in `frontend/src/api/strength.ts:95-102`, which
  POSTs `/api/strength/sets`.
- **Backend endpoint**: `POST /api/strength/sets` in
  `backend/routers/strength.py:97-129` (router mounted at `/api/strength`
  in `backend/main.py:144`). Validation by Pydantic
  `StrengthSessionCreate` (`backend/routers/strength.py:49-54`) —
  accepts `date: date`, `activity_id: int | None`,
  `sets: list[StrengthSetInput]` (each `exercise_name`,
  `set_number ≥ 1`, `reps ≥ 1`, `weight_kg ≥ 0 | None`,
  `rpe 0-10 | None`, `notes`, `performed_at: datetime | None`).
- **Database**: `strength_sets` table, model in
  `backend/models/strength.py:20-57`. FK `activity_id → activities.id
  ON DELETE SET NULL`. Column `performed_at: DateTime nullable` was
  added later — migration `b3c6d9e8a1f4_strength_set_performed_at.py`.
  `database.py:_ensure_compat_schema` retroactively adds the column at
  startup if missing (SQLite + Postgres branches;
  `backend/database.py:75-111`).
- **Frontend success behavior**: clears localStorage draft and calls
  `invalidateAppDataQueries(queryClient)`
  (`frontend/src/pages/Record.tsx:450-451`), then `navigate("/history")`.
  `invalidateAppDataQueries` invalidates
  `["activities"], ["sleep"], ["recovery"], ["dashboard"], ["insights"],
  ["strength"], ["sync"]` (`frontend/src/lib/queryCache.ts:20-28`).

### Database schema (key tables)

| Table | Purpose | Notable columns |
|---|---|---|
| `activities` (`backend/models/activity.py:27-105`) | Strava activities (one row per activity) | `strava_id BIGINT UNIQUE`, `enrichment_status` (pending/complete/failed), `weather_enriched`, `elevation_enriched`, `classification_*`, `rpe`, `raw_data JSON`, FK `location_id → user_locations` |
| `activity_laps` (`backend/models/activity.py:122-149`) | Embedded laps after enrichment | `(activity_id, lap_index)` unique, `hr_zone` |
| `activity_streams` (`backend/models/activity.py:108-119`) | Lazy-fetched HR/pace/power streams | `(activity_id, stream_type)` unique, `data JSON` |
| `sleep_sessions` (`backend/models/sleep.py`) | Eight Sleep + Whoop (single table, `source` discriminator) | `(source, date)` unique; bed/wake naive-local; stage durations in minutes; Whoop-specific extras nullable |
| `recovery_records` (`backend/models/recovery.py`) | Whoop daily recovery | unique per date |
| `whoop_workouts` (`backend/models/whoop_workout.py`) | Whoop activity table (separate from Strava) | `whoop_id` STRING unique (migrated from int) |
| `strength_sets` | Manual lifting entries | Implicit "session" = group by `date`; `performed_at` naive-local optional |
| `weather_snapshots` (`backend/models/weather.py`) | One row per activity (one-to-one) | FK activity_id |
| `user_locations`, `user_profile`, `goal`, `recommendation_feedback` | Profile/preferences/goals/RPE feedback | |
| `oauth_tokens` (`backend/models/oauth_token.py`) | Strava + Whoop token persistence (Eight Sleep NOT here) | `provider` PK |
| `sync_log` (`backend/models/sync_log.py`) | Per-sync audit row (one per call) | `source`, `started_at`, `completed_at`, `status`, `records_synced`, `error_message` |
| `analysis_cache` | LLM result cache | |

All `JSON` columns are declared with `sqlalchemy.dialects.sqlite.JSON`
(e.g. `backend/models/activity.py:18`, `backend/models/sleep.py:6`,
`backend/models/weather.py:6`, `backend/models/whoop_workout.py:15`,
`backend/models/user_profile.py:8`, `backend/models/recovery.py:6`). On
Postgres this resolves to plain TEXT, not JSONB. Functional, but you
lose JSON operators/indexes and silently round-trip strings.

---

## 2. Data flow

### Strava

- **Auth**: OAuth2 authorization code. Bootstrap: visit
  `/api/auth/strava` (`backend/routers/auth.py:40-47`); callback
  exchanges code at `/api/auth/strava/callback` (`:50-67`). Refresh:
  `StravaClient._ensure_token` (`backend/clients/strava.py:282-308`)
  with an `asyncio.Lock` to serialise concurrent refreshes (Strava
  refresh tokens are single-use).
- **Token storage**: source of truth is `oauth_tokens` table
  (`backend/services/oauth_tokens.py`). On construct,
  `StravaClient.__init__` (`backend/clients/strava.py:75-83`) seeds
  memory with
  `_read_env_var(self._env_path, "STRAVA_ACCESS_TOKEN") or settings.strava.access_token`
  (same pattern for refresh token). `_load_tokens_if_needed`
  (`:233-257`) hydrates from DB on first awaited call. After refresh,
  `_persist_tokens` (`:259-280`) writes to DB **and** best-effort to
  repo-root `.env` (which does not exist on Railway, so persist
  silently no-ops via `eight_sleep._persist_env_var`,
  `backend/clients/eight_sleep.py:335-356`).
- **Fetch**: pull-mode HTTPS via `httpx.AsyncClient`. No webhooks.
- **Schedule**: APScheduler interval job `sync_all` every
  `SYNC_INTERVAL_HOURS` hours (default 2), plus an enrichment drain
  every 20 min (`backend/scheduler.py:96-116`). On lifespan startup,
  `sync_on_startup=True` by default (`backend/config.py:115`) fires a
  one-shot `_run_sync("all")` in the background
  (`backend/main.py:32-42`). README recommends setting
  `SYNC_ON_STARTUP=false` on Railway (`README.md:99-101`) — but if not
  set, default is `True`.
- **DB write path**: `SyncEngine._strava_phase_a` upserts summary rows
  with `enrichment_status="pending"`
  (`backend/services/sync.py:120-191`); `_strava_phase_b` (`:205-276`)
  fetches detail + zones + laps, deletes/re-inserts `activity_laps`,
  calls classifier, sets `enrichment_status="complete"`.
- **Frontend read**: `frontend/src/api/activities.ts` →
  `GET /api/activities`, `/api/activities/{id}` (router
  `backend/routers/activities.py`). Dashboard tile pulls aggregates via
  `/api/dashboard/overview` and `/api/dashboard/today`
  (`backend/routers/dashboard.py:75-89, 173-248`). All client-side
  caching via TanStack Query with a `12h` stale time
  (`frontend/src/lib/queryCache.ts:4`).

### Eight Sleep

- **Auth**: username/password "consumer-app" grant against
  `https://auth-api.8slp.net/v1/tokens`
  (`backend/clients/eight_sleep.py:89-109`). Refresh-token grant on
  subsequent calls (`:111-132`). Client id/secret default to public
  consumer-app values (`backend/config.py:25-28`).
- **Token storage**: `.env` only. `_ensure_token`
  (`backend/clients/eight_sleep.py:134-165`) calls `_persist_env_var`
  with `EIGHT_SLEEP_REFRESH_TOKEN` and `EIGHT_SLEEP_USER_ID`. **There
  is no `oauth_tokens` row for Eight Sleep** — unlike Strava and Whoop,
  this client never touches the DB token store. On Railway (no
  writable `.env`), every cold start re-runs the password grant because
  the rotated refresh token can't be persisted.
- **Fetch / schedule**: pull-mode, same APScheduler `sync_all` job.
  `SyncEngine.sync_eight_sleep` (`backend/services/sync.py:328-338`)
  delegates to `backend/services/eight_sleep_sync.py:sync_eight_sleep`.
  Default window 30 days.
- **DB write**: `sleep_sessions` rows with `source="eight_sleep"`,
  keyed on `(source, date)` unique constraint. Upsert:
  `eight_sleep_sync.py:_sync_window:121-148`.
- **Frontend read**: `frontend/src/api/sleep.ts` → `GET /api/sleep`,
  `/api/sleep/trends`, and the merged `dashboard/today` payload.

### Whoop

- **Auth**: OAuth2 authorization code with `offline` scope. Start
  `/api/auth/whoop` (`backend/routers/auth.py:70-83`); callback at
  `/api/auth/whoop/callback` (`:86-196`). Callback also writes the
  tokens AND `WHOOP_ENABLED=true` to `.env` via `_persist_env_var`
  (`:140-149`), then verifies via `/developer/v2/user/profile/basic`.
- **Token storage**: `oauth_tokens` table (source of truth) + `.env`
  best-effort (`backend/clients/whoop.py:192-218`).
- **Enabled gate**: `WhoopClient.is_enabled` checks
  `_enabled and bool(_access_token)`;
  `_enabled = settings.whoop.enabled` at construct time
  (`backend/clients/whoop.py:86`). `ensure_ready()` (`:181-190`) does
  the lazy DB load then re-evaluates; the sync engine uses
  `ensure_ready()` (`backend/services/sync.py:353`) and
  `whoop_sync.sync_whoop` uses it too
  (`backend/services/whoop_sync.py:76`). Comment at
  `clients/whoop.py:174-178` says: "Treat the presence of any usable
  token as 'configured' ... the WHOOP_ENABLED env var was the legacy
  gate; with DB-backed tokens it can lag".
- **Fetch / schedule**: same APScheduler `sync_all` job; default 30-day
  window. Endpoints `/cycle`, `/recovery`, `/activity/sleep`,
  `/activity/workout` (v2; `backend/clients/whoop.py:55, 344-374`).
- **DB write**: `recovery_records` (per cycle date), `sleep_sessions`
  with `source="whoop"`, `whoop_workouts` (`whoop_id` string-keyed).
  Upserts in `backend/services/whoop_sync.py:_upsert_*`.
- **Frontend read**: `frontend/src/api/recovery.ts`, `/api/recovery`,
  `/api/recovery/trends`.

### OpenWeatherMap / Open-Meteo

- **Auth**: OpenWeatherMap `OPENWEATHERMAP_API_KEY` query param
  (`backend/clients/weather.py:130`). Open-Meteo no key.
- **Provider switch**: `backend/clients/__init__.py:get_weather_client`
  — `WEATHER_PROVIDER` (default `openmeteo`).
  `settings.weather_provider` (`backend/config.py:128`).
- **Fetch / schedule**: `SyncEngine.sync_weather`
  (`backend/services/sync.py:382-493`) runs as part of `sync_all` every
  `SYNC_INTERVAL_HOURS`. Iterates activities with `start_lat/lng` AND
  `weather_enriched=False`, calls `get_historical_weather`.
  Self-throttled at ~1 call/sec (`backend/clients/weather.py:26`).
- **DB write**: one `weather_snapshots` row per activity, sets
  `activity.weather_enriched=True`.

### Manual weight training (entry)

- **Entry UI**: `/record` page → `frontend/src/pages/Record.tsx`. Set
  rows stamped with naive-local ISO via `toNaiveLocalIso(new Date())`
  (`frontend/src/components/record/datetime.ts:4-10`). On
  `handleFinish` (`:434-457`) builds payload via
  `buildPayload(exercises)` (`:218-247`), then
  `createStrengthSession({ date, activity_id: null, sets })`.
- **API**: `POST /api/strength/sets` → `create_sets` in
  `backend/routers/strength.py:97-129`. Validation via Pydantic
  (`StrengthSessionCreate`). Inserts each set row, `await db.commit()`,
  refreshes, returns `{created, session: session_summary(...)}` with
  201.
- **DB table**: `strength_sets` (`backend/models/strength.py:20-57`).
  FK to `activities.id` is nullable. `performed_at` column was added by
  migration `b3c6d9e8a1f4`
  (`alembic/versions/b3c6d9e8a1f4_strength_set_performed_at.py`);
  `database.py:_ensure_compat_schema` (`:75-111`) adds it at startup if
  missing for both SQLite (PRAGMA) and Postgres (information_schema).
- **Frontend confirms**: `clearRecordDraft()` →
  `invalidateAppDataQueries` → `navigate("/history")`. On exception,
  `setError(getErrorMessage(...))` is shown
  (`frontend/src/pages/Record.tsx:454`).

---

## 3. Root-cause hypotheses for the known bugs

### Bug A — Data not refreshing (Strava / Eight Sleep / Whoop)

Ranked by probability.

**A1 (high) — Eight Sleep refresh-token rotation cannot persist on
Railway, so the password grant runs on every cold start AND silently
fails if the user_id cache is also lost.**

- `EightSleepClient` only stores tokens to `.env`
  (`backend/clients/eight_sleep.py:158, 165, 224, 229`). It does not
  use the `oauth_tokens` table. `_persist_env_var`
  (`backend/clients/eight_sleep.py:335-356`) reads/writes
  `_default_env_path() = /app/.env` on Railway — which does NOT exist
  in the Docker image (`Dockerfile:13-18` only copies `pyproject.toml`,
  `backend`, `alembic`, `alembic.ini` and the frontend dist).
  `if not env_path.exists(): logger.debug(...) ; return` — silent
  no-op. Each container restart starts from whatever Railway env vars
  exist; if you rotate by writing to memory but never persist, your
  Railway variable becomes stale after Eight Sleep rotates. Then a
  refresh succeeds in-memory once but fails after the next restart,
  falling back to password grant — which works if
  `EIGHT_SLEEP_EMAIL`/`EIGHT_SLEEP_PASSWORD` are set on Railway. README
  says they should be (`README.md:163-167`). **Verify Railway vars
  actually contain valid email/password**; if so, this is degraded but
  functional.
- Comment in client (`backend/clients/eight_sleep.py:212-217`) admits:
  "Refresh-grant responses don't echo userId back. If we got here via
  refresh (and the cached .env user_id is missing), force a password
  grant". If Railway has `EIGHT_SLEEP_REFRESH_TOKEN` set but no
  `EIGHT_SLEEP_USER_ID`, every call falls back. If both are missing,
  password grant is used.
- This isn't catastrophic by itself but it is **suspicious because
  Eight Sleep is the one client that bypasses `oauth_tokens`**.
  Migration from Mac mini→Railway was rushed; if the user copied
  `.env` values to Railway once but didn't copy `EIGHT_SLEEP_USER_ID`,
  refresh calls fail with
  `EightSleepAuthError("unable to determine Eight Sleep user id")`
  from `_get_user_id` (`:204-234`).

**A2 (high) — Strava token Railway-variable seeding is stale, and
`StravaClient` re-reads from `.env` at construct time which is also
missing on Railway.**

- `StravaClient.__init__` (`backend/clients/strava.py:75-82`):
  `self._access_token = _read_env_var(self._env_path,
  "STRAVA_ACCESS_TOKEN") or settings.strava.access_token`. On Railway
  `.env` doesn't exist so `_read_env_var` returns None and
  `settings.strava.access_token` (read once at process start from
  Railway env var) is used. That seed is then **immediately
  overwritten** on first awaited call by `_load_tokens_if_needed`
  (`:233-257`) reading from `oauth_tokens`. So as long as
  `oauth_tokens` has a fresh row, this works.
- The risk is **first deploy after migration**: if the user copied
  Strava tokens into Railway variables but the `oauth_tokens` table
  doesn't yet have a row, the client bootstraps a row from env
  (`:248-256`) — fine. **But** if the user re-ran OAuth locally after
  creating Railway tokens, the Railway env var has a *stale* refresh
  token; bootstrap writes it; the next `_ensure_token` tries to
  refresh with a single-use token already spent locally → 400 →
  `resp.raise_for_status()` raises (`backend/clients/strava.py:303`).
  The exception propagates to `sync_strava`, which logs a `SyncLog`
  row with `status=error` (`backend/services/sync.py:113-118`).
  Subsequent runs reuse the same dead refresh token. The user has to
  re-run OAuth on the Railway host. **Likely candidate. Easy to
  verify: check `oauth_tokens` row, check `sync_log` table for recent
  `status=error` rows.**

**A3 (high) — Whoop's `is_enabled` synchronous gate may be returning
False during the sync_all loop.**

- `sync_all` (`backend/services/sync.py:52-60`) calls
  `self.sync_whoop()` (`:342-378`). That method now correctly uses
  `await self.whoop.ensure_ready()` (`:353`) which does the lazy DB
  load. **Older callers** still use the sync `is_enabled` property:
  `WhoopClient.get_recovery/sleep/workouts/cycles` all return `[]` if
  `not self.is_enabled` (`backend/clients/whoop.py:344-374`).
  `is_enabled = self._enabled and bool(self._access_token)`.
  Construct-time `_enabled = settings.whoop.enabled` (`:86`). If
  Railway var `WHOOP_ENABLED` is unset/false but a valid `oauth_tokens`
  Whoop row exists, `_load_tokens_if_needed` (`:174-178`) flips
  `_enabled` true. But the `_get` path
  (`backend/clients/whoop.py:271-272`) also early-returns when
  `not self.is_enabled` *before* `_ensure_token` (note the order:
  `if not self.is_enabled: return {}` then `await self._ensure_token()`).
  If `_load_tokens_if_needed` hasn't run yet, you get a silent empty
  dict. `sync_whoop` does call `ensure_ready` first, which triggers
  the load — so within the sync path this should be OK. But the public
  methods on the client (`get_profile`, `get_recovery`, etc.) called
  directly elsewhere would silently no-op. Lower confidence than A2.

**A4 (medium) — Alembic migrations were never run on Railway Postgres;
schema is whatever `Base.metadata.create_all` produces, plus the
`_ensure_compat_schema` patch.**

- `Dockerfile:27` runs only `uvicorn`; no `alembic upgrade head`. The
  lifespan calls `init_db()` which is `create_all +
  _ensure_compat_schema` (`backend/database.py:68-72`). `alembic.ini:3`
  has `sqlalchemy.url = sqlite+aiosqlite:///./health_tracker.db`
  hardcoded; `alembic/env.py` does NOT override from `DATABASE_URL`.
  So running `alembic upgrade head` against Railway Postgres would NOT
  WORK from inside the container — it would try to write to SQLite.
- `create_all` does create all tables (the ORM is the source of truth
  in this path), so schema is "mostly correct". But: server-default
  values written by migrations using `op.execute(...)` won't run.
  Migration `c1a4e8f27b10_goals_rpe_feedback` and
  `b8f3d21e9a4c_whoop_workout_id_to_string` (type change int→str) for
  example could leave columns in inconsistent states if a partial DB
  was migrated by hand. The `alembic_version` table will simply be
  empty/missing on Railway.
- Net effect on bug A: **possibly innocuous now but a long-term
  hazard**. The reason this matters for "data not refreshing" is that
  any silent schema mismatch (e.g. an additional `NOT NULL` constraint
  a migration would have added) could cause `sync_*` upserts to fail
  with `IntegrityError`, which is then caught and logged as
  `error: {e}` in `sync_all` (`backend/services/sync.py:58-59`).
  **Check `sync_log` rows for `error_message` content** to confirm.

**A5 (medium) — Frontend cache: a 12h `staleTime` plus a `localStorage`
persister means even after sync runs, the dashboard may show old data
for up to 12 hours.**

- `frontend/src/lib/queryCache.ts:4`: `APP_STALE_TIME_MS = 12h`.
  `:11`: `QUERY_CACHE_BUSTER = "health-tracker:query-cache:v1"`.
  Queries with these prefixes are persisted to `localStorage`. If a
  user's "data not refreshing" complaint is "I see yesterday's run
  still missing", the data may already be in Postgres but the
  dashboard tile was rendered from cached JSON. Only triggered
  refetches (route changes, manual sync via `SyncSection.tsx`) call
  `invalidateAppDataQueries`. **Verify: load the dashboard with
  devtools network tab and confirm a fresh fetch is happening before
  drilling into ingestion.**

**A6 (low) — `_run_sync` swallows the per-source error message into a
string, so users see no surfaced reason.**

- `backend/services/sync.py:56-60` writes
  `results[source] = f"error: {e}"`. `_run_sync` logs this at INFO
  (`backend/scheduler.py:77`). The `/api/sync/status` endpoint reads
  the most recent `sync_log` row, which for `sync_all` is only created
  by `sync_strava` / `sync_whoop` (Eight Sleep too) individually — and
  the Strava row gets `status=success` even when an inner exception
  was caught by `sync_all`. So the user-facing status can be green
  while the data didn't update. This isn't itself a bug cause; it's
  why bug A is invisible.

**Quick checks to run** (read-only, but you'd run them on the live
Railway DB):

1. `SELECT * FROM oauth_tokens;` — confirm fresh rows for `strava` and
   `whoop`.
2. `SELECT source, status, started_at, completed_at, error_message
   FROM sync_log ORDER BY started_at DESC LIMIT 30;` — error messages
   here are gold.
3. `SELECT MAX(start_date), COUNT(*) FROM activities;` — when did
   Strava last land data?
4. `SELECT source, MAX(date), COUNT(*) FROM sleep_sessions
   GROUP BY source;`
5. `SELECT MAX(date) FROM recovery_records;`
6. Check Railway variables: `STRAVA_REFRESH_TOKEN`,
   `EIGHT_SLEEP_EMAIL`/`PASSWORD`/`USER_ID`, `WHOOP_ACCESS_TOKEN`/
   `REFRESH_TOKEN`, `WHOOP_ENABLED`, `SYNC_ON_STARTUP`.

---

### Bug B — Lifting workout save fails

Ranked by probability.

**B1 (high) — `strength_sets.performed_at` column missing on Railway
Postgres because Alembic never ran; the runtime patch may be
racing/incomplete or applied to a different connection.**

- The model declares `performed_at`
  (`backend/models/strength.py:48`). The frontend payload
  (`frontend/src/pages/Record.tsx:235-243`, `buildPayload`) always
  sends `performed_at` (set to `set.performed_at` which is stamped on
  "Log set" tap, `:406`). The router writes it
  (`backend/routers/strength.py:117`). If the table is missing the
  column on Railway, `db.commit()` raises a Postgres `UndefinedColumn`
  error.
- `database.py:_ensure_compat_schema` (`backend/database.py:75-111`)
  is supposed to fix this for both SQLite and Postgres. But it runs
  inside `init_db`'s `engine.begin()` block at lifespan startup. If
  the schema was bootstrapped by an earlier deploy *before* migration
  `b3c6d9e8a1f4` was added and `_ensure_compat_schema` was authored,
  AND if the strength table didn't exist at all on first boot
  (`create_all` would have made it WITH `performed_at`), there's no
  issue. **But** if the strength table predated the column and Railway
  is using the pre-`performed_at` version, this patch is the only
  thing standing between the user and the bug.
- Note the implementation reads columns from
  `information_schema.columns` *with `table_schema = current_schema()`*
  (`backend/database.py:97`). If the Railway database connection uses
  a non-default search_path or if the table lives in a different
  schema, the column check would falsely succeed in finding the column
  or fail to find the table at all and silently skip the patch. The
  `if columns and "performed_at" not in columns:` (`:108`) guard
  returns early when `columns` is empty (i.e. table not found), so on
  a fresh DB with no `strength_sets` yet, the patch is skipped — but
  `create_all` would have already created the table with the column.
  The dangerous case is: table exists, column doesn't, `columns` is
  non-empty, patch runs — which should work. **Most likely the patch
  silently fails on Postgres for another reason or the live DB has
  the column.** Direct verification:
  ```sql
  SELECT column_name FROM information_schema.columns
  WHERE table_name = 'strength_sets';
  ```
- **Smoking-gun caveat**: the migration that introduced `performed_at`
  (`b3c6d9e8a1f4_strength_set_performed_at.py`) has parent
  `a7e2c5f8b1d3`. Several routers/services and the merge revision
  `c2f7a4e91b85` depend on it. If Alembic was never applied, but
  `create_all` produces the column from the model — then the column
  SHOULD be present. **This hypothesis only holds if the DB was
  created from a snapshot/dump that predates the column.** Per
  CLAUDE.md (DB was migrated SQLite→Postgres rush), this is plausible.

**B2 (high) — `strength_sets.activity_id` FK +
`ON DELETE SET NULL` constraint on a Postgres deployment where the
constraint was created differently than the model expects.**

- Model: `ForeignKey("activities.id", ondelete="SET NULL")`
  (`backend/models/strength.py:36-40`). Migration:
  `e4a9b1c3d5f7_strength_sets.py:51-53` creates the same. Frontend
  always sends `activity_id: null` from Record.tsx
  (`pages/Record.tsx:449`). So no FK violation should occur.
- Lower confidence than B1.

**B3 (medium) — Pydantic input validator strictness; specifically
`weight_kg: float | None = Field(None, ge=0)` and the frontend sending
`weight_kg: 0` for bodyweight.**

- `StrengthSetInput` (`backend/routers/strength.py:32-46`):
  `weight_kg: float | None = Field(None, ge=0)`. The frontend
  `buildPayload` converts `weight: ""` → `null` and `0` is allowed
  (`pages/Record.tsx:226-228`, `parseOptionalNonNegative` returns
  `null` for empty, `0` for `"0"`). So a bodyweight set should pass.
- However, `parseOptionalNonNegative`
  (`pages/Record.tsx:191-196`) returns `undefined` for non-finite or
  negative. `buildPayload` then short-circuits with an error string.
  Not a backend bug.
- Set count: `set_number: int = Field(..., ge=1)`. The frontend
  `idx + 1` in `pages/Record.tsx:237` starts at 1. OK.
- **Possible subtle issue**: `set_number` is assigned `idx + 1` where
  `idx` indexes only the *logged* sets of one exercise, but the loop
  filters by `s.performed_at != null` (`pages/Record.tsx:223`). If
  users add multiple exercises and log out-of-order sets, this is
  fine. But if there are duplicate `(date, exercise_name, set_number)`
  combinations from a prior session on the same day, there's no DB
  unique constraint protecting against duplicates — the model doesn't
  declare one. So this isn't a failure cause; it's a data-quality
  risk.

**B4 (medium) — `_ensure_compat_schema` on Postgres uses
`information_schema.columns` with `current_schema()` but does NOT
account for the connection's transaction state.**

- The patch runs inside `engine.begin()` (`backend/database.py:70`).
  If a prior transaction in the same connection altered the schema
  and rolled back, the column count check sees one state but the
  ALTER TABLE in the same `engine.begin()` block could conflict.
  Probably not the bug; flagging as a code-smell since this whole
  helper is unusual.

**B5 (low) — Frontend always sends `activity_id: null` from the
Record page so manual logging cannot link to a Strava `WeightTraining`
activity.**

- Not a "save fails" bug, but a missing feature:
  `pages/Record.tsx:449` hardcodes `activity_id: null`. The
  `StrengthSession.activity_id` is preserved only when set via PATCH
  (`backend/routers/strength.py:67`). User-facing: the dashboard's
  HR-curve overlay on a strength session only renders when
  activity_id is set (`backend/services/strength.py:146-163`).
  Lifting saves still succeed; the link is just never made.

**B6 (medium-low) — Empty payload edge case: when the user starts a
session, logs no sets, and hits Finish.**

- Backend `create_sets` raises 400 if `not payload.sets`
  (`backend/routers/strength.py:103-104`). Frontend short-circuits
  with `"Log at least one set before finishing."` before the API call
  (`pages/Record.tsx:444-447`). Fine.

**B7 (medium-low) — Cache poisoning by `JSON.parse(text)` returning
`undefined as T` on empty body.**

- `fetchJson` (`frontend/src/api/http.ts:42-47`): on 201 with empty
  body returns `undefined`. The strength POST returns 201 with a JSON
  body though (`{"created": n, "session": ...}`,
  `backend/routers/strength.py:126-129`). Not a bug.

**Smoking-gun checks**:

1. **Reproduce the bug in dev tools**: open Network tab, log a set,
   hit Finish. Inspect the `POST /api/strength/sets` request body and
   the response (status, body). The frontend `getErrorMessage`
   (`frontend/src/utils/errors.ts`) surfaces backend `detail` strings
   — a Postgres column error would show as
   `column "performed_at" of relation "strength_sets" does not exist`.
2. **Inspect Railway logs** for the same request — the middleware at
   `backend/main.py:79-115` logs `status` and `duration_ms`. 500s are
   logged with `exception()` (`:96`) so the full stack trace is there.
3. **Direct DB check**: `\d strength_sets` in Railway Postgres console.

---

## 4. Migration debt (Mac mini → Railway)

| # | File:line | Issue |
|---|---|---|
| M1 | `alembic.ini:3` | `sqlalchemy.url = sqlite+aiosqlite:///./health_tracker.db` is hardcoded. `alembic/env.py` does NOT override from `DATABASE_URL`. Running `alembic upgrade head` on Railway against Postgres requires either editing this file or passing `-x sqlalchemy.url=...`. |
| M2 | `Dockerfile:27` | Runs only `uvicorn`. No `alembic upgrade head`. Schema management on Railway is entirely via `create_all + _ensure_compat_schema`, bypassing the migration history. New migrations that contain data transforms or non-trivial constraints will simply not apply. |
| M3 | `backend/clients/eight_sleep.py:303-306` | `_default_env_path()` returns the repo-root `.env` (a sibling of `pyproject.toml`). Inside the Railway container the `.env` file is NOT in the image (`Dockerfile:13-18` doesn't COPY it; nor should it — secrets should come from Railway env vars). All `_persist_env_var` calls (here, `clients/strava.py:278`, `clients/whoop.py:216-218`, `routers/auth.py:140-149`) become silent no-ops on Railway (`_persist_env_var` early-returns on `not env_path.exists()`, `:343-344`). For Strava and Whoop the DB token persistence still works; for Eight Sleep there is no DB-backed alternative — **so Eight Sleep refresh-token rotation does not persist across container restarts on Railway**. |
| M4 | `backend/main.py:65` | CORS allow-list hardcodes `localhost:5173` and `localhost:3000`. Augmented by `settings.tailscale_hostname` (`:66-68`) and `settings.cors_origins`. Same-origin Railway access works fine (frontend served from same host), but any custom-domain front-end split would silently fail CORS. |
| M5 | `backend/routers/auth.py:32-37` | `_oauth_callback_base()` defaults to `http://localhost:8000` if `PUBLIC_BASE_URL` is unset. On Railway without `PUBLIC_BASE_URL`, OAuth callbacks redirect to localhost — Strava/Whoop will reject. README warns about this (`README.md:91-94`) but it's not enforced. |
| M6 | `backend/routers/sync.py:65` | Sync hint message: `"Add credentials to .env for unconfigured sources"` — wrong instruction on Railway. Cosmetic but symptomatic of the rush. |
| M7 | `backend/routers/sync.py:123-154` | `/api/sync/debug/db` endpoint is SQLite-only: it runs `PRAGMA database_list` (`:133`), which fails on Postgres. The route doesn't dialect-guard. If anything in the frontend hits it (e.g. a settings debug panel), it 500s on Railway. |
| M8 | `deploy/` directory | All Mac-only: `com.healthtracker.plist.template`, `install.sh` (uses `launchctl`, `~/Library/LaunchAgents`, `brew`), `update.sh`. **There is no equivalent Railway deploy script.** The Mac-mini install also assumes a `.venv` and a writable `~/.health-tracker/`. None of this is removed or quarantined post-migration. |
| M9 | `backend/config.py:115` | `sync_on_startup: bool = True`. README explicitly recommends `SYNC_ON_STARTUP=false` on Railway (`README.md:99-101`) to avoid blocking the health-check window, but the default is True. If Railway env var isn't set, a long sync runs on every cold start and competes with the health check (`railway.toml:7` has 120s timeout). |
| M10 | `backend/config.py:11` | `_DEFAULT_DB_URL` points to `~/.health-tracker/health_tracker.db` which is Mac-mini-specific. Only used as fallback when `DATABASE_URL` is unset. On Railway you must have `DATABASE_URL` set or the app writes SQLite to an ephemeral container path. |
| M11 | `backend/models/*.py` (multiple) | All `JSON` columns use `from sqlalchemy.dialects.sqlite import JSON` (`activity.py:18`, `sleep.py:6`, `weather.py:6`, `whoop_workout.py:15`, `user_profile.py:8`, `recovery.py:6`). On Postgres these map to TEXT, not JSONB — losing operator support, indexing, and silently serializing dicts as strings. Compare with `backend/services/oauth_tokens.py:16-17` which DOES dialect-switch upserts but the schema-level JSON does not. |
| M12 | `tests/test_database.py:8` | Only the SQLite branch of `_ensure_compat_schema` is tested (`PRAGMA table_info`). The Postgres branch (`backend/database.py:90-103`) is **not tested at all**. Same module is the Railway-only path for adding `performed_at` if missing. |
| M13 | `.env.example:55-63` | Duplicated `TAILSCALE_HOSTNAME=` declaration on lines 59 and 63 — pure rush artifact. |
| M14 | `backend/clients/strava.py:75-82`, `clients/whoop.py:73-82` | Token seed-on-construct does `_read_env_var(self._env_path, ...)` first, then `settings.*` second. On Railway `.env` doesn't exist so it always falls through to the env-derived setting — the function call is wasted I/O on every client construct (and the scheduler constructs new clients every 2h + on every `POST /api/sync/trigger`). Functionally harmless but pre-Railway pattern. |
| M15 | `scripts/*.py` | Every script in `scripts/` (`backfill_strava.py`, `backfill_weather.py`, `backfill_eight_sleep.py`, `purge_streams.py`, `classify_all.py`, etc.) is documented in README/AGENTS.md for local CLI use. There is no Railway-side mechanism to invoke them (no Railway cron, no admin endpoint). After migration, the user can no longer trigger a backfill without `railway run` or shelling in. |
| M16 | `backend/services/whoop_sync.py:73-78` and `clients/whoop.py:174-178` | Defensive comments admitting "WHOOP_ENABLED env var lags the oauth_tokens table after a Railway redeploy" — direct evidence that the migration surfaced this bug, the fix was applied to the sync path but not the client property. |
| M17 | `backend/main.py:32-42` and `scheduler.py:91-122` | APScheduler runs **in-process** inside the FastAPI app. On Railway this is fine for a single-instance deploy but breaks silently if Railway ever auto-scales to 2 instances (each runs its own scheduler → duplicate Strava calls → faster rate-limit exhaustion). Mac mini had only one process, no risk. No locking/leader-election here. |

---

## 5. Test coverage assessment

### Organization

- pytest with `asyncio_mode = "auto"` (`pyproject.toml:51-52`). Tests
  in `tests/` split by layer: `test_clients/`, `test_services/`,
  `test_sync/`, `test_routers/`, `test_database.py`. Frontend uses
  vitest + Testing Library.
- Backend tests run via `python -m pytest` (CI:
  `.github/workflows/ci.yml:31`). Frontend via
  `npm run typecheck && npm run build` (no `npm test` step in CI).
- Router tests share fixture in `tests/test_routers/conftest.py`:
  in-memory SQLite, FastAPI app with single router mounted, dependency
  override of `get_db`.

### Coverage by area

| Area | File(s) | Coverage |
|---|---|---|
| Strava client | `tests/test_clients/test_strava.py` | Yes (stubbed HTTP) |
| Eight Sleep client | `tests/test_clients/test_eight_sleep.py` | Yes |
| Weather (OWM) | `tests/test_clients/test_weather.py` | Yes |
| Open-Meteo | `tests/test_clients/test_openmeteo*.py` | Yes (both weather + air quality) |
| Elevation | `tests/test_clients/test_elevation.py` | Yes |
| Whoop client | none | **Missing — no `test_whoop.py` for the client itself**. `test_sync/test_whoop_sync.py` covers the sync logic with a stub. |
| Strava sync | `tests/test_sync/test_strava_sync.py` | Yes |
| Eight Sleep sync | `tests/test_sync/test_eight_sleep_sync.py` | Yes |
| Whoop sync | `tests/test_sync/test_whoop_sync.py` | Yes |
| Elevation sync | `tests/test_sync/test_elevation_sync.py` | Yes |
| Classifier | `tests/test_sync/test_classifier.py`, `test_classifier_altitude.py` | Yes |
| Correlations | `tests/test_sync/test_correlations.py`, `test_sleep_analytics.py` | Yes |
| Strength service | `tests/test_services/test_strength.py`, `test_strength_hr.py` | Service helpers covered; **no router test** |
| Insights / LLM | `tests/test_services/test_insights.py`, `test_llm_providers.py` | Yes |
| Scheduler guards | `tests/test_services/test_scheduler_jobs.py` | Yes — but only the enrichment drain, not `_run_sync` itself |
| Routers — `/strength` POST | **NONE in `tests/test_routers/`** | Critical gap given Bug B |
| Routers — `/sync/trigger`, `/sync/status` | **NONE** | Bug A invisible |
| Routers — `/auth/strava`, `/auth/whoop` callbacks | **NONE** | |
| Routers — `/dashboard/today` | `tests/test_routers/test_dashboard_today.py` | Yes |
| Routers — `/sleep`, `/recovery`, `/goals`, `/chat`, `/profile`, `/locations`, `/insights/feedback`, activity feedback | Each has a test file | Yes |
| `_ensure_compat_schema` SQLite branch | `tests/test_database.py` | Yes |
| `_ensure_compat_schema` Postgres branch | **NONE** | Critical gap for Bug B — this is the only safety net for the `performed_at` column on Railway |
| `backend/database.py:_database_url` URL rewriting | **NONE** | The `postgresql://` → `postgresql+asyncpg://` rewrite (`backend/database.py:20-23`) is the one piece of Railway-specific logic and isn't tested |
| OAuth tokens upsert dialect switch | **NONE** | `services/oauth_tokens.py:save_tokens` has a postgres/sqlite branch (`:59-67`) — untested in isolation |
| Frontend Record page | `frontend/src/pages/Record.test.tsx` | Yes — mocks `createStrengthSession` and asserts payload shape. Does NOT cover the failure path. |

### Tests that would fail on the live Railway DB but pass in CI

- Every router/sync test uses in-memory SQLite. There is **no
  integration test against Postgres**. CI never exercises the
  Railway-specific code paths.

### Are the broken behaviors tested?

- **Bug A (data not refreshing)**: scheduler guard tests exist
  (`test_scheduler_jobs.py`) but only assert pending-quota and
  pending-count edge cases. **No end-to-end test that, given valid
  token-row in `oauth_tokens` + a stub Strava response, a `sync_all`
  call lands rows in the DB and bumps `sync_log`.** The closest is
  `test_strava_sync.py` but it bypasses the scheduler. No test of the
  Eight Sleep .env-persistence behavior on a missing-file fs.
- **Bug B (lifting save fails)**: tested *only* via frontend mock
  (`Record.test.tsx`) and via service-layer helpers
  (`test_strength.py`). **No router test that posts a real
  `StrengthSessionCreate` to a FastAPI test client and checks the
  round-trip**. This is the most glaring coverage gap. The Postgres
  branch of `_ensure_compat_schema` is similarly untested. Currently
  the test suite would pass even if the live Postgres save was 500ing.

---

## 6. Recommended next steps (prioritized)

The audit's role is to point. In order:

1. **Inspect the live Railway database before changing code.**
   Read-only queries (no migrations yet):
   - `SELECT * FROM oauth_tokens;`
   - `SELECT source, status, started_at, completed_at, error_message
     FROM sync_log ORDER BY started_at DESC LIMIT 30;` — likely
     reveals Bug A's actual error message.
   - `\d strength_sets` (or equivalent `information_schema` query) —
     does `performed_at` exist? — resolves Bug B's likeliest cause in
     one query.
   - `SELECT MAX(start_date), COUNT(*) FROM activities;`,
     `SELECT source, MAX(date), COUNT(*) FROM sleep_sessions
     GROUP BY source;`, `SELECT MAX(date) FROM recovery_records;` —
     confirms staleness per source.
   - Audit Railway service variables for: `DATABASE_URL`,
     `PUBLIC_BASE_URL`, `SYNC_ON_STARTUP`, `STRAVA_*`,
     `EIGHT_SLEEP_EMAIL/PASSWORD/USER_ID/REFRESH_TOKEN`, `WHOOP_*`.
     **Most likely you'll find at least one expired or never-rotated
     token.**

2. **Bug B first — likely a 5-minute fix.** If `performed_at` is
   missing on the Railway `strength_sets` table: either run
   `ALTER TABLE strength_sets ADD COLUMN performed_at TIMESTAMP`
   directly, or trigger a redeploy now that `_ensure_compat_schema`
   exists (`backend/database.py:75-111`) — except confirm it actually
   ran (`SELECT * FROM information_schema.columns WHERE table_name =
   'strength_sets'`). If something blocked it, manually patch and
   then write the missing router test (B5 in recommended fixes).

3. **Bug A: re-OAuth from the Railway host.** The most common
   Mac→Railway migration failure mode for OAuth is that the user
   copied tokens from local `.env`, the Mac kept refreshing locally,
   single-use refresh tokens got spent there, and the Railway-side
   value is now dead. Visit
   `https://<your-railway-host>/api/auth/strava` and
   `…/api/auth/whoop` from a browser, complete OAuth — this writes
   fresh rows to `oauth_tokens`. Verify with a manual
   `POST /api/sync/trigger {"source": "strava"}` and
   `{"source": "whoop"}`, then check `/api/sync/status`.

4. **Eight Sleep on Railway: confirm credentials are in Railway
   variables AND add `EIGHT_SLEEP_USER_ID`.** Without
   `EIGHT_SLEEP_USER_ID`, the refresh-grant fallback in
   `_get_user_id` (`backend/clients/eight_sleep.py:204-234`) forces a
   password grant on every cold start. Set `EIGHT_SLEEP_USER_ID` from
   a successful local run, or add an OAuth-style callback for Eight
   Sleep that persists to `oauth_tokens`. Longer term: **move Eight
   Sleep token persistence into `oauth_tokens` to match Strava/Whoop**
   — eliminates a class of "rushed migration" bug.

5. **Make Alembic able to run on Railway.** Either:
   - (a) Patch `alembic/env.py` to honor `DATABASE_URL` (override
     `config.set_main_option("sqlalchemy.url", _database_url())` at
     top of `env.py`); then add `alembic upgrade head` to the
     Dockerfile `CMD` or as a Railway pre-deploy command.
   - (b) Or formally commit to `create_all + _ensure_compat_schema`
     as the schema strategy and document it. Either is fine; the
     status quo (both exist, neither runs in prod) is the
     rushed-migration smell.

6. **Add the missing router tests.** Highest value:
   - `tests/test_routers/test_strength.py` covering
     `POST /strength/sets`, `PATCH /strength/sets/{id}`,
     `DELETE /strength/sets/{id}`. Use the existing `conftest.py`
     fixture (`tests/test_routers/conftest.py:40-51`). Specifically
     test posting a payload that includes `performed_at` (catches Bug
     B regression).
   - `tests/test_routers/test_sync.py` covering
     `POST /sync/trigger` and `GET /sync/status` with stubbed
     clients. Covers the orchestration path Bug A lives in.
   - Add a Postgres branch to
     `tests/test_database.py:test_compat_schema_*` (use `pg-tmp` or
     `testcontainers-postgres`, or at minimum a SQL-only assertion
     that the Postgres branch is reachable).

7. **Defaults and config sanity**:
   - Flip `sync_on_startup` default to `False`
     (`backend/config.py:115`) — production-safer default; opt-in via
     env.
   - Add a startup-time assertion that on Postgres dialect,
     `PUBLIC_BASE_URL` is set; warn if not.
   - Dialect-guard `/api/sync/debug/db`
     (`backend/routers/sync.py:123-154`) or remove it (it's
     debug-only and currently 500s on Postgres).

8. **Migrate JSON columns to `JSON` from `sqlalchemy` core (or
   `JSONB` on Postgres) rather than
   `sqlalchemy.dialects.sqlite.JSON`**
   (`backend/models/{activity,sleep,recovery,weather,whoop_workout,user_profile}.py`).
   Low urgency, but pays for itself the first time you write a query
   against the JSON content on Postgres.

9. **APScheduler single-instance assumption**: document or enforce.
   Railway can autoscale; if it ever does, the in-process scheduler
   will run multiple times. Either pin replicas=1 in Railway, or add
   a `pg_try_advisory_lock` leader election around the scheduler
   jobs.

10. **Delete or quarantine `deploy/`** if Mac-mini operation is no
    longer supported. Otherwise add a README banner stating that the
    launchd path is unsupported and Railway is the source of truth
    (CLAUDE.md says it is).

---

### Confidence labels

- High confidence: file:line citations are exact and all confirmed
  by direct reads in this audit.
- Speculation explicitly labeled: A3 (Whoop is_enabled gate
  likelihood), A4-A6 (lower-prob alternatives), B4-B7 (lower-prob).
- One thing I could not confirm without DB access: which of B1 vs A2
  is the actual cause of the user-visible bugs. Both have specific
  testable hypotheses in step 1 above.
