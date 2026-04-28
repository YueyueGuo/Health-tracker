# AGENTS.md

Canonical context for AI agents on this repo. Refresh stale claims with:  
`alembic heads`, routes in `frontend/src/App.tsx`, and `pytest --collect-only`.

## What this is

Personal health tracker: ingests **Strava**, **Eight Sleep**, **Whoop**, and **OpenWeatherMap** into a local **SQLite** database (WAL on), serves a **FastAPI** API, and a **React + Vite** dashboard with optional **LLM** insights (Anthropic / OpenAI / Google). Single-user, local-first.

## Repo map

| Area | Notes |
|------|--------|
| `backend/main.py` | App entry; lifespan wires scheduler |
| `backend/scheduler.py` | APScheduler — periodic full sync + Strava enrichment drain |
| `backend/services/sync.py` | `SyncEngine`; Strava two-phase sync, delegates Eight Sleep |
| `backend/services/eight_sleep_sync.py` | Eight Sleep-only sync (keep split from Strava edits) |
| `backend/clients/` | `strava`, `eight_sleep`, `whoop`, `weather`, `elevation` (httpx, async) |
| `backend/models/` | SQLAlchemy models |
| `backend/routers/` | `activities`, `auth`, `chat`, `correlations`, `dashboard`, `goals`, `insights`, `locations`, `recovery`, `sleep`, `strength`, `summary`, `sync`, `weather` |
| `frontend/src/` | Pages, components; `api/*.ts` domain clients; `api/http.ts` shared fetch |
| `scripts/` | Backfills, setup, one-offs (see below) |
| `alembic/` | Migrations (history is a **DAG**, not one linear list) |

## Stack

- **Backend**: Python **3.11+**, FastAPI, SQLAlchemy async, Alembic, APScheduler. Deps: [`pyproject.toml`](pyproject.toml).
- **Frontend**: React **19**, Vite, TypeScript, Recharts, Tailwind (see `globals.css` `@tailwind` layers) plus **CSS variables** for tokens (`--bg`, `--accent`, etc.). Deps: [`frontend/package.json`](frontend/package.json).
- **CI**: [`.github/workflows/ci.yml`](.github/workflows/ci.yml) — Ruff, pytest, `npm run typecheck`, `npm run build` (Node 22).

## Run locally

```bash
cp .env.example .env   # fill credentials
pip install -e ".[dev]"
python scripts/setup_db.py          # or your usual DB init
uvicorn backend.main:app --reload --port 8000

cd frontend && npm install && npm run dev
```

- Dashboard: http://localhost:5173  
- API docs: http://localhost:8000/docs  

**DB file**: `health_tracker.db` (and `*.db-wal`, `*.db-shm`) — gitignored.

## Migrations

- History has **merge revisions**; do not assume a single linear chain.
- **Current head** (last verified with doc update): `c2f7a4e91b85`. Confirm anytime: `alembic heads`.
- Prefer `op.add_column` for new nullable SQLite columns (not `batch_alter_table`) so running migrations alongside the scheduler is safe.

## Integrations (pointers)

**Strava** — [`backend/services/sync.py`](backend/services/sync.py), [`backend/clients/strava.py`](backend/clients/strava.py): Phase A lists activities (cheap), Phase B enriches detail + zones + laps; streams are **lazy** (on-demand API/cache, not bulk in sync). Shared module-level quota state; 429 → clean stop. Resumable backfill: `scripts/backfill_strava.py`.

**Eight Sleep** — [`backend/clients/eight_sleep.py`](backend/clients/eight_sleep.py), [`backend/services/eight_sleep_sync.py`](backend/services/eight_sleep_sync.py): three API hosts; password grant first, then refresh tokens persisted into `.env`; **refresh responses omit `userId`** — also persist `EIGHT_SLEEP_USER_ID`. Consumer-app client id/secret defaults in config are public, not secret. Rich interval data is **short-retention** vs trends; timezone: store bed/wake as **naive local**, not UTC `Z` mistaken for local.

**Whoop** — [`backend/clients/whoop.py`](backend/clients/whoop.py), [`backend/services/whoop_sync.py`](backend/services/whoop_sync.py). Re-auth via `/api/auth/whoop` if tokens go bad.

**Weather / elevation** — OpenWeatherMap client + Open-Meteo for elevation/geocoding; [`backend/services/elevation_sync.py`](backend/services/elevation_sync.py), user locations [`backend/routers/locations.py`](backend/routers/locations.py). Backfill: `scripts/backfill_elevation.py`.

## Domain logic (read the code for rules)

| Concern | Primary files |
|---------|----------------|
| Workout classification (rules, not ML) | [`backend/services/classifier.py`](backend/services/classifier.py) |
| Weekly summaries | [`backend/services/weekly_summary.py`](backend/services/weekly_summary.py), [`backend/routers/summary.py`](backend/routers/summary.py) |
| Sleep analytics / correlations | [`backend/services/sleep_analytics.py`](backend/services/sleep_analytics.py), [`backend/services/correlations.py`](backend/services/correlations.py) |
| Strength + HR from Strava streams | [`backend/services/strength.py`](backend/services/strength.py), [`backend/services/strength_hr.py`](backend/services/strength_hr.py) — read-only on streams; no lazy fetch |
| LLM insights | [`backend/services/insights.py`](backend/services/insights.py), `insight_schemas.py`, `insight_prompts.py`, `llm_providers.py`, `training_metrics.py` |

**Insights guardrail**: do not run structured LLM paths on Strava rows with `enrichment_status != "complete"` (no laps/quality data). Scheduler enrichment drain constructs **only** `StravaClient` when calling Phase B (avoids spurious Eight Sleep refresh).

## Frontend routes

From [`frontend/src/App.tsx`](frontend/src/App.tsx):

- `/` — Dashboard (`HomeLayout`)
- `/record`, `/history`, `/activities/:id` — `AppShell`
- `/sleep`, `/recovery`, `/training`, `/ask`, `/settings` — `Layout`

Lazy-loaded pages; prefer domain APIs under `frontend/src/api/` and shared [`frontend/src/api/http.ts`](frontend/src/api/http.ts).

## Scripts (common)

| Script | Purpose |
|--------|---------|
| `scripts/backfill_strava.py` | Full Strava history / Phase B loop |
| `scripts/classify_all.py` | Bulk classify (`--force` to overwrite) |
| `scripts/backfill_eight_sleep.py` | Eight Sleep history |
| `scripts/backfill_elevation.py` | Elevation + locations (`--phase1-only`, etc.) |
| `scripts/purge_streams.py` | One-off stream cleanup (if needed) |
| `scripts/setup_db.py`, `scripts/initial_sync.py` | Setup / first sync |

## Verify before you ship

```bash
ruff check .
python -m pytest
cd frontend && npm run typecheck && npm run build
```

Use `pytest --collect-only -q` for current test inventory without running tests.

## Conventions

- `.env` at repo root — never commit. `health_tracker.db`, `*.bak`, wal/shm gitignored.
- Parallel agents: use **separate branches** to avoid merge pain.
- Do not **merge to `main` / force-push shared branches** without explicit user confirmation.

## Archived design notes

Long-running feature plans and dated branch strategies live under [`docs/archive/`](docs/archive/) (not loaded into routine agent context).
