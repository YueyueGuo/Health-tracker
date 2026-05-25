# Apple Health workouts ingestion — did anything actually land?

**Status:** open investigation (kicked off after PR #46)
**Created:** 2026-05-25
**Trigger:** PR #46 unblocked the production schema; ingestion path can
finally write. Open question is whether it has — either before or after
the schema fix.

## Background — what just happened

- PR #42 (2026-05-2x) added Apple Health workouts ingestion via Health
  Auto Export (iOS app that POSTs HealthKit exports to a configurable
  webhook URL). It introduced new tables (`health_data_points`,
  `workouts`, `workout_laps`) and new columns on `activities`
  (`source`, `external_id`, `superseded_by_id`).
- PR #42's alembic migration never ran on Railway, so production was
  missing the columns. Any ingest POST that wrote to `activities`
  would have 500'd with `UndefinedColumnError`.
- PR #46 (merged 2026-05-24) landed the auto-apply fix and a manual
  patch repaired prod schema. Full detail in
  `docs/bugs/apple-health-prod-migration.md`.

So as of 2026-05-25 the schema is correct. **But we never confirmed
data is actually flowing.** That's this investigation.

## The question

Did Health Auto Export deliver any Apple Health workouts into
production — before the schema was applied (where POSTs would have
failed) or after (where they should now succeed)?

Secondary questions that follow from the answer:
- If nothing landed: where in the chain is it failing? HAE not
  configured? Webhook URL wrong? Endpoint not mounted? Payload shape
  mismatch?
- If something landed: do the rows show up on the History tab? Are
  Strava activities being correctly superseded per ADR 0002? Are
  there gaps relative to what's on the user's phone?

## Fastest discriminating check

Run against prod via psql (use the public Railway URL — same one used
in the migration fix):

```sql
SELECT count(*) FROM health_data_points;
SELECT count(*) FROM workouts;
SELECT count(*) FROM workout_laps;
SELECT source, count(*) FROM activities GROUP BY source;
SELECT min(start_date), max(start_date) FROM health_data_points;
```

Branches the investigation: zero rows vs non-zero. Don't pre-commit
to a fix path before knowing which.

## Likely starting points if you need to dig in

- **Ingest route** — find it under `backend/routers/` or
  `backend/api/`, probably named after Apple Health / Health Auto
  Export. Confirm it's mounted, externally reachable on Railway, and
  matches what HAE actually POSTs (HAE's payload shape is well
  documented on their site).
- **Railway logs window 2026-05-2x → 2026-05-24** — anything 5xx from
  the ingest path during that window is evidence HAE was reaching the
  endpoint but failing on the schema gap. If logs show no incoming
  hits at all, HAE may never have been pointed at prod.
- **HAE retry semantics** — if HAE retries failed exports, anything
  that queued during the broken window may flow through on the next
  HAE run. If it doesn't retry, there's a permanent gap.
- **Reference docs** — `docs/decisions/0002-apple-health-polymorphic-workouts.md`
  for the ingest + dedup model, `docs/plans/apple-health-workouts.md`
  for the original feature plan.

## What NOT to redo

- Prod schema is at `37d57cfdb27d`. No alembic / SQL action needed.
- `alembic/env.py` already honors `DATABASE_URL` (PR #46).
- Dockerfile already runs `alembic upgrade head` on boot (PR #46).
- `Base.metadata.create_all()` in `backend/main.py` lifespan is a
  known footgun (it's what silently created the new tables on prod
  while skipping the column adds, producing the partial state PR #46
  fixed). It's a deferred follow-up — leave it unless it bears
  directly on this investigation.

## Suggested kickoff for the new session

```
/bug Apple Health workouts ingestion may not have landed any rows in
production. PR #46 unblocked the schema on 2026-05-24; before that,
ingest POSTs would have 500'd. Full context in
docs/bugs/apple-health-ingestion-check.md — read that first. Start by
running the discriminating count queries to figure out whether we're
in the "zero rows" or "non-zero rows" branch, then proceed.
```

---

## Discriminating queries — result (2026-05-25)

Run against prod (`shinkansen.proxy.rlwy.net:43454`). Schema queries
succeeded, so the new tables/columns exist — prod is at PR #46 state.

```
health_data_points                = 0
workouts                          = 0
workout_laps                      = 0
activities by source              = strava: 1775   (no apple_health rows)
health_data_points min/max start  = NULL / NULL
activities WHERE superseded_by_id IS NOT NULL = 0
```

**Branch: zero rows.** Nothing has ever landed via the Apple Health
ingest route. The endpoint exists and the schema is correct, so this is
a reachability/auth/silent-failure issue, not a schema issue.

## Diagnosis (2026-05-25)

### Top 3 ranked hypotheses

#### 1. `APPLE_HEALTH_INGEST_TOKEN` is unset/blank in the Railway env — every POST returns 503 (most likely)

- **Evidence**: `backend/config.py:84-86` defines `AppleHealthSettings`
  with `ingest_token: str = ""` (no default, no required validator).
  `backend/routers/apple_health.py:39-46` raises `HTTPException(503)`
  whenever `settings.apple_health.ingest_token` is falsy, **before**
  the body is parsed or any DB write occurs. Every HAE POST against an
  unconfigured deploy 503s, leaving no DB rows.
- **Mechanism**: HAE fires its export, hits the webhook, gets 503,
  retries, never persists. No entrypoint log on the server
  (`apple_health.py` has zero `logger.info` calls at the route layer),
  so this failure mode is silent except for the middleware's generic
  `api.request status=503` line in `backend/main.py:106-114`.
- **How to confirm**:
  `curl -i -X POST https://<railway>/api/ingest/apple-health/workouts`
  with no header. 503 confirms; 401 falsifies.

#### 2. HAE was never pointed at prod (config-only, not a code bug)

- **Evidence**: PR #42 landed the endpoint ~2026-05-21. PR #46 fixed
  the schema on 2026-05-24. No HAE setup artifact (screenshot, deploy
  checklist) exists confirming the webhook URL was switched from the
  retired Mac mini.
- **Mechanism**: Endpoint wired, schema correct; the iOS app simply
  has the wrong URL.
- **How to confirm**: Search Railway access logs for any
  `POST /api/ingest/apple-health/*` since 2026-05-21. Zero hits ⇒ HAE
  never reached the box; non-zero with 5xx ⇒ hypothesis #1 or #3.

#### 3. Per-workout `try/except continue` masks a systematic failure; commit still fires with empty results

- **Evidence**: `backend/services/apple_health_ingest.py:69-105`. Every
  workout is wrapped in two `try/except Exception: continue` blocks
  (lines 70-84 parse, 86-100 upsert). `await db.commit()` at line 104
  runs unconditionally — even when every workout errored. A
  categorical failure produces a 200 OK with all-error results and
  zero rows committed. Evidence would only be per-workout
  `logger.exception` lines (line 89), which need log retention from
  the actual ingest window.
- **Notable suspect**: `apple_health_parser.py:123` returns a naive
  UTC datetime written into a `DateTime(timezone=True)` column
  (`health_data_point.py:63-66`). asyncpg accepts this today but it's
  a known footgun.
- **How to confirm**: After #1 is ruled out, fire one curl with the
  test fixture payload and inspect the JSON response — `status:
  "error"` with a populated `error` field on every entry is the
  smoking gun. Or grep Railway logs for `"failed to upsert"` /
  `"failed to parse"`.

### Recommended fix (Owner: backend)

Hypothesis #1 (and its config-side twin #2) is by far the most likely
cause. The single smallest **code** fix is an **observability** patch
so the next HAE POST is unambiguously diagnosable from Railway logs
alone, plus a startup warning so a blank token is loud at boot rather
than per-request.

Scope (one file): `backend/routers/apple_health.py`.

1. At module load, emit a one-shot WARNING when
   `settings.apple_health.ingest_token` is blank: "`apple_health
   ingest_token is blank — POSTs to /api/ingest/apple-health/* will
   503`". Makes hypothesis #1 a single grep at deploy time.
2. In `ingest_apple_health_workouts`, INFO-log before the call to
   `ingest_workouts`: workout count, first `external_id`, first start
   timestamp. Closes "is HAE actually reaching us?" without touching
   auth or schema.
3. After `ingest_workouts` returns, INFO-log the
   created/updated/error counts. Catches hypothesis #3 (200 OK with
   all-error results) without a per-workout log dive.

No migration. No env-var change. No behavior change to existing
clients — only added log lines.

### Regression test spec

File: `tests/test_routers/test_apple_health.py` (extend; the fixture
and client already exist).

1. `test_blank_token_warns_at_boot(monkeypatch, caplog)` — set
   `settings.apple_health.ingest_token = ""`, reload the router
   module, assert `caplog.records` contains a WARNING whose message
   mentions `ingest_token` and `503`.
2. `test_workouts_logs_batch_receipt_and_summary(client, caplog)` —
   with `caplog.at_level(logging.INFO,
   logger="backend.routers.apple_health")`, POST the happy-path
   payload (existing `_payload()` fixture), assert one INFO record
   contains `workouts=1` and one contains `created=1` (or equivalent
   summary token).

### Out of scope (follow-ups, not this PR)

- `health_data_point.py:28` imports `JSON` from
  `sqlalchemy.dialects.sqlite` (six other models do the same).
- `apple_health_parser.py:123` returns a naive UTC datetime stored
  into a `DateTime(timezone=True)` column.
- `backend/main.py:25` still calls `init_db()` /
  `Base.metadata.create_all` in lifespan despite PR #46's follow-up
  note to remove it.
- `apple_health_ingest.py:104` commits unconditionally after the
  per-workout loop — a "warn on all-error batch" gate would make
  hypothesis #3 self-diagnosing.
- No unauthenticated `/healthz`-style probe on the ingest path for
  HAE connectivity testing.

