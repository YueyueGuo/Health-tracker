# Project: Health & Fitness Tracker (PWA)

## What this is
A personal fitness and health tracking PWA. Aggregates data from
wearables, weather APIs, and manual workout entry into a unified
Postgres database. Serves analysis through a React dashboard. Built
initially for a single user (the project owner), with the option to
extend to others later.

## Stack
- **Backend**: FastAPI (Python), Railway Postgres
- **Frontend**: React + Vite (served as PWA)
- **Data sources**:
  - *External APIs*: Strava (workouts), Eight Sleep (sleep),
    Whoop (recovery/strain), OpenWeatherMap (weather)
  - *Manual entry*: weight training workouts (exercises, sets, reps)
    entered via the dashboard UI
- **Insights**: optional LLM analysis layer
- **Hosting**: Railway

## Repo layout
- `frontend/` — React + Vite app
- `backend/` — FastAPI server, ingestion logic, DB models
- `tests/` — unit test suite (fairly extensive coverage exists)

## Project history & current state
- v1 was built to run locally on a Mac mini with local Postgres
- Migrated to Railway Postgres + Railway-hosted backend so the app
  could be accessed from anywhere
- **The migration was rushed.** The suspected source of current bugs.

## Known issues (the focus of the first mission)
1. **Data not refreshing** — latest Strava / Eight Sleep / Whoop data is
   not appearing in the dashboard
2. **Lifting workout save fails** — manual weight training entry is not
   persisting to the database

## Conventions for agents working in this repo
- Run the existing test suite before opening any PR
- Add tests for new logic and bug fixes
- Use existing FastAPI patterns; don't introduce new frameworks without
  written rationale
- Treat the Railway deployment as the source of truth, not localhost
- Document non-obvious architectural decisions in `docs/decisions/`
- Open PRs against `main`; never push directly to `main`
- Never commit secrets or credentials

## Current mission: initial audit
Read-only architecture audit by the `architecture-auditor` agent.
No code changes. Produce a written report covering current architecture,
data flow, root-cause hypotheses for the two known bugs, migration debt,
and test coverage.

## Definition of "done" for the current mission
A written report covering the items listed in the architecture-auditor
agent definition, presented for the project owner's review. Once
reviewed, save to `docs/audit-001-initial.md`.

---

*This file is v1 and will evolve. It is the single source of truth for
project context — every agent reads it before working.*
