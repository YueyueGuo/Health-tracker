# Audit-001 — Execution plan & agent briefs

Companion to `docs/audit-001-initial.md`. This file scopes the
follow-up work into headless-agent-friendly tasks. Each brief is
self-contained: copy the brief into a fresh Claude Code session and
the agent should be able to land a PR without further prompting.

---

## Status board

| Wave | Task | Branch | PR | Status |
|---|---|---|---|---|
| 0 | DB diagnostics + findings doc | (manual) | — | TODO |
| 1 | W1-tests — router + Postgres tests | | | TODO |
| 1 | W1-alembic — Alembic on Railway | | | TODO |
| 1 | W1-config — defaults & dialect guards | | | TODO |
| 1 | W1-eightsleep-tokens — move to oauth_tokens | | | TODO |
| 1 | W1-deploy-cleanup — quarantine `deploy/` | | | TODO |
| 2 | W2-bug-B — fix lifting save | | | BLOCKED on Wave 0 |
| 2 | W2-bug-A — fix data refresh + surface errors | | | BLOCKED on Wave 0 |

Update this table as PRs open / merge.

---

## Wave 0 — diagnostics (manual, you do this)

Run from a machine with the Railway CLI:

```bash
railway run python scripts/diagnose_railway.py | tee docs/audit-001-findings.md
```

Or with an explicit URL:

```bash
DATABASE_URL='postgresql://...' python scripts/diagnose_railway.py \
  | tee docs/audit-001-findings.md
```

The script prints:

- `oauth_tokens` rows (tokens redacted) → confirms which providers
  have persisted DB tokens and whether they're expired.
- `sync_log` last 30 rows with `error_message` → reveals the real
  cause of Bug A.
- Per-source data freshness (`activities`, `sleep_sessions`,
  `recovery_records`) → quantifies the staleness.
- `strength_sets` schema → reveals whether `performed_at` is missing
  (Bug B smoking gun).
- `alembic_version` row → confirms whether Alembic ever ran on
  Railway.
- Presence of all relevant env vars (values redacted).

**Commit `docs/audit-001-findings.md` to the repo before kicking off
Wave 2.** Wave 1 can start without it.

---

## Wave 1 — parallel, independent (kick off all 5 at once)

These five briefs do not share any source files. They can run in
parallel as long as **W1-tests lands first**, since the others should
rebase onto its CI-with-Postgres setup.

### Brief: W1-tests

> **Branch off `main`.** Read `docs/audit-001-initial.md` §5 first.
>
> **Goal.** Close the test gaps that left Bugs A and B undetected by
> CI. Specifically:
>
> 1. **`tests/test_routers/test_strength.py`** — exercise the FastAPI
>    test client against `POST /api/strength/sets`,
>    `PATCH /api/strength/sets/{id}`, `DELETE /api/strength/sets/{id}`.
>    Use the existing fixture in `tests/test_routers/conftest.py`.
>    Cases:
>    - Round-trip a payload that includes `performed_at` — assert it
>      is returned and persisted (this would have caught Bug B).
>    - Empty `sets` list returns 400.
>    - Negative `weight_kg` returns 422 (Pydantic).
>    - `set_number < 1` returns 422.
>    - `activity_id` referencing a non-existent activity is accepted
>      (FK is nullable on delete; create one with a real activity_id
>      to verify the FK link works too).
> 2. **`tests/test_routers/test_sync.py`** — exercise
>    `POST /api/sync/trigger` and `GET /api/sync/status`. Stub the
>    `SyncEngine` methods on the FastAPI dependency. Assert that
>    `error_message` from a failed source surfaces in the status
>    response (it currently doesn't — leave this test failing if
>    that's true and add an `xfail` marker referencing
>    `backend/services/sync.py:56-60`; W2-bug-A will fix it).
> 3. **Postgres-branch test for `_ensure_compat_schema`.** Add a new
>    test module (e.g. `tests/test_database_postgres.py`) gated on
>    `TEST_POSTGRES_URL` being set in the environment (CI sets this).
>    Skip when unset. Test: create a `strength_sets` table WITHOUT
>    `performed_at`, run `_ensure_compat_schema`, assert the column
>    now exists. Mirror the SQLite test in `tests/test_database.py`.
>
> **Non-goals.** Do not touch any router or service code. Do not
> modify CI (Postgres service is already configured by an earlier
> change). Do not refactor the existing conftest.
>
> **Verification.** `python -m pytest` and `ruff check .` pass.
>
> **PR description checklist.**
> - Lists all new test files.
> - Notes any `xfail` markers and what production fix lifts them.
> - Confirms CI Postgres service is exercised by the new
>   compat-schema test.

---

### Brief: W1-alembic

> **Branch off `main`.** Read `docs/audit-001-initial.md` §4 items
> M1 and M2 first.
>
> **Goal.** Make Alembic migrations runnable on Railway. After this
> PR, `alembic upgrade head` works against the Railway Postgres URL
> and runs automatically on every deploy.
>
> **Tasks.**
> 1. **`alembic/env.py`** — at the top of the file, override
>    `config.set_main_option("sqlalchemy.url", ...)` from
>    `os.environ["DATABASE_URL"]` (with the same `postgresql://` →
>    `postgresql+asyncpg://` rewrite logic that
>    `backend/database.py:_database_url()` uses, but synchronous
>    psycopg2 / asyncpg URL — Alembic uses the sync driver by default,
>    so just `postgresql://`). If `DATABASE_URL` is unset, fall back
>    to the existing ini value.
> 2. **`alembic.ini`** — leave the SQLite URL as the dev default;
>    document in a comment that production overrides via env.
> 3. **`Dockerfile`** — before `CMD uvicorn ...`, run
>    `alembic upgrade head`. Use a small shell wrapper script (e.g.
>    `scripts/start.sh`) that does:
>    ```sh
>    #!/bin/sh
>    set -e
>    alembic upgrade head
>    exec uvicorn backend.main:app --host 0.0.0.0 --port "${PORT:-8000}"
>    ```
>    Make it executable; set `CMD ["./scripts/start.sh"]`.
> 4. **README** — add one paragraph under "Railway deployment"
>    explaining that migrations run on every deploy and how to write
>    a new one.
>
> **Important caveat.** The current Railway database may have been
> created via `create_all` with no `alembic_version` row. Alembic
> will refuse to `upgrade head` against an existing schema with no
> version. The PR must include a one-time fix: detect this case in
> `scripts/start.sh` (or a small Python helper) and stamp the DB to
> the current head before running `upgrade`. Pseudocode:
>
> ```sh
> if alembic current 2>&1 | grep -q "^$"; then
>   alembic stamp head
> fi
> alembic upgrade head
> ```
>
> Verify the stamp logic against a local Postgres (the new CI
> service container makes this easy).
>
> **Non-goals.** Do not write any new migrations. Do not remove
> `_ensure_compat_schema` — it stays as belt-and-suspenders. Do not
> touch any tests in `tests/test_database.py`.
>
> **Verification.** `alembic upgrade head` succeeds against a fresh
> Postgres AND against a Postgres pre-populated by `create_all`.
> `python -m pytest` and `ruff check .` pass.

---

### Brief: W1-config

> **Branch off `main`.** Read `docs/audit-001-initial.md` §4 items
> M6, M7, M9, M13 first.
>
> **Goal.** Tighten the small migration-debt items that don't need
> coordination with any other work.
>
> **Tasks.**
> 1. **`backend/config.py:115`** — change `sync_on_startup` default
>    from `True` to `False`. Update the field docstring/comment to
>    note that Railway should rely on the APScheduler interval job
>    only.
> 2. **`backend/routers/sync.py:123-154`** — dialect-guard the
>    `/api/sync/debug/db` endpoint. If `engine.dialect.name !=
>    "sqlite"`, return a 200 JSON `{"dialect": "...", "note":
>    "PRAGMA endpoint is sqlite-only"}` instead of running the
>    PRAGMA. Do not delete the endpoint.
> 3. **`backend/routers/sync.py:65`** — replace the `"Add credentials
>    to .env for unconfigured sources"` hint with `"Configure the
>    relevant service env vars (see README)"`.
> 4. **`.env.example:55-63`** — remove the duplicated
>    `TAILSCALE_HOSTNAME=` line.
> 5. **`backend/main.py` startup** — if running against Postgres and
>    `PUBLIC_BASE_URL` is unset, log a `WARNING` at startup. Do NOT
>    fail startup. One-liner using the existing logger.
>
> **Non-goals.** Do not change Eight Sleep, Strava, or Whoop code.
> Do not introduce new config keys. Do not refactor the sync router.
>
> **Verification.** `python -m pytest`, `ruff check .`. Add a small
> test for the dialect guard if straightforward; skip if it would
> require fixture surgery.
>
> **PR description checklist.**
> - Lists each of the five touchpoints.
> - Notes the `sync_on_startup` default flip prominently (behavior
>   change for local devs who didn't set the env var).

---

### Brief: W1-eightsleep-tokens

> **Branch off `main`.** Read `docs/audit-001-initial.md` §3 (Bug A
> hypothesis A1) and §4 (M3) first. This is the largest Wave 1
> task.
>
> **Goal.** Make Eight Sleep token persistence survive Railway
> container restarts by moving it to the `oauth_tokens` table,
> matching the Strava and Whoop pattern.
>
> **Current state.** `backend/clients/eight_sleep.py` writes tokens
> to a repo-root `.env` via `_persist_env_var`. Inside the Railway
> container, `.env` does not exist, so the writes silently no-op.
> `backend/services/oauth_tokens.py` already provides
> `save_tokens(provider, ...)` and `load_tokens(provider)` with a
> Postgres/SQLite dialect switch. Use it.
>
> **Tasks.**
> 1. **`backend/clients/eight_sleep.py`** — replace `.env`
>    persistence with `oauth_tokens` reads/writes. Specifically:
>    - On token load (currently `__init__` + `_ensure_token`), call
>      `await load_tokens("eight_sleep")` and seed in-memory state
>      from the DB. Fall back to env vars
>      (`EIGHT_SLEEP_REFRESH_TOKEN`, `EIGHT_SLEEP_USER_ID`) only on
>      first run when the DB row is absent.
>    - After every refresh that returns new tokens, call
>      `await save_tokens("eight_sleep", access_token=..., refresh_token=...,
>      expires_at=...)`. Store `user_id` in the `access_token`
>      field's metadata if convenient, OR add a second row keyed by
>      `provider="eight_sleep_user_id"` for clarity — pick one and
>      justify in the PR. (The `oauth_tokens` row schema has no
>      extras column, so a second-row pattern is simpler.)
>    - Remove all calls to `_persist_env_var` in this file. The
>      helper can remain in the module for now in case other code
>      uses it; check `backend/clients/strava.py` and `routers/auth.py`
>      — they reuse it. **Do not delete the helper.**
> 2. **Tests** — add `tests/test_clients/test_eight_sleep_tokens.py`
>    covering: cold start with env vars only writes a DB row; cold
>    start with DB row only ignores env vars; refresh rotates the DB
>    row; missing user_id triggers password grant. Use the existing
>    httpx mocking in `tests/test_clients/test_eight_sleep.py` as a
>    pattern.
> 3. **Backfill helper** — add a one-time script
>    `scripts/migrate_eight_sleep_tokens.py` that reads the relevant
>    env vars and writes them to `oauth_tokens`. Document in the PR
>    that the user should run this once after deploy.
>
> **Non-goals.** Do not touch Strava or Whoop clients. Do not change
> `services/oauth_tokens.py` schema. Do not write a database
> migration — the `oauth_tokens` table already exists. Do not modify
> the Eight Sleep sync engine (`services/eight_sleep_sync.py`).
>
> **Verification.** New tests pass on both SQLite (CI default) and
> Postgres (set `TEST_POSTGRES_URL` if you add a Postgres-specific
> case). `python -m pytest`, `ruff check .` pass.
>
> **PR description checklist.**
> - Explains the user-id-storage decision (second row vs. embed).
> - Notes the one-time `migrate_eight_sleep_tokens.py` step.
> - Confirms `_persist_env_var` was NOT removed.

---

### Brief: W1-deploy-cleanup

> **Branch off `main`.** Read `docs/audit-001-initial.md` §4 item M8
> first.
>
> **Goal.** Make it unambiguous that Railway is the source of truth
> and remove confusion from the leftover Mac-mini deploy artifacts.
>
> **Tasks.**
> 1. **Move `deploy/` → `deploy/legacy-mac-mini/`.** Add a
>    `deploy/legacy-mac-mini/DEPRECATED.md` explaining that this path
>    is unsupported and pointing readers at the Railway setup in the
>    README.
> 2. **README** — update any references to the Mac-mini deploy path
>    to note it is legacy. Keep one short paragraph stating the
>    Railway-only stance.
> 3. **`AGENTS.md`** — if it references the launchd path, replace
>    with the Railway link.
>
> **Non-goals.** Do not delete the launchd files outright (they are
> useful historical context). Do not modify any backend or frontend
> code. Do not touch `scripts/`.
>
> **Verification.** `python -m pytest` and `ruff check .` still
> pass (nothing should reference the old path; if anything does,
> fix it in this PR).
>
> Smallest of the Wave 1 PRs — should be < 100 lines of diff.

---

## Wave 2 — bug fixes (start AFTER Wave 0 lands)

Both briefs require `docs/audit-001-findings.md` to exist and be
committed. Each agent should refuse to start if it's absent.

### Brief: W2-bug-B

> **Branch off `main`.** Pre-flight: `docs/audit-001-findings.md`
> must exist. If it doesn't, stop and ask. Read
> `docs/audit-001-initial.md` §3 Bug B and `docs/audit-001-findings.md`
> "strength_sets schema" section.
>
> **Goal.** Make the lifting workout save succeed on Railway.
>
> **Branch by finding.**
>
> - **If findings.md shows `performed_at` MISSING:**
>   - Add a small Alembic migration that ALTERs `strength_sets` to
>     add the column (or rely on `_ensure_compat_schema` + a
>     redeploy if W1-alembic hasn't landed yet — document in the PR).
>   - Add an explicit ALTER step to the migration file, NOT just a
>     model change.
>   - Verify by running `scripts/diagnose_railway.py` against a
>     fresh deploy.
> - **If `performed_at` IS present:** the bug is elsewhere. Capture
>   the actual error from a reproduction: open the deployed app,
>   open devtools Network tab, log a set, hit Finish, paste the 500
>   response + Railway log stack trace into the PR description.
>   Then fix the root cause. Likely candidates from the audit: a
>   different missing column, a transaction commit issue, an FK
>   mismatch. The router test from W1-tests should now catch
>   regressions.
>
> **In either branch**, expand
> `tests/test_routers/test_strength.py` (added by W1-tests) with a
> regression test for the specific failure mode you fixed.
>
> **Non-goals.** Do not refactor `backend/routers/strength.py` for
> style. Do not change the frontend Record page. Do not touch other
> bugs in this PR.
>
> **Verification.** `python -m pytest`, `ruff check .` pass.
> Manually verify on Railway after deploy: log a set, hit Finish,
> confirm it lands in `/history`.

---

### Brief: W2-bug-A

> **Branch off `main`.** Pre-flight: `docs/audit-001-findings.md`
> must exist. If it doesn't, stop and ask. Read
> `docs/audit-001-initial.md` §3 Bug A and `docs/audit-001-findings.md`
> "oauth_tokens" and "sync_log" sections.
>
> **Goal.** Restore Strava / Eight Sleep / Whoop data refresh AND
> make future regressions visible.
>
> **Manual step (user does this, NOT the agent).** Re-run OAuth for
> Strava and Whoop from the Railway-hosted app:
> `https://<railway-host>/api/auth/strava` and `.../api/auth/whoop`.
> Confirm new rows in `oauth_tokens` via a second
> `diagnose_railway.py` run. The agent does NOT trigger OAuth.
>
> **Code-side tasks.**
> 1. **Surface real errors in `/api/sync/status`.** Currently
>    `backend/services/sync.py:56-60` catches per-source exceptions
>    and writes `f"error: {e}"` to a results dict that never reaches
>    `sync_log.error_message`. Change `sync_all` so that when a
>    per-source call raises, the matching `sync_log` row's
>    `status=error` and `error_message` are written. The simplest
>    approach: let each `sync_<source>` method's own `try/except`
>    record the error in `sync_log` (some already do this — verify
>    coverage), and remove the swallowing `try/except` in
>    `sync_all`. Lift the `xfail` marker added by W1-tests in
>    `tests/test_routers/test_sync.py`.
> 2. **`backend/clients/whoop.py` `_get` ordering** — swap the order
>    at `:271-272` so `await self._ensure_token()` runs BEFORE the
>    `is_enabled` check. This eliminates the "lazy DB load doesn't
>    happen because is_enabled returns False" race called out as
>    hypothesis A3. Add a unit test that constructs a `WhoopClient`
>    with `WHOOP_ENABLED=false` but a valid `oauth_tokens` row and
>    asserts `_get` proceeds.
> 3. **Documentation** — append a short "Re-OAuth on Railway"
>    section to README with the two URLs and the diagnostic command.
>
> **Non-goals.** Do not migrate Eight Sleep token storage (that's
> W1-eightsleep-tokens). Do not refactor the scheduler. Do not
> introduce webhooks.
>
> **Verification.** `python -m pytest`, `ruff check .`. After
> deploy, run `diagnose_railway.py` again; `sync_log` rows for the
> failing sources should show `error_message` populated; after the
> manual OAuth step, subsequent `sync_log` rows should show
> `status=success` and `records_synced > 0`.

---

## Headless-mode reminders

- **One PR per brief.** Do not let an agent combine briefs.
- **CI must pass before merge.** No `--no-verify`, no force-push.
- **Each brief lists explicit non-goals.** If an agent strays, push
  back with the brief link.
- **Wave 1 ordering:** W1-tests merges first; the other four rebase
  onto it so they pick up the Postgres CI service and the new
  fixture patterns.
- **Wave 0 cannot be done by an agent.** The Railway DB is not
  reachable from the headless container; the diagnostic script must
  be run from your laptop with `railway run`.
