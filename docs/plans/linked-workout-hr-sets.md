# Plan: Linked workout HR sets

## 1. Goal

Extend the strength session detail view so the project owner can manually link a single strength session to one device-recorded workout (Strava `activities` row or Apple Health `workouts` row) for the same block. Once linked, the backend auto-segments the workout's HR stream into N windows (N = logged set count), persists per-set `avg_hr` / `max_hr`, and renders a session-wide HR curve with segment boundaries. The link is strictly 1:1; the device workout cannot already be linked to another session. The history list shows a small HR-linked indicator on linked sessions. Whoop is not a v1 link target. No new external integrations.

The v1 per-set merge path becomes **segmentation-driven** (HR-stream peaks/valleys + set-count target) and **replaces** the timestamp-driven `_slice_hr_for_set` path in `backend/services/strength_hr.py`. The timestamp path is kept as a *fallback only* when every set has a `performed_at` AND segmentation returns zero usable segments. The session detail JSON shape grows a `link` block, a `segmentation` block, and per-set HR continues to be populated on the existing `sets` array. No new external API integrations.

## 2. Affected surfaces

| Surface | Change | Files |
|---|---|---|
| `backend/models/` | New `StrengthSessionLink` model. Optional session-level link header (`strength_session_links` table) keyed by `date`, with a generic `(source, ref_id)` target supporting both Strava `activities.id` and Apple Health `workouts.id` (joined-table inheritance over `health_data_points`). Drop reliance on per-row `strength_sets.activity_id` for v1 link target. | `backend/models/strength.py` (new `StrengthSessionLink`), `backend/models/__init__.py` |
| `backend/services/` | New segmentation algorithm; rewrite of `attach_hr_to_sets` to segmentation-first; new candidate-listing service; new on-demand stream-loader helper shared with the Strava lazy-stream path; new Apple-Health HR-summary loader. | `backend/services/strength_hr.py` (rewrite), `backend/services/strength_segmentation.py` (new), `backend/services/strength_link.py` (new), `backend/services/strength.py` (wire to link service) |
| `backend/routers/` | New `GET /strength/session/{date}/link-candidates`, `PUT /strength/session/{date}/link`, `DELETE /strength/session/{date}/link`, `POST /strength/session/{date}/resegment` (forces re-run if cached). Update `GET /strength/session/{date}` and `GET /strength/sessions` to read the link from `strength_session_links` and include a `hr_linked` boolean on session-list rows. | `backend/routers/strength.py` |
| `alembic/` | New revision adding `strength_session_links` (and indexes), plus a tiny backfill from existing non-null `strength_sets.activity_id`. | new revision off current head `c2f7a4e91b85` |
| `frontend/src/api/` | Add link/unlink/candidate fetchers and the new link block on `StrengthSessionDetail`. | `frontend/src/api/strength.ts` |
| `frontend/src/components/` | New `DeviceWorkoutPanel`, `LinkWorkoutPicker`, `SessionHRCurve` (session-wide curve with segment marker overlay), per-set HR columns, history-list HR-linked indicator. | `frontend/src/components/strength/DeviceWorkoutPanel.tsx`, `frontend/src/components/strength/LinkWorkoutPicker.tsx`, `frontend/src/components/strength/SessionHRCurve.tsx`, `frontend/src/components/strength/SessionDetailView.tsx` (host page extracted out of current History click target), `frontend/src/components/history/HistoryEventCard.tsx` (indicator), `frontend/src/components/activity/ExercisesTable.tsx` (avg/max HR columns) |
| Tests | New unit tests for segmentation, link router, candidate service, plus a frontend test for the picker and indicator. | `tests/test_services/test_strength_segmentation.py`, `tests/test_services/test_strength_link.py`, `tests/test_routers/test_strength.py` (extend), `tests/test_services/test_strength_hr.py` (rewrite for segmentation), `frontend/src/components/strength/DeviceWorkoutPanel.test.tsx`, `frontend/src/components/strength/LinkWorkoutPicker.test.tsx` |

## 3. Backend tasks

Ordered. Each is small enough for a single agent run.

1. **Add `StrengthSessionLink` model.** New table `strength_session_links` in `backend/models/strength.py` with columns: `id` (PK), `session_date` (Date, UNIQUE), `source` (`String(16)`, values `strava` | `apple_health`), `activity_id` (FK `activities.id`, nullable, `ON DELETE SET NULL`), `workout_id` (FK `workouts.id`, nullable, `ON DELETE SET NULL`), `segmentation_status` (`String(16)` — `pending|ok|too_few|too_many|flat|no_stream|error`), `segmentation_detected_count` (Int), `segmentation_target_count` (Int), `segmentation_payload` (JSON — `[{start_sec,end_sec,avg_hr,max_hr}, ...]`), `linked_at`, `updated_at`. UNIQUE on `(source, activity_id)` (partial via `WHERE activity_id IS NOT NULL`) and `(source, workout_id)` (partial via `WHERE workout_id IS NOT NULL`) to enforce 1:1 at the device-workout side. Register in `backend/models/__init__.py`.

2. **Add segmentation service.** `backend/services/strength_segmentation.py` exporting `segment_hr_stream(time_stream, hr_stream, target_count) -> SegmentationResult`. Algorithm v1 (concrete starting point):
   - Decimate to ~1Hz, drop zero/None.
   - Apply rolling-mean smoothing (window ~15s).
   - Detect peaks with `scipy.signal.find_peaks` (already in deps if present; otherwise pure-Python `argrelextrema`-style scan; planner to confirm — see Step 4 open questions) using a minimum prominence of `0.4 * (smoothed_max - smoothed_p20)` and a minimum distance of `max(20s, total_duration / (target_count * 3))`.
   - If detected peak count > `target_count`: keep the `target_count` highest-prominence peaks; if < `target_count`: keep what was found (the UI shows "auto-segmentation found N of M sets").
   - For each kept peak, define a window `[peak - 22s, peak + 8s]` clipped to neighbouring valley boundaries — captures the working-HR plateau where the user is mid-set, not the recovery dip.
   - Compute `avg_hr` / `max_hr` per window.
   - Confidence flags returned: `flat` (smoothed range < 15bpm), `noisy` (too many peaks survive prominence filter > 3 × target), `too_few`, `too_many`, `ok`.
   - Return `{status, segments, target_count, detected_count}`.
   Pure functions only — no DB.

3. **Rewrite `attach_hr_to_sets` in `backend/services/strength_hr.py`** to call segmentation. Drop the per-set timestamp dependency from the primary path. Map detected segments to logged sets in order (set 1 → segment 1, etc.). When `detected_count < target_count`, leave trailing sets with `avg_hr` / `max_hr` unset and surface the count mismatch via the return dict. When `detected_count > target_count`, drop the lowest-prominence extras (segmentation service already trims). Keep `_slice_hr_for_set` as a private fallback used only when (a) segmentation returns `flat` or `error` AND (b) every set has `performed_at` set — guard with a code comment that this is legacy behaviour, removed in v2.

4. **Add link/candidate service.** `backend/services/strength_link.py` with:
   - `list_candidates(db, session_date) -> list[dict]` — returns Strava `activities` rows + Apple Health `workouts` rows whose `start_date_local` (or `health_data_points.start_time` for Apple) falls in `[session_date - 1d, session_date + 1d]`, ordered by start time. Each row: `{source, ref_id, name, sport, start_local, duration_s, avg_hr, max_hr, distance_m, hr_stream_available}`. `hr_stream_available` is `True` for Strava if `activity_streams` for `heartrate` is cached OR `enrichment_status == "complete"` (lazy-fetchable); `False` for Apple unless `raw_payload` includes `heartRateData`.
   - `set_link(db, session_date, source, ref_id) -> StrengthSessionLink` — enforces 1:1 (raises 409 if the chosen device workout is already linked to another date). Triggers segmentation synchronously after fetching/loading streams. Persists `segmentation_payload`.
   - `clear_link(db, session_date)` — deletes the link row; the session falls back to the no-link UI on next load.
   - `ensure_streams_loaded(db, link) -> StreamLoadResult` — wraps the existing Strava on-demand stream fetch (factored out of `backend/routers/activities.py:get_activity_streams`) and the Apple `_maybe_apple_streams` helper. Returns `{time_stream, hr_stream, has_curve}` where `has_curve=False` for Apple workouts with summary-only HR.

5. **Refactor stream-fetch helper out of `activities.py`.** Pull the Strava lazy-fetch path from `backend/routers/activities.py:get_activity_streams` (lines ~327–379) into `backend/services/strava_streams.py` (or extend `backend/services/strength_link.py`) so `set_link` can reuse it without going via HTTP. Keep existing endpoint behaviour identical. This is the single point that calls `StravaClient.get_activity_streams` — preserve the 429 / rate-limit behaviour and the cache-write semantics.

6. **Wire link into `session_summary`.** Update `backend/services/strength.py:session_summary` to read the link from `strength_session_links` (instead of inferring from `strength_sets.activity_id`), call `attach_hr_to_sets` only when a link exists, and return:
   ```json
   {
     "date": "...",
     "sets": [...],
     "exercises": [...],
     "link": {
        "source": "strava" | "apple_health",
        "ref_id": 12345,
        "name": "Garage lift",
        "sport": "WeightTraining",
        "start_iso": "2026-05-25T17:30:00",
        "duration_s": 3600,
        "avg_hr": 132,
        "max_hr": 168
     } | null,
     "segmentation": {
        "status": "ok" | "too_few" | "too_many" | "flat" | "no_stream" | "no_curve" | "pending" | "error",
        "detected_count": N,
        "target_count": M
     } | null,
     "hr_curve": [[offset_sec, bpm], ...] | null,
     "segment_markers": [{set_number, start_sec, end_sec}, ...] | null,
     "activity_start_iso": "..."
   }
   ```
   Maintain backward-compat by also setting `activity_id` to the link's Strava `activity_id` when source is Strava (used by `frontend/src/components/activity/ActivityDetailStrength.tsx`).

7. **Add link endpoints to `backend/routers/strength.py`.**
   - `GET /strength/session/{session_date}/link-candidates` → list of candidate dicts from `list_candidates`.
   - `PUT /strength/session/{session_date}/link` body `{"source": "strava"|"apple_health", "ref_id": int}` → 200 with full updated session summary; 409 if conflict; 404 if no such session; 422 if candidate not found.
   - `DELETE /strength/session/{session_date}/link` → 204; session reloads to unlinked state.
   - `POST /strength/session/{session_date}/resegment` → recomputes segmentation against the currently linked workout; useful when streams arrived after first link attempt. Returns session summary.
   - Extend `GET /strength/sessions` to include `hr_linked: bool` per row (LEFT JOIN `strength_session_links` on `session_date`).

8. **Update bulk-insert path.** `POST /strength/sets` keeps accepting `activity_id` for backward-compat. When provided, write a `strength_session_links` row with `source="strava"` AND skip running segmentation inline (record stays `pending` until first `GET /session/{date}` fires the lazy resegment, to keep the POST cheap). Document this in the docstring.

9. **Logging + observability.** All segmentation runs log `(session_date, source, ref_id, status, detected_count, target_count)` at INFO. Stream-fetch failures during link log at WARNING with the exception class. Keep the existing scheduler untouched — linking is request-time only.

## 4. External integration

No new third-party API integrations are introduced. Existing integrations are touched only via the **lazy Strava streams** path:

- **Auth method**: existing Strava OAuth tokens (`backend/clients/strava.py`); no new credentials.
- **Sync model**: pull-on-demand. `set_link` for a Strava target invokes the same `StravaClient.get_activity_streams` flow used by `GET /activities/{id}/streams` today; cached results live in `activity_streams`.
- **Rate limits**: shared module-level quota state in `backend/clients/strava.py` — a 429 propagates as HTTP 502 from the link endpoint with a `detail` payload indicating the link row was still saved (status `no_stream`) and the user can retry via `POST /resegment`.
- **Apple Health**: no API — read existing rows in `workouts` / `health_data_points` only. When `raw_payload.heartRateData` is absent the link saves with `segmentation.status="no_curve"` and the UI degrades to summary-only.

### Open questions for the integration-researcher agent

These must be resolved **before** the segmentation service is finalized:

- **Algorithm — peak vs. valley framing.** Is "working HR plateau" better captured by anchoring on peaks (top of set) and walking ±N seconds, or on the valley-to-valley region between rests? The v1 starting point uses peaks; the researcher should confirm against 3–5 representative real sessions (look in the user's `activity_streams` table for `WeightTraining` rows).
- **`scipy.signal` availability.** Confirm whether `scipy` is already a transitive dep via `pyproject.toml` (it is *not* listed in `AGENTS.md` stack notes). If not, planner must choose between (a) adding `scipy` to deps (Railway image impact) or (b) a pure-Python peak detector. Recommendation: pure-Python first, since the streams are short (~3600 samples at 1Hz).
- **Set-count fidelity vs. honesty.** When detected count ≠ target count, should the algorithm aggressively merge/split to hit the target (better UX, lower fidelity) or report honestly (current plan)? Spec says honest reporting with tooltip — researcher to confirm with the owner if any sample sessions look misleading.
- **Apple Health `raw_payload` shape.** Confirm whether `heartRateData` time series is ever present for `WeightTraining`-type Apple workouts in this DB (`backend/routers/activities.py:_maybe_apple_streams` shows the parsing path exists; the question is whether the data is actually populated). If never present in practice, the Apple link UI degrades to summary-only **always**.
- **Smoothing window default.** 15s is a guess; researcher should verify against 2–3 real strength sessions.
- **Confidence threshold for "flat HR".** Current draft says "smoothed range < 15bpm" — verify against real data.

## 5. Frontend tasks

1. **Add types + fetchers in `frontend/src/api/strength.ts`.**
   - Extend `StrengthSessionDetail` with `link`, `segmentation`, `segment_markers`, and `hr_linked` on the session-list row.
   - Add `fetchLinkCandidates(date) -> Candidate[]`, `linkWorkout(date, {source, ref_id})`, `unlinkWorkout(date)`, `resegment(date)`.

2. **Promote strength session detail to a routable page.** Today the session detail is fetched ad-hoc by `ActivityDetailStrength` and `YesterdayActivityCard`. Add a real `/strength/session/:date` route in `frontend/src/App.tsx` (under `AppShell`), hosting a new component `frontend/src/components/strength/SessionDetailView.tsx`. History rows for strength sessions link into this route. Existing call sites keep working (they call the same API).

3. **`DeviceWorkoutPanel`.** Renders four states by inspecting `link` + `segmentation`:
   - Unlinked → `[Link device workout]` button.
   - Linking / loading → spinner with "Loading heart-rate stream…".
   - Linked + curve OK → source badge, name, start time, duration, avg/max HR, plus `[Change]` / `[Unlink]`.
   - Linked + error/degraded → summary plus an explicit message (`"Apple Health workout has no HR time series"`, `"Strava stream not available yet"`, `"Couldn't detect set boundaries from HR"`) and a `[Retry]` that calls `resegment`.

4. **`LinkWorkoutPicker`.** Modal/sheet driven by `fetchLinkCandidates`. Each row: source badge (Strava/Apple Health), sport, local start time, duration (hh:mm), avg HR, max HR, distance (if relevant). Empty state explains "no device workouts found within ±1 day of this session". Tap a row → confirm → `linkWorkout` → close → parent reloads session summary.

5. **`SessionHRCurve`.** Recharts line chart over `hr_curve` (x = offset_sec, y = bpm). Overlay `segment_markers` as shaded vertical bands (one per detected set) with the set number labelled. Hidden when `hr_curve` is null. When `segmentation.status === "no_curve"`, render a summary-only banner instead.

6. **Per-set HR columns in the exercises table.** Update `frontend/src/components/activity/ExercisesTable.tsx` (or a new `frontend/src/components/strength/ExerciseSetsTable.tsx` if the activity-side table needs to stay narrow) to render `Avg HR` and `Max HR` columns. Sets missing HR render `—` with a tooltip: `"auto-segmentation found N of M sets"` (from `segmentation`).

7. **History list HR-linked indicator.** In `frontend/src/components/history/HistoryEventCard.tsx`, when the event is a strength session and `hr_linked === true`, show a small heart icon next to the title.

8. **Wire `ActivityDetailStrength` to the new shape.** Keep current behavior but read per-set HR from the new `link`-driven payload — no UI change required since today's code already reads `avg_hr` / `max_hr` per set off `session.exercises[].sets[]`.

9. **Error and loading states.** A failed `linkWorkout` (e.g. 502 from stream fetch) shows an inline error in the panel and does **not** roll back the link (the row is saved with `segmentation.status="no_stream"`); a `[Retry]` button calls `resegment`.

## 6. Tests

By file:

- `tests/test_services/test_strength_segmentation.py` (new) — pure-function tests:
  - Synthetic HR trace with 5 clean peaks → 5 segments returned, set counts match.
  - Same trace with `target_count=3` → keeps 3 highest-prominence peaks.
  - Flat HR trace (range < 15bpm) → returns `status="flat"`, zero segments.
  - Noisy trace with 30 micro-peaks → prominence filter rejects all, returns honest detected_count.
  - Mismatched stream lengths → service tolerates and slices.
- `tests/test_services/test_strength_hr.py` (rewrite) — drop most of the timestamp-window tests; replace with segmentation-driven tests using the new service. Keep `_slice_hr_for_set` tests under a `_legacy_fallback` group.
- `tests/test_services/test_strength_link.py` (new) — `list_candidates` returns both Strava and Apple Health, ±1 day window honored; `set_link` enforces 1:1 (raises on duplicate device workout); `clear_link` removes row; `ensure_streams_loaded` returns `has_curve=False` for an Apple workout with no `heartRateData`.
- `tests/test_routers/test_strength.py` (extend) — new endpoint coverage:
  - `GET /strength/session/{date}/link-candidates` happy path + empty case.
  - `PUT /strength/session/{date}/link` Strava with cached streams → 200 with `segmentation.status=="ok"`.
  - `PUT` Strava with no cached streams → triggers fetch (mocked `StravaClient`) → 200.
  - `PUT` Apple Health workout without HR series → 200, `segmentation.status=="no_curve"`.
  - `PUT` against an already-linked device workout → 409.
  - `DELETE` → 204; subsequent `GET /strength/session/{date}` has `link=null`.
  - `POST /strength/session/{date}/resegment` recomputes when streams change.
  - `GET /strength/sessions` includes `hr_linked` boolean.
- `frontend/src/components/strength/DeviceWorkoutPanel.test.tsx` (new) — renders each of the four states from props.
- `frontend/src/components/strength/LinkWorkoutPicker.test.tsx` (new) — fetches candidates, renders both source badges, empty state, click triggers `linkWorkout`.
- `frontend/src/components/history/HistoryEventCard.test.tsx` (extend) — renders the HR-linked indicator when `hr_linked: true`.

## 7. Migration tasks

- **Revision name**: `add_strength_session_links` (file: `alembic/versions/<rev>_add_strength_session_links.py`).
- **Parent revision**: `c2f7a4e91b85` (current head per `AGENTS.md`; verify with `alembic heads` before authoring).
- **Operations** (SQLite-safe — use `op.create_table` + `op.add_column`, **no `batch_alter_table`** per AGENTS.md):
  - `op.create_table('strength_session_links', ...)` with columns listed in Backend task 1.
  - `op.create_index('ix_strength_session_links_session_date', ...)` UNIQUE on `session_date`.
  - `op.create_index('ix_strength_session_links_source_activity', 'strength_session_links', ['source', 'activity_id'], unique=True, sqlite_where=sa.text('activity_id IS NOT NULL'), postgresql_where=sa.text('activity_id IS NOT NULL'))`.
  - Same idea for `(source, workout_id)`.
  - Backfill: `INSERT INTO strength_session_links (session_date, source, activity_id, segmentation_status, linked_at, updated_at) SELECT date, 'strava', activity_id, 'pending', NOW(), NOW() FROM strength_sets WHERE activity_id IS NOT NULL GROUP BY date, activity_id;` — uses one row per distinct `(date, activity_id)`; existing data has 1 activity per date by convention so this is safe. Use `op.execute` with dialect-aware `NOW()` vs `CURRENT_TIMESTAMP`.
- **Downgrade**: drop indexes, drop table. Backfilled data is reconstructible from `strength_sets.activity_id` so loss is acceptable.
- **No changes to `strength_sets`** — `activity_id` stays for back-compat and for the existing POST `/strength/sets` payload shape. v2 may drop it after a deprecation cycle.

## Parallelism plan

```
Phase 1 (parallel):
  - integration-researcher → answer the five open questions in Step 4
                              (algorithm, scipy availability, fidelity,
                              Apple HR series, smoothing/flat thresholds);
                              produces a short note that the backend
                              engineer uses to finalize the segmentation
                              algorithm.
  - db-migrator             → write the Alembic revision per Step 7.

Phase 2 (parallel, depends on Phase 1):
  - backend-engineer        → Steps 1–9 in Backend tasks. Splits cleanly
                              into two sub-batches if needed:
                                  (2a) models + segmentation service + tests
                                  (2b) link service + router + session_summary wire-up
                              (2b) depends on (2a).
  - frontend-engineer       → Steps 1–9 in Frontend tasks. Can start on
                              the API client + DeviceWorkoutPanel stubs
                              against a mocked payload while (2b) lands.

Phase 3 (sequential):
  - test-runner             → `ruff check .`, `python -m pytest`,
                              `cd frontend && npm run typecheck && npm run build`.
  - code-reviewer           → reviews backend + frontend diffs together.
```

## Risks and rollback

- **Production blast radius (Railway).** New `strength_session_links` table is additive; the only schema risk is the partial-unique-index syntax, which differs between SQLite and Postgres. Migration writer must use dialect branches (sqlite vs postgresql `where=`) and run the migration locally against both `health_tracker.db` and a Railway-style Postgres before merging.
- **`session_summary` payload shape change.** Existing frontend call sites (`ActivityDetailStrength`, `YesterdayActivityCard`) read `session.activity_id` and `session.exercises[].sets[].avg_hr` — both are preserved. Other consumers should be greenlit by `grep -r "fetchStrengthSessionOptional\|session_summary" frontend/`.
- **Lazy Strava stream fetch in a request path.** `PUT /strength/session/{date}/link` can now block on a Strava call. Risk: long-tail latency, 429s mid-request. Mitigation: the endpoint always persists the link row first, then attempts segmentation; on stream failure it returns the link with `segmentation.status="no_stream"` and the UI's `[Retry]` triggers `resegment`. Honour the existing `StravaClient` 429 propagation.
- **Segmentation false positives.** A user could link the wrong workout and see misleading per-set HR. Mitigated by (a) honest count-mismatch reporting in the UI, (b) `[Unlink]` is one tap, (c) segment markers visible on the curve so the user can sanity-check.
- **Whoop / future sources.** The `(source, activity_id, workout_id)` schema is awkward if a third source appears. v2 should migrate to a single polymorphic `(source, ref_id)` column, but for v1 the two-FK shape lets us keep `ON DELETE SET NULL` cascades free.
- **Rollback plan.**
  - *Code*: revert the PR. The link table sits idle; no other code reads it.
  - *Migration*: `alembic downgrade -1` drops the table cleanly. Existing `strength_sets.activity_id` is untouched, so the timestamp-driven HR merge resumes working for sessions logged with per-set `performed_at`.
  - *Partial rollback*: if segmentation regresses but linking is fine, the segmentation algorithm lives behind a single import — swap `strength_segmentation.segment_hr_stream` for a stub that always returns `status="flat"` and the UI falls back to summary-only with link preserved.
