# Health Tracker

Personal health & fitness analytics platform that pulls data from Strava, Eight Sleep, and Whoop, enriches it with weather data, and provides AI-powered coaching insights through a web dashboard.

## Features

- **Strava Integration** — Two-phase sync pulls summary + laps + time-in-zone distributions for every activity. Per-sample streams (HR, pace, power, cadence, elevation) are fetched lazily on demand and cached.
- **Workout Classifier** — Rules-based classification of runs (easy / tempo / intervals / race) and rides (recovery / endurance / tempo / mixed / race), with flags for `is_long`, `has_speed_component`, `has_warmup_cooldown`, `is_hilly`. See [`backend/services/classifier.py`](backend/services/classifier.py).
- **Weekly Summary** — `/api/summary/weekly` returns per-week totals, per-sport breakdown, classification mix, and flags (long run, speed session, long ride). Rendered on the dashboard as a 4-week strip.
- **Eight Sleep Integration** — Sleep stages, HRV, heart rate, respiratory rate, bed temperature
- **Whoop Integration** — Recovery score, strain, sleep, HRV, SpO2, skin temp (ready for when device arrives)
- **Weather Enrichment** — Weather for outdoor activities via Open-Meteo by default (no key) or OpenWeatherMap (optional)
- **Multi-Model AI Analysis** — Query your data using Claude, GPT-4o, Gemini, or other LLMs. Swap models per-request
- **Web Dashboard** — Interactive charts for activities, sleep trends, recovery, training load (CTL/ATL/TSB)
- **Scheduled Sync** — Automatic background data pulls on a configurable interval

## Quick Start

### 1. Install Dependencies

```bash
# Backend (Python 3.11+)
pip install -e ".[dev]"

# Frontend
cd frontend && npm install
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your credentials (see Setup Guides below)
```

### 3. Initialize Database

```bash
python scripts/setup_db.py
```

### 4. Run Initial Sync

```bash
python scripts/initial_sync.py
```

For Strava specifically, a full-history backfill is often easier than the
initial sync because it's resumable and rate-limit aware:

```bash
python scripts/backfill_strava.py              # full history, multi-day safe
python scripts/backfill_strava.py --no-list    # skip Phase A, only enrich
python scripts/classify_all.py                 # classify enriched activities
```

Agent context for future work lives in [`AGENTS.md`](AGENTS.md) (see also [`CLAUDE.md`](CLAUDE.md) for a Claude-specific pointer).

### 5. Start the App

```bash
# Backend API (terminal 1)
uvicorn backend.main:app --reload --port 8000

# Frontend dashboard (terminal 2)
cd frontend && npm run dev
```

Dashboard: http://localhost:5173  
API docs: http://localhost:8000/docs  

For a **public HTTPS URL** (phone, PWA, sharing), use **[Deploy on Railway](#deploy-on-railway)** below. To run 24/7 on your own Mac with Tailscale, see [`deploy/README.md`](deploy/README.md).

## Deploy on Railway

One **Railway service** runs the full stack: **FastAPI** (REST API + background scheduler) and the **built React app** from the same origin. The repo root [`Dockerfile`](Dockerfile) produces that image; [`railway.toml`](railway.toml) sets the health check to `GET /api/health`.

### Steps

1. In [Railway](https://railway.app), create a project and **deploy from GitHub** using this repository (`main` or your branch).
2. Add a **PostgreSQL** database in the same Railway project.
3. In your app service, set `DATABASE_URL` from the Railway Postgres connection variable (Railway usually exposes it as a variable reference like `${{ Postgres.DATABASE_URL }}`). The app converts `postgresql://...` to SQLAlchemy's async `postgresql+asyncpg://...` driver at runtime.
4. **Settings** → **Networking** → generate a **public URL** (e.g. `https://your-service.up.railway.app`). You will paste this into variables below.
5. **Variables** → add the tables below (same names as in [`.env.example`](.env.example)). Railway injects **`PORT`**; you do not need to set it unless debugging.
6. Deploy, then open the public URL. The dashboard should load; API docs are at `/docs`.

### Variables to set in Railway

#### Required for hosting (app + database)

| Variable | Example | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | `${{ Postgres.DATABASE_URL }}` | Railway Postgres connection URL. `DATABASE_PUBLIC_URL` also works as a fallback, but prefer `DATABASE_URL` from the app service to the database service. |
| `PUBLIC_BASE_URL` | `https://your-service.up.railway.app` | **No trailing slash.** Used to build Strava/Whoop OAuth `redirect_uri` values. Must match the URL users open in the browser. |

#### Strongly recommended

| Variable | Example | Purpose |
|----------|---------|---------|
| `SYNC_ON_STARTUP` | `false` | Avoids a long first boot while the deploy health check runs. Scheduled sync still runs on `SYNC_INTERVAL_HOURS`. |

#### Integrations (copy from your local `.env`)

Set whichever integrations you use. Names match `.env.example`.

| Prefix / variable | Notes |
|-------------------|--------|
| `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET`, `STRAVA_ACCESS_TOKEN`, `STRAVA_REFRESH_TOKEN` | After OAuth, tokens in Railway replace `.env` on your laptop for production. |
| `EIGHT_SLEEP_EMAIL`, `EIGHT_SLEEP_PASSWORD`, `EIGHT_SLEEP_TIMEZONE` | Optional: `EIGHT_SLEEP_REFRESH_TOKEN`, `EIGHT_SLEEP_USER_ID` if you already have them from local runs. |
| `WHOOP_ENABLED`, `WHOOP_CLIENT_ID`, `WHOOP_CLIENT_SECRET`, `WHOOP_ACCESS_TOKEN`, `WHOOP_REFRESH_TOKEN` | Set `WHOOP_ENABLED=true` when connected. |
| `OPENWEATHERMAP_API_KEY` | Only if you use OpenWeatherMap (`WEATHER_PROVIDER=openweathermap`). Default weather is Open-Meteo (no key). |
| `WEATHER_PROVIDER` | `openmeteo` (default) or `openweathermap`. |

#### LLM (optional; dashboard / chat)

| Variable | Notes |
|----------|--------|
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_AI_API_KEY` | Set any subset you need. |
| `DEFAULT_LLM_PROVIDER` | e.g. `claude-sonnet` |
| `DASHBOARD_MODEL`, `DASHBOARD_FALLBACK_MODELS` | Advanced; see [`backend/config.py`](backend/config.py). |

#### Optional tuning / domains

| Variable | Notes |
|----------|--------|
| `SYNC_INTERVAL_HOURS` | Default `2`. |
| `CORS_ORIGINS` | Comma-separated extra origins if you use a **custom domain** or split frontend/API later. Same-origin Railway URL usually needs **no** CORS entry. |
| `HOST` | Defaults to `0.0.0.0` in the container; rarely need to set. |
| `PORT` | **Do not set** unless you know you need it; Railway sets this. |

### OAuth redirect URLs on Railway

Register these with each provider (use your real `PUBLIC_BASE_URL` host):

- **Strava** (`https://www.strava.com/settings/api`):  
  `https://<your-host>/api/auth/strava/callback`
- **Whoop**:  
  `https://<your-host>/api/auth/whoop/callback`

For **local dev**, keep using `http://localhost:8000/...` in the provider consoles (or separate Strava apps for dev vs prod).

### Tokens and `.env` in Docker

The app sometimes **writes refreshed tokens to a repo-root `.env` file**. In Railway there is no persistent project `.env`; **store tokens as Railway variables** (copy from a successful OAuth response or from your laptop `.env`). After redeploys, if refresh fails, re-run OAuth or paste updated tokens into Variables.

### Data import note

Local development can still use SQLite (`sqlite+aiosqlite:///./health_tracker.db`), while Railway should use Postgres. Copying the raw SQLite file into Railway is only for the old SQLite-volume deploy path; for Postgres you need an import/export script or a fresh cloud sync/backfill.

## Setup Guides

### Strava

1. Go to https://www.strava.com/settings/api
2. Create an application. **Local dev:** website `http://localhost:8000`, callback `http://localhost:8000/api/auth/strava/callback`. **Railway:** website and callback use your `PUBLIC_BASE_URL`, e.g. `https://your-app.up.railway.app` and `https://your-app.up.railway.app/api/auth/strava/callback` (many people use a second Strava app for production).
3. Copy Client ID and Client Secret to `.env` (local) or Railway Variables (deployed).
4. Visit `/api/auth/strava` on the same host (e.g. `http://localhost:8000/api/auth/strava` or `https://your-app.up.railway.app/api/auth/strava`).
5. Copy returned tokens into `.env` or Railway Variables.

### Eight Sleep

Add your Eight Sleep account email and password to `.env` (local) or Railway Variables (deployed):

```
EIGHT_SLEEP_EMAIL=your@email.com
EIGHT_SLEEP_PASSWORD=your_password
```

If you already have `EIGHT_SLEEP_REFRESH_TOKEN` and `EIGHT_SLEEP_USER_ID` from a local run, add those too so the server does not need to re-authenticate on every cold start.

### Whoop

1. Register at https://developer.whoop.com
2. Create an application. Set **redirect URI** to match the host you use:  
   **Local:** `http://localhost:8000/api/auth/whoop/callback`  
   **Railway:** `https://<your-public-host>/api/auth/whoop/callback`
3. Set `WHOOP_CLIENT_ID` and `WHOOP_CLIENT_SECRET` in `.env` or Railway, and `WHOOP_ENABLED=true`
4. Visit `/api/auth/whoop` on that host to complete OAuth
5. Persist tokens in `.env` (local) or Railway Variables (deployed)

### Weather (OpenWeatherMap)

The app defaults to **Open-Meteo** (no API key). To use OpenWeatherMap instead, set `WEATHER_PROVIDER=openweathermap` in `.env` or Railway, then:

1. Sign up at https://openweathermap.org/api
2. Subscribe to the One Call API 3.0
3. Add `OPENWEATHERMAP_API_KEY` to `.env` or Railway Variables

### LLM Providers

Configure one or more in `.env` (local) or Railway Variables (deployed):
```
ANTHROPIC_API_KEY=sk-ant-...    # Claude (Sonnet, Opus, Haiku)
OPENAI_API_KEY=sk-...           # GPT-4o, GPT-4o-mini
GOOGLE_AI_API_KEY=...           # Gemini Pro, Flash
```

Set your preferred default:
```
DEFAULT_LLM_PROVIDER=claude-sonnet
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check |
| `/api/activities` | GET | List activities (filterable) |
| `/api/activities/{id}` | GET | Activity detail with streams |
| `/api/sleep` | GET | Sleep sessions |
| `/api/sleep/trends` | GET | Sleep trend data |
| `/api/recovery` | GET | Recovery records |
| `/api/recovery/trends` | GET | Recovery trend data |
| `/api/dashboard/overview` | GET | Dashboard overview data |
| `/api/chat/ask` | POST | Ask AI a free-form question `{"question": "...", "model": "..."}` |
| `/api/chat/models` | GET | List available AI models |
| `/api/insights/training-metrics` | GET | Raw training-load / sleep / recovery snapshot |
| `/api/insights/daily-recommendation` | GET | Structured daily training recommendation (cached) |
| `/api/insights/latest-workout` | GET | Structured insight for a workout (cached per activity) |
| `/api/sync/trigger` | POST | Trigger data sync `{"source": "all"}` |
| `/api/sync/status` | GET | Sync status per source |
| `/api/auth/strava` | GET | Start Strava OAuth |
| `/api/auth/whoop` | GET | Start Whoop OAuth |

## Architecture

```
Backend (FastAPI + SQLAlchemy + SQLite)
├── clients/     → Strava, Eight Sleep, Whoop, Weather API clients
├── models/      → SQLAlchemy ORM models (7 tables)
├── services/    → Sync engine, LLM providers, analysis engine, metrics
├── routers/     → FastAPI route handlers
└── scheduler    → APScheduler for periodic syncs

Frontend (React + Vite + Recharts)
├── Dashboard    → Overview with metric cards
├── Activities   → List + detail with HR/pace/power charts
├── Sleep        → Score trends, stage breakdown, HRV
├── Recovery     → Recovery score, HRV, strain tracking
├── Training     → CTL/ATL/TSB fitness model
└── Chat         → AI Q&A with model selector
```

## Available AI Models

| Key | Provider | Model |
|-----|----------|-------|
| `claude-sonnet` | Anthropic | Claude Sonnet 4 |
| `claude-opus` | Anthropic | Claude Opus 4 |
| `claude-haiku` | Anthropic | Claude Haiku 4.5 |
| `gpt-4o` | OpenAI | GPT-4o |
| `gpt-4o-mini` | OpenAI | GPT-4o Mini |
| `gemini-pro` | Google | Gemini 1.5 Pro |
| `gemini-flash` | Google | Gemini 1.5 Flash |
