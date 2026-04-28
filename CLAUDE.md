# CLAUDE.md

**Agent context:** use **[`AGENTS.md`](AGENTS.md)** — canonical, kept current for this repo. This file is a thin pointer so Claude-flavored tools that only load `CLAUDE.md` still land in the right place.

## Claude / LLM configuration

- Structured dashboard insights and multi-provider routing live under `backend/services/insights.py`, `insight_schemas.py`, and `llm_providers.py`.
- API keys and model defaults come from [`backend/config.py`](backend/config.py) (`LLMSettings` / env vars). Prefer the same env patterns as `.env.example` for Anthropic, OpenAI, and Google.
- Do not call insight generation on Strava activities until `enrichment_status == "complete"` — see `AGENTS.md` guardrail.

Everything else (architecture, routes, migrations, scripts, CI) is in **`AGENTS.md`** — avoid duplicating it here.
