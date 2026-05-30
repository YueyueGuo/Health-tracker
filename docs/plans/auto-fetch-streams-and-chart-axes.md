# Plan: Auto-fetch HR streams during sync + fix chart axes

## 1. Feature summary

Two related improvements to the workout detail experience. **Feature 1**: During the Strava sync enrichment pass (Phase B), automatically fetch and persist per-sample stream data (heartrate, time, velocity_smooth, cadence, watts, altitude, distance, latlng) so that HR/pace curves are available instantly when the user opens a workout detail page -- eliminating the manual "Load Streams" button for newly synced activities. **Feature 2**: Fix the Analysis chart axes so (a) the pace Y-axis is inverted and formatted as `m:ss` per unit, (b) the HR Y-axis uses nice round tick intervals (e.g. 100, 120, 140, 160, 180), and (c) the X-axis (time in minutes) uses evenly spaced round intervals (every 5 or 10 minutes depending on total duration).

## 2. Affected surfaces

| Surface | Change | Files |
|---|---|---|
| `backend/services/sync.py` | Add stream fetch to `_strava_phase_b` after enrichment succeeds, gated on quota headroom | `backend/services/sync.py` |
| `backend/services/strava_streams.py` | Extract a `fetch_and_cache_streams` helper that `_strava_phase_b` can call directly (reusing the existing cache-miss path from `load_streams_for_activity`) | `backend/services/strava_streams.py` |
| `frontend/src/components/ActivityDetail.tsx` | Auto-load streams for Strava workouts when `streams_cached` is true (eager fetch, no button click needed) | `frontend/src/components/ActivityDetail.tsx` |
| `frontend/src/components/activity/AnalysisChart.tsx` | Fix X-axis tick intervals, HR Y-axis ticks, pace Y-axis inversion + `m:ss` tick formatting | `frontend/src/components/activity/AnalysisChart.tsx` |
| `frontend/src/components/activity/utils.ts` | Add `formatPaceTick` helper for Y-axis tick labels | `frontend/src/components/activity/utils.ts` |
| `tests/test_sync/test_strava_sync.py` | Add test that Phase B fetches streams | `tests/test_sync/test_strava_sync.py` |
| `tests/test_services/` | New test file for the refactored `strava_streams` helper | `tests/test_services/test_strava_streams.py` |

## 3. Data model

No new tables. No new columns. No migration needed.

The `activity_streams` table already exists (`backend/models/activity.py`, lines 130-141) with the exact schema needed:
- `id` (PK), `activity_id` (FK to `activities.id`, CASCADE), `stream_type` (String), `data` (JSON)
- UNIQUE constraint on `(activity_id, stream_type)`

Currently, rows are inserted only on first demand via `GET /api/activities/{id}/streams`. This plan changes the insertion point to also happen during Phase B enrichment, using the same model and the same `load_streams_for_activity` code path.

No backfill is needed for existing activities -- they will continue to use the on-demand lazy-fetch path when the user opens their detail page.

## 4. External integration (if any)

**Strava Streams API** -- `GET /activities/{id}/streams` (already integrated via `StravaClient.get_activity_streams`, line 381 of `backend/clients/strava.py`).

- **Auth method**: Same OAuth2 token as the existing Strava client.
- **Sync model**: Pull during Phase B enrichment (one extra API call per activity per enrichment pass).
- **Rate limits**: Each stream fetch costs 1 Strava read-API call. Phase B already fetches detail (1 call) + zones (1 call) per activity. Adding streams makes it 3 calls per activity. The existing quota-exhaustion check (`self.strava.quota_exhausted()`) at the top of the enrichment loop will automatically limit total throughput. However, the streams call should be wrapped in its own try/except so a stream-fetch failure (e.g. 429 hit on the third call) does not revert the successful detail+zones enrichment -- the activity should still be marked `complete` and streams can be lazy-fetched later.
- **Credentials**: Same as existing Strava integration (DB-persisted OAuth tokens).

**Open questions for `integration-researcher`**:
- What is the typical payload size of a Strava stream response for a 1-hour activity with all 8 stream types? (Estimate: 200-500 KB of JSON. Confirm this is acceptable for DB storage in the `data` JSON column.)
- Does the Strava streams endpoint ever return a 404 for activities that have a valid detail response? (e.g. manual uploads without GPS.) If so, document which stream types may be absent.
- For the rate-limit budget: with the enrichment drain running every 20 minutes, batch=40, and 3 API calls per activity (was 2), the worst-case 15-minute usage is 120 reads. The default read-15m limit is 100. Confirm whether the app has elevated limits and whether the `quota_exhausted` check at `fraction=0.95` is sufficient to prevent 429s, or whether we should lower the enrichment batch size to ~30.

## 5. Backend tasks

1. **Refactor `strava_streams.py`: extract `fetch_and_cache_streams`.** Split the existing `load_streams_for_activity` (lines 41-86) into two functions:
   - `load_streams_for_activity(db, activity)` -- unchanged public API, returns cached or lazy-fetched streams (used by `GET /api/activities/{id}/streams` endpoint and strength-link service).
   - `fetch_and_cache_streams(db, activity, strava_client)` -- accepts an existing `StravaClient` instance (avoiding constructing a new one per activity), fetches from Strava, caches to `activity_streams`, returns the streams dict. Called by Phase B and internally by `load_streams_for_activity` on cache miss. If `activity_streams` rows already exist for the activity, returns early (no Strava call).
   - File: `backend/services/strava_streams.py`

2. **Add stream fetch to `_strava_phase_b`.** After the successful `_apply_detail_to_activity` + zones + laps write block (around line 270 of `backend/services/sync.py`), call `fetch_and_cache_streams(db, activity, self.strava)`. Wrap in a try/except that:
   - On `StravaRateLimitError`: log a warning, skip streams for this activity but do NOT break the enrichment loop (the detail/zones enrichment is already done and should still be committed as `complete`).
   - On any other exception: log a warning, skip streams, continue.
   - File: `backend/services/sync.py` (inside `_strava_phase_b`, after line ~270)

3. **Update the scheduler batch size comment.** The enrichment drain in `backend/scheduler.py` (line 15, `batch=40`) should include a comment noting that each activity now costs 3 API reads (detail + zones + streams) instead of 2, so effective API usage per drain is up to 120 reads per 20-minute window. No code change required unless the researcher confirms limits are too tight, in which case lower to `batch=30`.
   - File: `backend/scheduler.py`

## 6. Frontend tasks

1. **Auto-load streams when cached.** In `frontend/src/components/ActivityDetail.tsx`, add a `useEffect` that calls `handleLoadStreams()` automatically when `activity.streams_cached === true` and `streams === null` and source is not `apple_health` (Apple Health already has eager loading at line 109-118). This eliminates the "Load Streams" button for any workout whose streams are already in the DB.
   - File: `frontend/src/components/ActivityDetail.tsx`
   - The "Load Streams" button in `AnalysisChart.tsx` remains as a fallback for older activities that were enriched before this feature shipped and whose streams have not yet been lazy-fetched.

2. **Fix X-axis tick intervals.** In `AnalysisChart.tsx`, add `tickCount` and a `tickFormatter` to the `<XAxis>`. Compute a nice interval based on the total duration: for activities under 30 minutes use 5-minute ticks, for 30-60 minutes use 10-minute ticks, for over 60 minutes use 15 or 20-minute ticks. Use Recharts' `ticks` prop with an explicit array of values (e.g. `[0, 5, 10, 15, 20, 25, 30]`) computed from `chartData[chartData.length - 1].time`.
   - File: `frontend/src/components/activity/AnalysisChart.tsx`

3. **Fix HR Y-axis tick intervals.** On the HR `<YAxis>` (yAxisId="right"), replace `domain={["dataMin - 10", "dataMax + 10"]}` with a computed domain that snaps to nice round numbers (e.g. floor to nearest 20 below dataMin, ceil to nearest 20 above dataMax). Add explicit `ticks` array with 20bpm spacing (e.g. `[100, 120, 140, 160, 180]`). Use a `useMemo` to compute the domain and ticks from the chartData HR values.
   - File: `frontend/src/components/activity/AnalysisChart.tsx`

4. **Fix Pace Y-axis: inversion + `m:ss` formatting.** The `reverseSecondary` flag is already set for run mode (line 113: `const reverseSecondary = mode === "run";`), and the `<YAxis yAxisId="left">` already accepts `reversed={reverseSecondary}` (line 206). The axis is correctly inverted. The remaining issues are:
   - The `domain` is set to `["auto", "auto"]` which lets Recharts auto-scale from 0, making the actual pace data look flat. Change `domain` to `["dataMin - 0.5", "dataMax + 0.5"]` (in decimal-minute space) so the Y-axis zooms to the data range.
   - Add a `tickFormatter` that converts decimal minutes to `m:ss` format (e.g. `7.5` -> `7:30`). Add a new `formatPaceTick(decimal: number): string` function to `utils.ts`.
   - Compute explicit `ticks` in 0.5-minute (30-second) increments within the data range for clean labels.
   - File: `frontend/src/components/activity/AnalysisChart.tsx`, `frontend/src/components/activity/utils.ts`

5. **Update Tooltip pace formatting.** The existing tooltip formatter (line 238-244) already converts decimal pace to `m:ss` format, but it uses the `secondaryUnit` which is `/mi` or `/km`. Verify this still works correctly after the axis changes. No change expected, but confirm.
   - File: `frontend/src/components/activity/AnalysisChart.tsx`

## 7. Migration tasks

**No migration needed.** The `activity_streams` table already exists with the correct schema. The feature only changes when rows are inserted (during sync instead of on-demand), not the table structure.

**Risk: trivial** -- No schema changes at all. Zero migration risk.

## 8. Tests to add

| File | Tests |
|---|---|
| `tests/test_services/test_strava_streams.py` (new) | Test `fetch_and_cache_streams`: (1) populates `activity_streams` rows on cache miss; (2) returns cached data on cache hit without calling Strava; (3) propagates `StravaRateLimitError` to caller; (4) handles empty stream response gracefully. |
| `tests/test_sync/test_strava_sync.py` (extend) | Test that `_strava_phase_b` calls stream fetch after enrichment. Test that stream-fetch failure (rate limit or generic error) does not prevent the activity from being marked `enrichment_status='complete'`. Test that stream-fetch failure does not break the enrichment loop (next activity still enriched). |
| `tests/test_services/test_scheduler_jobs.py` (extend, if applicable) | Verify the enrichment drain still works with the added stream step. |
| Frontend: no new test files | The chart axis changes are visual/formatting -- covered by manual QA and existing TypeScript type checks (`npm run typecheck`). The `formatPaceTick` utility should have a unit test if the project has frontend unit tests set up; check `frontend/src/components/activity/utils.test.ts`. |

## 9. Parallelism plan

```
phase 1 (parallel):
  - integration-researcher  -> answers open questions about Strava stream payload sizes, 404 behavior, rate-limit budget
  - (no migration needed)

phase 2 (parallel, depends on phase 1 for rate-limit answer):
  - backend-engineer        -> tasks 1-3: refactor strava_streams.py, update _strava_phase_b, update scheduler comment
  - frontend-engineer       -> tasks 1-5: auto-load streams, fix X-axis, fix HR Y-axis, fix pace Y-axis, verify tooltip

phase 3 (sequential, depends on phase 2):
  - test-runner             -> run full test suite (pytest + npm run typecheck + npm run build)
  - code-reviewer           -> review all changes
```

The backend and frontend work are fully independent -- no shared API contract changes. The backend adds rows to `activity_streams` during sync (same shape as today), and the frontend reads `streams_cached: true` (already in the API response, line 238 of `backend/routers/activities.py`). The frontend auto-load feature works with both old (lazy-fetched) and new (sync-fetched) cached streams.

## 10. Risks and rollback

**Production risks (Railway):**
- **Rate-limit budget increase**: Adding 1 API call per activity during enrichment increases per-activity cost from 2 to 3 calls. With batch=40, worst case is 120 reads per 20-minute drain window vs the default 100/15min read limit. If the app does NOT have elevated Strava limits, this could trigger 429s earlier. **Mitigation**: The existing `quota_exhausted()` check runs before each activity and will stop the loop. Worst case: fewer activities enriched per pass, but they will be picked up on the next drain cycle. If the researcher confirms tight limits, lower `batch` to 30.
- **DB storage growth**: Stream data is large JSON (hundreds of KB per activity). Over time this will grow the `activity_streams` table significantly. **Mitigation**: This is the existing behavior for any activity whose streams were ever loaded on-demand -- the table already has cached streams. The only change is that more activities will have cached data sooner. The `scripts/purge_streams.py` script exists for cleanup if needed.
- **No migration risk**: No schema changes.

**Frontend risks:**
- Chart axis changes are purely visual. If the tick computation produces unexpected values, the chart degrades to slightly-off labels but remains functional.
- The `reverseSecondary` flag is already working for pace inversion; this plan tightens the domain and formatting but does not change the inversion logic.

**Rollback plan:**
- Revert the PR. No migration to revert. Streams cached during the feature-active period remain in `activity_streams` (harmless; they would have been cached eventually via on-demand fetch anyway).
