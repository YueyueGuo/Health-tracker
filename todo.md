# Backlog

The authoritative list of known remaining work. Curated — anything
captured elsewhere as a `# TODO` in code should bubble up here if it's
actually worth doing.

Last updated: 2026-04-22 (end of strength-live-mode + HR ship).

---

## Bugs / cleanup

### Pre-existing test failures (UTC vs local day boundary)
`tests/test_services/test_training_metrics.py` has 3 failing tests:
- `test_training_load_with_activities`
- `test_training_load_monotony_zero_stdev`
- `test_full_snapshot_assembles_all_sections`

Root cause: `_make_activity` uses `datetime.utcnow()` as the activity's
`start_date`, but `get_training_load_snapshot` compares against
`date.today()` (local). Across the UTC/local-midnight boundary, today's
activity falls into "yesterday" and the 7-day acute window drops it.

**Fix:** in `tests/test_services/test_training_metrics.py::_make_activity`,
replace `datetime.utcnow()` with `datetime.now()` (or pass a
tz-aware datetime). Verify all three tests pass, then consider fixing the
same `utcnow()` pattern in `test_insights.py` and `test_scheduler_jobs.py`
(they'll fail the same way if run at the wrong hour).

### Alembic vs live DB drift
Strength-live-mode migration `b3c6d9e8a1f4` was applied via direct SQL
(`ALTER TABLE strength_sets ADD COLUMN performed_at DATETIME`) because
the live DB is on a revision from another branch not present in this
worktree. When the branches reconcile, run `alembic stamp head` or
`alembic upgrade head` to bring the DB in sync with the migration
chain.

### Branch reconciliation
No `main` branch exists. `yy/dashboard-insights-and-sleep-fixes` (main
worktree) and `claude/interesting-archimedes-16548a` (strength work)
have diverged. Open PRs and merge on GitHub; pick one as trunk going
forward or set `origin/HEAD` accordingly.

---

## Strength training

### Delete/edit strength sets in the UI
Backend has `PATCH /strength/sets/{id}` and `DELETE /strength/sets/{id}`.
Frontend (`Strength.tsx`) shows sets read-only. Add inline edit +
delete affordances to the session-detail exercise tables. Stale HR
cached values after a `performed_at` edit — regenerate from the linked
activity (or just drop the stale pill and rely on the curve).

### Strength classification + progression surfacing
`Strength.tsx` shows a list + progression chart. Surface week-over-week
volume deltas and flag PRs (new max weight or new est_1rm) on the
dashboard, similar to the weekly-summary strip.

### `has_weight_training` / flags on linked activities
When a strength session is linked to a Strava WeightTraining activity,
set a flag on the activity row so the Dashboard can show "3 sets squat,
4 sets bench" alongside the usual summary. Today the link is one-way.

### Retroactive HR backfill for linked sessions
If the user retroactively links an activity to an existing strength
session (currently not a flow, but we should add it), `attach_hr_to_sets`
should run on the next `session_summary` call. No new code needed — just
verify the path works when coming from the UI.

---

## From the April work stream (carry-over)

### Elevation — Phase 2 follow-up
Backfill Phase 2 was deliberately skipped. Once a default `UserLocation`
is set via `/settings`, re-run `python scripts/backfill_elevation.py` to
resolve the 62 indoor activities + 180 pending-Strava rows.

### Phone-location PWA
Schema (`user_locations`, `location_id` on activities) is ready. Add:
- `navigator.geolocation` pinging from the PWA
- `POST /api/location/ping` → `location_pings` table
- Nightly timestamp-join to activities missing coords
See the elevation plan doc in Warp Drive.

### `/api/correlations/altitude-vs-effort`
Dedicated endpoint pairing `base_elevation_m` against HR / suffer_score
/ pace for same-sport activities. Low priority — the existing
sleep-vs-activity matrix already surfaces the signal.

### Classifier tuning
Distribution looks sensible after the `max_pace_zone ≥ 3` gate. Revisit
if specific sport mixes look off.

### Read rate limit header
`StravaClient` doesn't parse `X-ReadRateLimit-Usage` separately — Strava
has a distinct read limit (100/15min) that can hit before the overall
counter reaches 95% of 200. Cheap fix to stop *before* 429'ing.

### `/api/summary/weekly` UI filter
Clicking a weekly-summary card doesn't filter the activity list yet.
Obvious follow-up.

### Strava HTTP-level client coverage
Classifier / weekly-summary / SyncEngine phase A+B are all covered.
Remaining gap: full HTTP-level tests of `StravaClient` OAuth / refresh /
pagination (header parsing is already tested).

---

## Nice-to-haves

### Eight Sleep — HR/HRV visualization
Data is in `raw_data.interval.timeseries` for recent nights. No UI yet.
Add a per-night HR/HRV overlay on `/sleep` similar to the stacked-stages
bar chart.

### LLM insights — richer context
Now that `hr_zones`, `hr_drift`, and per-lap `hr_zone` are wired in,
smoke-test the daily recommendation and workout insight endpoints
against a few real activities and refine the prompts based on what the
model actually says.

### Frontend bundle size
Production build warns at 693 KB. Code-split routes — `/strength`,
`/sleep`, `/recovery`, `/training`, `/settings` are all standalone
pages.
