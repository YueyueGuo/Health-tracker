# Health Tracker

Personal health & fitness analytics platform that pulls data from Strava, Eight Sleep, and Whoop, enriches it with weather data, and provides AI-powered coaching insights through a web dashboard, Telegram bot, and Discord bot.

## Features

- **Strava Integration** — Two-phase sync pulls summary + laps + time-in-zone distributions for every activity. Per-sample streams (HR, pace, power, cadence, elevation) are fetched lazily on demand and cached.
- **Workout Classifier** — Rules-based classification of runs (easy / tempo / intervals / race) and rides (recovery / endurance / tempo / mixed / race), with flags for `is_long`, `has_speed_component`, `has_warmup_cooldown`, `is_hilly`. See [`backend/services/classifier.py`](backend/services/classifier.py).
- **Weekly Summary** — `/api/summary/weekly` returns per-week totals, per-sport breakdown, classification mix, and flags (long run, speed session, long ride). Rendered on the dashboard as a 4-week strip.
- **Eight Sleep Integration** — Sleep stages, HRV, heart rate, respiratory rate, bed temperature
- **Whoop Integration** — Recovery score, strain, sleep, HRV, SpO2, skin temp (ready for when device arrives)
- **Weather Enrichment** — Automatic weather data for outdoor activities via OpenWeatherMap
- **Multi-Model AI Analysis** — Query your data using Claude, GPT-4o, Gemini, or other LLMs. Swap models per-request
- **Web Dashboard** — Interactive charts for activities, sleep trends, recovery, training load (CTL/ATL/TSB)
- **Telegram Bot** — `/today`, `/last`, `/week`, `/ask` commands for on-the-go insights
- **Discord Bot** — Slash commands with rich embeds for the same functionality
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

Agent context for future work lives in [`CLAUDE.md`](CLAUDE.md).

### 5. Start the App

```bash
# Backend API (terminal 1)
uvicorn backend.main:app --reload --port 8000

# Frontend dashboard (terminal 2)
cd frontend && npm run dev
```

Dashboard: http://localhost:5173
API docs: http://localhost:8000/docs

## Setup Guides

### Strava

1. Go to https://www.strava.com/settings/api
2. Create an application (use `http://localhost:8000` as the website and `http://localhost:8000/api/auth/strava/callback` as the callback)
3. Copy your Client ID and Client Secret to `.env`
4. Visit http://localhost:8000/api/auth/strava to complete OAuth
5. Copy the tokens to your `.env` file

### Eight Sleep

Add your Eight Sleep account email and password to `.env`:
```
EIGHT_SLEEP_EMAIL=your@email.com
EIGHT_SLEEP_PASSWORD=your_password
```

### Whoop

1. Register at https://developer.whoop.com
2. Create an application
3. Set `WHOOP_ENABLED=true` in `.env`
4. Visit http://localhost:8000/api/auth/whoop to complete OAuth

### Weather (OpenWeatherMap)

1. Sign up at https://openweathermap.org/api
2. Subscribe to the One Call API 3.0
3. Add your API key to `.env`

### LLM Providers

Configure one or more:
```
ANTHROPIC_API_KEY=sk-ant-...    # Claude (Sonnet, Opus, Haiku)
OPENAI_API_KEY=sk-...           # GPT-4o, GPT-4o-mini
GOOGLE_AI_API_KEY=...           # Gemini Pro, Flash
```

Set your preferred default:
```
DEFAULT_LLM_PROVIDER=claude-sonnet
```

### Telegram Bot

1. Message @BotFather on Telegram
2. Create a new bot with `/newbot`
3. Copy the token to `TELEGRAM_BOT_TOKEN` in `.env`
4. Run: `python -m bot.telegram_bot`

### Discord Bot

1. Go to https://discord.com/developers/applications
2. Create a new application and bot
3. Enable "Message Content Intent" in the Bot settings
4. Copy the bot token to `DISCORD_BOT_TOKEN` in `.env`
5. Invite the bot to your server with the OAuth2 URL Generator (scopes: `bot`, `applications.commands`)
6. Run: `python -m bot.discord_bot`

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

Bot (Telegram + Discord)
├── handler.py   → Shared ChatHandler (bot-agnostic logic)
├── telegram     → python-telegram-bot commands
└── discord      → discord.py slash commands + embeds

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
