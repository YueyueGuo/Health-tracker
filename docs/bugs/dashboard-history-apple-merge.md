# Bug Diagnosis: `/api/dashboard/history` ignores Apple Health workouts and surfaces superseded Strava rows

**Owner:** `backend-engineer`
**Severity:** medium (PR #42's user-facing claim is invisible on the History page; superseded duplicates appear)

---

## 1. Symptom

Both reproduced against `main` post-PR #42 by `qa-verifier`:

1. **Apple Health workouts never appear on the History page.** Ingestion is working (rows land in `health_data_points` + `workouts`) and `/api/activities` correctly merges them with source badges. The History page (`frontend/src/pages/History.tsx:25-28`) does **not** call `/api/activities`; it calls `/api/dashboard/history`, which queries only the Strava `activities` table. So the source badges shipped in PR #42 are invisible on the page the PR claims to have updated.
2. **`/api/dashboard/history` returns superseded Strava rows** — rows where `Activity.superseded_by_id IS NOT NULL` (i.e. Apple-won-dedup losers). The wrong canonical row surfaces.

**User actions that trigger it:** any visit to `/history` after Apple Health ingestion has run. QA screenshot: `/tmp/qa/screenshots/02_history.png` — two Strava badges, zero Apple badges, both for superseded rows.

## 2. Reproduction (read-only, API-level)

Against a local backend with at least one Apple+Strava dedup pair seeded (e.g. via the existing `_seed_strava` / `_seed_apple` helpers in `tests/test_routers/test_activities.py`):

```bash
# Expected after PR #42: superseded Strava row hidden, Apple workout present.
curl -s http://localhost:8000/api/activities | jq '[.[] | {id, source, superseded_by_id}]'

# Actual on the History page's endpoint: superseded Strava row IS returned,
# Apple workout is missing.
curl -s 'http://localhost:8000/api/dashboard/history?days=30' \
  | jq '[.activities[] | {id, source, superseded_by_id}]'
```

The second response contains the Strava loser (`superseded_by_id` set, `source: "strava"`) and zero `apple_health` rows. A regression test of this exact shape does not yet exist (`tests/test_routers/test_dashboard_today.py:144` only asserts the basic bundle shape and never seeds Apple data or a superseded Strava row).

## 3. Root cause

`backend/routers/dashboard.py:91-117`, `dashboard_history`:

```python
activities_result = await db.execute(
    select(Activity)
    .where(Activity.start_date >= cutoff)
    .order_by(Activity.start_date.desc())
    .limit(limit)
)
```

Two concrete defects vs. the canonical merge logic in `backend/routers/activities.py:60-144`:

- **No `superseded_by_id` filter.** Line 101's `where` clause does not include `Activity.superseded_by_id.is_(None)`. Compare against `activities.py:87-88`, which correctly applies it unless `include_superseded=True`. Result: Strava rows that Apple has already won dedup against still surface.
- **No Apple-workout merge.** There is no second query against `Workout`/`HealthDataPoint`, no Apple-only branch, no Apple-winner branch. The endpoint never emits `_apple_workout_summary` rows. Compare against `activities.py:100-139`, which runs the two-pass Apple query and merges results via Python sort.

The PR #42 plan flagged this exact risk in `docs/plans/apple-health-workouts.md:361` ("Existing dashboards / insights query `activities` directly and start showing only half the workouts after dedup hides superseded rows") and the implementation task list at line 285 named only `/api/activities` for the merge. `dashboard.py` was simply not updated.

## 4. Blast radius

Same bug, same file:

- **`/api/dashboard/training-trends`** (`backend/routers/dashboard.py:120-156`, lines 134-140): identical `select(Activity).where(Activity.start_date >= cutoff)` with no `superseded_by_id` filter and no Apple merge. The Trends page will under-count Apple workouts and double-count superseded Strava ones. **Yes, same bug.** Consumed by `frontend/src/api/dashboard.ts:163`.

Other dashboard endpoints in the same router are unaffected:
- `/overview` (line 75): delegates to `services/metrics.py`.
- `/today` (line 173): does not query `Activity` directly.

Internal callers that DO want the unfiltered set (MUST NOT change):
- `backend/services/sync.py:143, 227, 421` — Strava sync looks up its own rows by `strava_id` or enrichment status; intentionally needs all rows including superseded.
- `backend/scheduler.py` — same pattern (enrichment drain).

No frontend code besides `History.tsx` and the Trends page consumes these two endpoints.

## 5. Recommended fix

**Minimum-scope fix.** Extract the merge + supersede-filter logic from `activities.py` into a shared helper and have all three call sites use it:

- **New helper module:** `backend/services/activity_feed.py` (sibling to `workout_dedup.py`).
- **Public signature:**
  ```python
  async def list_activity_feed(
      db: AsyncSession,
      *,
      cutoff: datetime,
      limit: int,
      offset: int = 0,
      sport_type: str | None = None,
      include_superseded: bool = False,
  ) -> list[dict]:
      """Merged Strava + Apple feed shared by /api/activities, /api/dashboard/history,
      and /api/dashboard/training-trends. Returns rows already shaped as ActivitySummary."""
  ```
  Body is the verbatim Strava query + two Apple queries + Python sort/page that lives at `activities.py:80-144` today.

- **Call sites:**
  - `backend/routers/activities.py:list_activities` — thin wrapper, parses query params, calls helper.
  - `backend/routers/dashboard.py:dashboard_history` (replace lines 99-105).
  - `backend/routers/dashboard.py:dashboard_training_trends` (replace lines 134-140).

- **`include_superseded=true` opt-in on `/dashboard/history` and `/dashboard/training-trends`:** **yes, add it** for symmetry with `/api/activities` (default `False`). Required to write the third regression-test assertion below.

- **Frontend:** no changes. `frontend/src/api/dashboard.ts` types already accept the union shape because `ActivitySummary` already carries `source`/`external_id`/`superseded_by_id`.

- **Migration required:** **no.** Query-layer bug only.

## Regression tests

One file, new. Path: `tests/test_routers/test_dashboard_history_apple_merge.py`. Pattern after `test_activities.py` (reuse the `_seed_strava` / `_seed_apple` helper shape). Seed exactly one Apple+Strava dedup pair (Strava row's `superseded_by_id` set to the Apple HDP id, Apple `Workout.activity_id` set to the Strava row id) plus one Apple-only workout, then assert:

1. `GET /api/dashboard/history` → response `activities` includes the Apple-only workout AND the Apple winner of the deduped pair, both with `source == "apple_health"`.
2. `GET /api/dashboard/history` → response `activities` does **not** include any row whose `superseded_by_id` is non-null (i.e. the Strava loser is gone).
3. `GET /api/dashboard/history?include_superseded=true` → both rows of the deduped pair are present (Apple winner AND Strava loser), plus the Apple-only row.

Add a near-identical test for `/api/dashboard/training-trends` (its `activities` field has the same contract).

## 6. Out-of-scope cleanups spotted (do NOT include in fix PR)

- `backend/services/metrics.py:120-124` (`get_training_load`) and `:24-26` (`get_weekly_stats`) also do raw `select(Activity)` with no `superseded_by_id` filter. Once Apple Health workouts are populated, CTL/ATL/TSB and weekly volume will double-count the deduped workouts. Worth a separate ticket.
- `dashboard_history` and `dashboard_training_trends` don't apply `sport_type` filtering while `/api/activities` does. Probably intentional but worth confirming once the shared helper exists.
- After the fix lands, consider strengthening `test_dashboard_today.py:144` to assert `source` is present on every returned activity row.
