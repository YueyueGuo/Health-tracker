# Bug Diagnosis: History page shows no activities after April 2026

## Symptom
On the dashboard History page, no activities appear after April of the
current year (2026), even though Postgres holds 1776 activities including
ones dated May. The data exists in the DB but is filtered/sorted out of the
API response. The newest activities (late April → May 30) never reach the UI.

## Failing path
`frontend/src/pages/History.tsx:26-31` calls `fetchDashboardHistory(days, 200)`
with `days` defaulting to 30 → `GET /api/dashboard/history?days=30&limit=200`
→ `backend/routers/dashboard.py:92` → `list_activity_feed` in
`backend/services/activity_feed.py:28`.

## Root cause (Hypothesis 1 — most likely)
Naive cutoff compared against a `timestamptz` column.

- `backend/routers/dashboard.py:106` builds
  `cutoff = utc_now_naive() - timedelta(days=days)`. `utc_now_naive()`
  (`backend/services/time_utils.py:18-20`) returns a **naive** datetime.
- That cutoff flows into `backend/services/activity_feed.py:52` as
  `query.where(Activity.start_date >= cutoff)`.
- `Activity.start_date` is declared `DateTime(timezone=True)`
  (`backend/models/activity.py:36-38`) and is written **tz-aware** with a
  real `+00:00` offset in `backend/services/sync.py:164-166`. On Postgres
  this column is `timestamptz`.
- asyncpg sends the naive Python `cutoff` as a `timestamp` (no zone).
  Postgres coerces it to `timestamptz` using the session `TimeZone` setting,
  and no explicit timezone is configured on the engine
  (`backend/database.py:40-44`). If the Railway session TZ is not UTC, the
  comparison boundary shifts by the offset, systematically dropping the
  newest rows → "everything after a date disappears."

The codebase already knows this hazard: `backend/services/workout_snapshot.py:46-58`
defines `_to_naive_utc()` to normalize before comparing — but
`list_activity_feed` never applies it.

The existing test suite runs on **SQLite**, which stores datetimes as strings
and ignores tz, silently masking the bug. That SQLite-vs-Postgres gap is why
this shipped (rushed Railway migration).

## Secondary findings (not the primary cause)
- `dashboard.py:115` filters sleep with `local_today()` (server-local) while
  activities use `utc_now_naive()` — mixed reference points; affects sleep
  rows only.
- `activity_feed.py:115` merges Strava+Apple by **ISO-string** sort, fragile
  when offset suffixes differ.

## Recommended fix (minimal scope)
Make the cutoff timezone-aware UTC so it compares cleanly against the
`timestamptz` column:
- `backend/routers/dashboard.py:106` (history) and `:147`
  (`dashboard_training_trends`), and `backend/routers/activities.py:101`
  (`list_activities`): use `utc_now()` (tz-aware) instead of `utc_now_naive()`.
- Defense-in-depth: pin the asyncpg engine session to UTC via
  `connect_args={"server_settings": {"timezone": "UTC"}}` in
  `backend/database.py`.

No migration required — query-time comparison bug, not schema/data.

## Regression test
In `tests/test_routers/test_dashboard_history_apple_merge.py`, add an
aware-seed variant: seed a Strava `Activity` with a **tz-aware** `start_date`
at "now" (UTC), then assert `GET /api/dashboard/history?days=30` includes that
row and returns newest-first. The existing `_seed_strava` helper uses naive
`utc_now_naive()`, which is exactly what hides the bug.
