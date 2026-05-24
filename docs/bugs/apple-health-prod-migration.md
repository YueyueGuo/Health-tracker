# Production History tab returns 500 — Apple Health migration not applied

**Status:** resolved (2026-05-24)
**Reported:** 2026-05-24
**Symptom:** Dashboard History tab returns "Internal Server Error" on Railway production after PR #42 (Apple Health workouts) merged.

## Symptom

After merging PR #42 (Apple Health workouts) and Railway redeploying:
- Backend code references new columns (`activities.source`, `activities.external_id`, `activities.superseded_by_id`) and new tables (`health_data_points`, `workouts`, `workout_laps`).
- Production Postgres schema does NOT have these — the migration `37d57cfdb27d_apple_health_workouts.py` was never executed against production.
- Result: any endpoint that reads `activities` (e.g. the dashboard's training-load snapshot at `backend/services/training_load_snapshot.py:67`) raises `UndefinedColumnError: column activities.source does not exist` → 500.

## Confirmed root cause

The Dockerfile's `CMD` runs `uvicorn` directly with no `alembic upgrade head` step:

```dockerfile
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
```

Migrations have to be applied manually for every deploy. PR #42 was merged without that manual step, and we couldn't complete it because of the secondary issues below.

## Production DB state (partial info)

- Owner ran `psql "$RAILWAY_URL" -c "SELECT version_num FROM alembic_version;"` → returned `d4f1a8b62c70`.
- That revision **does not exist** in the local alembic history. Local head is `37d57cfdb27d`, parent is `a9d2f6c1e3b7`, then `f9c2e1a45b80`.
- Hypothesis: `d4f1a8b62c70` was a revision from one of the parallel audit/review branches that got reworked before landing on `main`. Production was stamped to a revision that later disappeared from the codebase.
- The schema state of production is **unknown** — we couldn't run `\d activities` to verify which columns/tables actually exist. (See blocker below.)

## Secondary blocker: can't run alembic locally against Railway Postgres

Owner's local env: macOS, Python 3.14 (Homebrew), fresh `.venv` with `pip install -e .`.

Attempts:

1. `python -c "from alembic.config import Config; ..."` with `postgresql://...` URL → `ModuleNotFoundError: No module named 'psycopg2'` (alembic fell back to sync driver because URL scheme was bare `postgresql://`).
2. Same with `postgresql+asyncpg://...` scheme → `socket.gaierror: [Errno 8] nodename nor servname provided, or not known` from inside asyncpg's `_create_ssl_connection`.
3. `psql "$RAILWAY_URL" -c "select 1;"` against the **same** URL → **works fine**, returns `1`.
4. `dig +short shinkansen.proxy.rlwy.net` and `nc -zv ... 43454` → both succeed, so DNS + connectivity are fine.

So the connection works from psql but fails from asyncpg in the same shell with the same URL. Suspected cause: Python 3.14 + asyncpg compatibility, OR a URL-special character in the Railway-generated password that breaks asyncpg's URL parser.

## Investigation hints / paths the investigator should consider

1. **First: figure out production schema state.** Try `psql "$RAILWAY_URL" -c "\d activities"` and `psql "$RAILWAY_URL" -c "\dt"` once `$RAILWAY_URL` is exported in the current shell. Decide based on the actual columns/tables what step is needed:
   - If `activities.source` doesn't exist AND `health_data_points` doesn't exist → production is at the pre-Apple-Health state. Stamp alembic_version to `a9d2f6c1e3b7` then apply `37d57cfdb27d`.
   - If the columns/tables exist already → just update `alembic_version` to `37d57cfdb27d`. (Someone may have applied the schema by hand without updating alembic.)
   - If state is partial/mixed → apply only the missing pieces and stamp.

2. **Sidestep the asyncpg issue.** Two viable paths:
   - Generate the migration SQL in alembic's offline mode (`alembic upgrade <rev>:head --sql > migration.sql`) and apply with `psql -f`. We know psql works.
   - SSH into the Railway backend container (Railway dashboard → backend service → "Shell" or `railway shell`). The container has the right env (DATABASE_URL set, deps installed) so `alembic upgrade head` should just work — assuming `env.py` reads the URL from env, which it currently does NOT (it reads from `alembic.ini`'s hardcoded value). So the env.py fix below is a prerequisite.

3. **Fix `alembic/env.py` to read `DATABASE_URL` from env.** Right now it only reads `sqlalchemy.url` from `alembic.ini`, which is hardcoded to `sqlite+aiosqlite:///./health_tracker.db`. This is the underlying reason migrations can't run cleanly in production at all. Suggested change:
   ```python
   import os
   url = os.environ.get("DATABASE_URL")
   if url and url.startswith("postgresql://"):
       url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
   if url:
       config.set_main_option("sqlalchemy.url", url)
   ```
   Plus updating any place that reads `config.get_section(...)`.

4. **Bake migrations into the Dockerfile** so this doesn't recur. Change the CMD to:
   ```dockerfile
   CMD ["sh", "-c", "alembic upgrade head && uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
   ```
   (After fix #3 lands, since the env.py change is what makes this work in the Railway container.)

5. **Look into how `d4f1a8b62c70` got into production.** The migration with parent `a9d2f6c1e3b7` (`a9d2f6c1e3b7_pg_identity_and_tz.py`) describes "two SQLite → Postgres migration regressions that were patched live against the Railway database during the audit-001 mission and never landed in the migration history." That audit work may have involved stamping production to a revision that was later replaced. Worth checking git log for any `audit-001` or `d4f1a8b62c70` references to understand what schema state production actually represents.

## Diagnostic facts to NOT re-run

- DNS resolves: yes.
- Network reaches port: yes.
- psql against `$RAILWAY_URL` works: yes (returned `1` from `select 1;`).
- asyncpg against the same URL: fails with gaierror.

## Wanted outcome

- History tab returns 200 on the production dashboard.
- `alembic_version` on production matches local `head` (currently `37d57cfdb27d`).
- A follow-up PR makes migrations run automatically on Railway deploy (Dockerfile + env.py fix), so the next migration doesn't have to be applied by hand.

## Resolution (2026-05-24, PR #46)

**Production schema state when we inspected:** Mixed. `alembic_version` was at
`d4f1a8b62c70`, but `Base.metadata.create_all()` on app boot had already
auto-created the new tables introduced between `d4f1a8b62c70` and
`37d57cfdb27d` (`user_profile`, `oauth_tokens`, `health_data_points`,
`workouts`, `workout_laps`). Only the `activities` column adds from
`37d57cfdb27d` were missing — which is exactly what was 500ing the History
endpoint, since `create_all` never ALTERs existing tables.

**Manual patch applied to prod:**

```sql
BEGIN;
ALTER TABLE activities ADD COLUMN source VARCHAR(32);
ALTER TABLE activities ADD COLUMN external_id VARCHAR(128);
ALTER TABLE activities ADD COLUMN superseded_by_id INTEGER;
CREATE INDEX ix_activities_superseded_by_id ON activities (superseded_by_id);
UPDATE activities SET source = 'strava' WHERE source IS NULL;
UPDATE activities SET external_id = CAST(strava_id AS TEXT) WHERE external_id IS NULL;
UPDATE alembic_version SET version_num='37d57cfdb27d' WHERE version_num = 'd4f1a8b62c70';
COMMIT;
```

History tab returned 200 immediately after. Auto-apply on future deploys
landed in PR #46 (env.py reads `DATABASE_URL`, Dockerfile prepends
`alembic upgrade head &&` to CMD).

## Follow-ups (deferred, separate PRs)

- **Drop `init_db()` / `create_all` from `backend/main.py` lifespan.** It was
  the silent mechanism that produced the partial-state schema above —
  with alembic running on boot it's at best redundant, at worst hides
  future migration drift the same way.
- **Audit auto-created tables against alembic-intended shape.** The
  `health_data_points` / `workouts` / `workout_laps` / `user_profile` /
  `oauth_tokens` tables on prod were created by `create_all`, which can
  produce subtle differences from `op.create_table` (index naming,
  nullability nuances, FK behavior). A future migration that ALTERs any
  of these could surprise.
- **Consider Railway release-command for migrations.** Running
  `alembic upgrade head` in the web container's CMD means a slow
  migration could trip Railway's startup health check before uvicorn
  binds the port. Not urgent — current migrations are small — but worth
  capturing in `docs/decisions/` when one isn't.
- **Investigate whether Apple Health workouts are actually ingesting.**
  Now that the schema is in place, separately verify Health Auto Export
  is reaching the backend and rows are landing in `health_data_points` /
  `workouts`.
