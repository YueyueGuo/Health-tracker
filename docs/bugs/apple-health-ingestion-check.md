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
