# History Infinite Scroll

## 1. Feature summary
Replace the fixed 7d/30d/90d/1y time-range selector on the History page
with an infinite-scroll feed. The feed starts at the newest events and
loads progressively older events as the user scrolls toward the bottom,
all the way back through full history with no time window. The blended
timeline (Strava + Apple activities, sleep, and strength sessions)
continues loading together in correct newest-first date order, so a
strength session, a sleep night, and a run from the same week stay
interleaved correctly across page boundaries.

## 2. Affected surfaces
| surface | change | files |
|---------|--------|-------|
| `backend/services/` | new unified cursor-paginated feed merging activities + sleep + strength behind one cursor | `backend/services/history_feed.py` (new) |
| `backend/routers/dashboard.py` | new `GET /api/dashboard/history-feed` endpoint (keep `dashboard_history` as-is for back-compat) | `backend/routers/dashboard.py` (`dashboard_history` at line 92) |
| `frontend/src/api/dashboard.ts` | new `fetchHistoryFeed(cursor?, limit)` client + page/response types | `frontend/src/api/dashboard.ts` (after `fetchDashboardHistory`, line 136) |
| `frontend/src/pages/History.tsx` | remove time-range `<select>` (lines 69-79), add IntersectionObserver sentinel, append pages, dedupe, loading/end states | `frontend/src/pages/History.tsx` |
| `frontend/src/hooks/` | new `useInfiniteApi` hook wrapping TanStack `useInfiniteQuery` | `frontend/src/hooks/useInfiniteApi.ts` (new) |
| `frontend/src/lib/historyEvents.ts` | reuse `buildHistoryEvents` unchanged as the event-shaping source of truth | `frontend/src/lib/historyEvents.ts` (line 296) |
| `tests/test_services/` | pagination correctness tests | `tests/test_services/test_history_feed.py` (new) |
| `tests/test_routers/` | endpoint contract tests | `tests/test_routers/test_dashboard_history_feed.py` (new) |
| frontend tests | infinite-scroll append/dedupe/end-state | `frontend/src/pages/History.test.tsx` (new) |

No migration. No model changes. No new indexes (see section 7).

## 3. Data model
No schema changes. The three sources and their ordering keys:

- Activities: `list_activity_feed` (`backend/services/activity_feed.py:28`)
  returns dicts with `start_date` (ISO string; Strava `Activity.start_date`
  or Apple `HealthDataPoint.start_time`, both `DateTime(timezone=True)`),
  plus `id` and `source` (`"strava"` | `"apple_health"`).
- Sleep: `SleepSession` rows. Sort field for the timeline is the same one
  the client uses, `wake_time` (falling back to `date`T07:00:00`) per
  `sleepTimestamp` in `historyEvents.ts:144`. Carries `id`, `source`
  (`"eight_sleep"` | `"whoop"`), `date`.
- Strength: `list_sessions` (`backend/services/strength.py:56`) groups
  `StrengthSet` into one row per `date`; the client stamps each at
  `date`T12:00:00` (`historyEvents.ts:228`). Natural key is `date`.

Relationships are already handled client-side by `buildHistoryEvents`
(`historyEvents.ts:296`): strength rows linked to a Strava WeightTraining
activity dedup (strength wins, dropping the linked `activity_id`), and
sleep rows dedup by `date` (eight_sleep wins over whoop). The plan keeps
that logic on the client (see section 4 recommendation), so the backend
page must return the three typed arrays, not pre-merged events.

No backfill.

## 4. Backend feed design

### Endpoint contract (new endpoint, do not overload `dashboard_history`)
- Path: `GET /api/dashboard/history-feed`
- Query params:
  - `cursor: str | None` — opaque cursor; omit/empty for the first page.
  - `limit: int = 50` (`ge=1, le=100`) — number of merged timeline rows
    to return per page (counts post-merge events, see note below).
  - `include_superseded: bool = False` — passthrough to `list_activity_feed`.
- Response shape:
  ```
  {
    "activities": ActivitySummary[],   // only those in this page's window
    "sleep": SleepSession[],           // only those in this page's window
    "strength": StrengthSession[],     // only those in this page's window
    "next_cursor": string | null,      // null when has_more is false
    "has_more": boolean
  }
  ```
  Keep `dashboard_history` (line 92) untouched so the Trends page and any
  other consumer are unaffected.

### Recommendation: return the three typed arrays, not pre-merged events
`buildHistoryEvents` already encodes the cross-source dedup rules
(strength-vs-Strava link, sleep-by-date). Reproducing that server-side
would duplicate logic and risk drift. So the endpoint returns the three
arrays for the page window and the client keeps `buildHistoryEvents` as
the single source of truth for event shaping and merge.

### Cursor vs offset — recommend cursor
Use a keyset/cursor design, not offset. Offset re-scans and can drop or
duplicate rows if data is inserted during scroll (the scheduler syncs
new Strava/Eight Sleep/Whoop rows continuously — CLAUDE.md known issue #1
is literally about refresh). A cursor anchored on a timestamp is stable
against inserts at the head.

### The merge-behind-one-cursor problem (core of the design)
Three sources are independently ordered by their own date field. To page
them as one newest-first stream without dropping or duplicating rows at
boundaries:

1. Define a single comparable timeline key per row:
   `(timestamp_utc, source_rank, id)` where:
   - `timestamp_utc` = the row's sort instant, normalized to a tz-aware
     UTC datetime. Activities: `start_date`. Sleep: `wake_time` or
     `date`T07:00:00` localized. Strength: `date`T12:00:00`. Normalizing
     to UTC matters because `Activity.start_date` / `HealthDataPoint.start_time`
     are `timestamptz` and the recent `utc_now()` change made cutoffs
     tz-aware — open question Q1 covers the exact tz to localize the
     naive sleep/strength stamps into.
   - `source_rank` = deterministic small int per source family
     (e.g. activity=0, sleep=1, strength=2) to break ties on equal
     `timestamp_utc` across sources.
   - `id` = the row's own id (activity id, sleep id; strength uses the
     `date` ordinal since it has no integer id) to break ties within a
     source.
2. The cursor encodes the composite key of the LAST row emitted on the
   previous page: `base64("{iso_ts}|{source_rank}|{id}")`. Decode and
   page with strict "less than this key" (newest-first) semantics:
   a row is on the next page iff
   `(ts, rank, id) < (cursor_ts, cursor_rank, cursor_id)` lexicographically.
3. Implementation: over-fetch `limit + 1` candidates from EACH source
   constrained to `key <= cursor` (using `<=` on the timestamp at the SQL
   level, then applying the strict composite comparison in Python to
   exclude the exact cursor row and anything ordered after it). Merge the
   candidates with a sort-merge on the composite key (mirrors the existing
   Python merge in `activity_feed.py:109-112`), take the top `limit`,
   set `next_cursor` to the composite key of the last taken row, and
   `has_more = (more candidates remained beyond limit OR any source still
   had its over-fetch sentinel row)`.

This guarantees no gaps (each source is queried from the same cursor
anchor) and no duplicates (strict composite comparison excludes the
cursor row, and the composite key is globally unique). Ties on equal
timestamps across sources resolve deterministically via `source_rank`
then `id`.

### Services to reuse
- `list_activity_feed` (`activity_feed.py:28`) — already supports
  `cursor`/`limit`/`offset`-style over-fetch and the Apple dedup. The new
  service passes a per-page `cutoff` derived from the cursor timestamp and
  a `limit` of `limit + 1`. Open question Q2: confirm whether to thread a
  composite cursor into `list_activity_feed` itself or keep using its
  `cutoff` + post-filter in Python (recommend the latter to avoid touching
  the shared feed used by `/api/activities`).
- `SleepSession` query (pattern at `dashboard.py:113-118`) — add the
  cursor lower bound and `order_by(date.desc()).limit(limit+1)`.
- `list_sessions` (`strength.py:56`) — currently caps at `limit` with no
  cursor. Open question Q3: add an optional `before_date` param, or fetch
  with a generous limit and filter in Python. Recommend a small additive
  `before_date: date | None` param so deep scroll stays cheap.

### Open questions for integration-researcher / reviewer
- **Q1 (tz):** Which timezone should naive sleep/strength stamps localize
  into for the composite key? Eight Sleep stores bed/wake as naive local
  (per AGENTS.md). Recommend: treat sleep `wake_time` as the stored value
  localized via the app's configured local tz; strength `date`T12:00 in
  local tz. Must produce a tz-aware UTC instant for cross-source compare.
- **Q2:** Thread cursor into `list_activity_feed` vs. keep `cutoff` +
  Python post-filter. Recommend Python post-filter (no shared-API change).
- **Q3:** Add `before_date` to `list_sessions` vs. over-fetch + filter.
  Recommend `before_date` param (additive, keyset-friendly).
- **Q4:** Page-size semantics — count merged events (post-dedup) or raw
  rows? Recommend count the merged candidates taken (pre-client-dedup) so
  the cursor math stays on the backend's own keys; the client dedup only
  ever removes rows, so a page may render slightly fewer than `limit`
  cards — acceptable. Flag in section 6 caveat.
- **Q5:** Should `has_more=false` be derived per-source exhaustion or by
  the over-fetch sentinel? Recommend over-fetch sentinel across the merged
  candidate set.

## 5. Backend tasks
1. Create `backend/services/history_feed.py` with `list_history_feed(db, *,
   cursor: str | None, limit: int, include_superseded: bool)`:
   cursor encode/decode helper (composite key <-> base64), per-source
   windowed queries (reusing `list_activity_feed`, sleep query, `list_sessions`),
   sort-merge on `(timestamp_utc, source_rank, id)`, returns
   `{activities, sleep, strength, next_cursor, has_more}`.
2. Add a small `_timeline_key(row, source)` helper in the same module that
   normalizes each source's sort field to a tz-aware UTC datetime and the
   composite key (resolve Q1 here).
3. Add `before_date` optional param to `list_sessions` in
   `backend/services/strength.py:56` (additive; default None keeps
   current behavior) — only if Q3 resolves that way.
4. Add `GET /api/dashboard/history-feed` to `backend/routers/dashboard.py`
   delegating to `list_history_feed`. Leave `dashboard_history` (line 92)
   in place.

## 6. Frontend tasks
1. `frontend/src/hooks/useInfiniteApi.ts`: thin wrapper over TanStack
   `useInfiniteQuery` (same lib as `useApi`, `useApi.ts:2`) exposing
   `pages`, `fetchNextPage`, `hasNextPage`, `isFetchingNextPage`,
   `loading`, `error`. Reuse the retry/`refetchOnWindowFocus:false`
   config from `useApi`.
2. `frontend/src/api/dashboard.ts`: add `HistoryFeedPage` type
   (`{activities, sleep, strength, next_cursor, has_more}`) and
   `fetchHistoryFeed(cursor?: string, limit = 50)` calling
   `/dashboard/history-feed?...` (after line 136).
3. `frontend/src/pages/History.tsx`:
   - Remove the time-range `<select>` (lines 69-79) and the `days` state
     (lines 26, 28-31).
   - Use `useInfiniteApi` with `getNextPageParam: (last) => last.next_cursor`.
   - Flatten pages -> concat `activities`/`sleep`/`strength` across pages,
     then call `buildHistoryEvents(...)` once on the concatenated arrays
     (keeps existing sort + dedup; `historyEvents.ts:296`).
   - Dedupe the resulting events by `event.id` (ids are already
     source-namespaced, e.g. `strava-123`, `apple-123`, `sleep-5`,
     `strength-2026-05-30`, see `historyEvents.ts:209,224,258`) to guard
     against any boundary overlap.
   - Add an IntersectionObserver sentinel `<div>` after the list that
     calls `fetchNextPage()` when visible and `hasNextPage`.
   - States: initial `Loading history...`, inline `Loading more...` while
     `isFetchingNextPage`, `You're all caught up`-style end marker when
     `!hasNextPage`, and keep the existing empty-filter message.
   - Keep `activeFilter`/`activeType` client-side filters
     (`applyHistoryFilter`/`applyTypeFilter`) applied to the
     concatenated-then-merged list.
4. UX caveat to document in the PR/code comment: client-side filters
   (`activeFilter`/`activeType`) operate only on the rows loaded so far.
   With a filter active, the visible list reflects matches within loaded
   pages, not all history; the user keeps scrolling to load more matches.
   Recommend: when a filter is active and the filtered list is short but
   `hasNextPage`, auto-trigger the next page (or surface a "load more to
   see older matches" hint). Flag as open question Q6 (auto-load vs hint).

## 7. Migration tasks
None. No tables, columns, or indexes are added or altered.

The cursor ordering relies on columns that are already indexed:
`Activity.start_date` (index=True, `activity.py:37`),
`HealthDataPoint.start_time` (index=True, `health_data_point.py:64`),
`SleepSession.date` (index=True, `sleep.py:19`),
`StrengthSet.date` (index=True, `strength.py:49`). No new index needed.

Current Alembic head (verified `alembic heads`): `b6e9c4a7d51f`.
(Note: AGENTS.md line 51 lists `e1a3b7d2c9f4` — stale; the live head is
`b6e9c4a7d51f`.)

**Risk: trivial** (no migration in this plan at all).

## 8. Tests to add
- `tests/test_services/test_history_feed.py`:
  - Page boundary: no dropped and no duplicated rows when paging the full
    feed in chunks vs. one big fetch (assert set/order equality).
  - Tie handling: two rows from different sources with identical timestamp
    resolve deterministically by `source_rank` then `id`, and survive a
    page boundary placed exactly between them.
  - End of feed: last page returns `has_more=false`, `next_cursor=null`.
  - Cursor round-trip: encode/decode is stable; bad/empty cursor -> first page.
  - tz correctness: naive sleep/strength stamps order correctly relative
    to tz-aware activity timestamps (regression for the `utc_now()` change).
- `tests/test_routers/test_dashboard_history_feed.py`:
  - Contract: response keys, `limit` clamping, `include_superseded` passthrough.
  - Reuse fixtures/patterns from `tests/test_routers/test_dashboard_history_apple_merge.py`.
- `frontend/src/pages/History.test.tsx`:
  - Sentinel intersection triggers `fetchNextPage` and appends rows.
  - Dedupe: an event id appearing in two pages renders once.
  - End state shown when `has_more=false`; no further fetch fires.
  - Time-range `<select>` is gone (assert not in DOM).

## 9. Parallelism plan
```
phase 1 (sequential, decisions first):
  - plan reviewer / integration-researcher -> answers Q1-Q6 (tz, cursor
    threading, page-size semantics, filter-vs-pagination UX)

phase 2 (parallel, depends on phase 1):
  - backend-engineer   -> history_feed.py service + router + strength before_date
  - frontend-engineer  -> useInfiniteApi hook + api client + History.tsx rewrite

phase 3 (parallel, depends on phase 2):
  - test-runner (backend pytest: test_history_feed, test_dashboard_history_feed)
  - test-runner (frontend: History.test.tsx, npm run typecheck + build)

phase 4 (sequential):
  - code-reviewer
  - PR
```
No `migration-safety-checker` needed (Risk: trivial, no migration).

## 10. Risks and rollback
- Production risk is low: no migration, no schema change, no writes. The
  new endpoint is additive; existing `dashboard_history` is untouched, so
  the Trends page and any cached clients keep working.
- Highest functional risk is the merge/cursor correctness (dropped or
  duplicated rows at page boundaries) and tz normalization of naive
  sleep/strength stamps against tz-aware activity timestamps. Mitigated by
  the backend page-boundary and tie tests in section 8.
- Continuous scheduler inserts at the head of the feed during a scroll
  session are the reason for choosing cursor over offset; new rows appear
  only on a fresh first-page load, never as dup/gap mid-scroll.
- Rollback: revert the PR. Since the change is purely additive (new
  endpoint + frontend wiring), reverting `History.tsx` to the
  `fetchDashboardHistory` version and dropping the new endpoint fully
  restores prior behavior. No data migration to reverse.
