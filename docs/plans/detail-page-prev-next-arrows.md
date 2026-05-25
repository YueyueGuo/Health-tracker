# Plan: Prev/Next navigation arrows on Sleep & Recovery and Workout detail pages

## 1. Feature summary
Give the user prev/next chevron arrows at the top of the **Sleep & Recovery** detail page (`/sleep`) and the **Workout** detail pages (`/activities/:id`, `/workouts/lifting/:date`) so they can step backward and forward through historical records without bouncing back to History. The arrows mirror the look and behavior of the home-page `Header` chevrons (`frontend/src/components/dashboard/Header.tsx`). Because sleep/workout data is sparse (not every day has a record), each arrow **jumps to the nearest neighbor that has actual data** and is disabled when no such neighbor exists.

## 2. Affected surfaces

| surface | change | files |
|---|---|---|
| `frontend/src/components/sleep/` | Add chevrons + neighbor-aware navigation to existing in-page header | `frontend/src/components/sleep/SleepRecoveryDetailsCard.tsx` |
| `frontend/src/components/activity/` | Add chevrons + neighbor-aware navigation to Strava + Apple workout detail header | `frontend/src/components/activity/ActivityHeader.tsx` |
| `frontend/src/pages/` | Add chevrons + neighbor-aware navigation to lifting detail header | `frontend/src/pages/LiftingDetail.tsx` |
| `frontend/src/components/ui/` (new, small) | Shared `DetailNavArrows` (left/right pair, matches home `Header` styling) | new: `frontend/src/components/ui/DetailNavArrows.tsx` |
| `frontend/src/hooks/` (new) | Hook(s) that compute prev/next neighbor: `useSleepNeighbors`, `useActivityNeighbors`, `useLiftingNeighbors` (or one generic `useDetailNeighbors`) | new: `frontend/src/hooks/useDetailNeighbors.ts` |
| `frontend/src/api/` | Either reuse existing list endpoints (preferred — see Section 4) or add small neighbor fetchers | `frontend/src/api/sleep.ts`, `frontend/src/api/activities.ts`, `frontend/src/api/strength.ts` |
| `backend/routers/` (only if Section 4 picks server-side) | New small `/neighbors` helper endpoints | `backend/routers/sleep.py`, `backend/routers/activities.py`, `backend/routers/strength.py` |
| `tests/` | Unit tests for hook(s) + render tests for header arrow states | `frontend/src/components/sleep/SleepRecoveryDetailsCard.test.tsx`, `frontend/src/pages/LiftingDetail.test.tsx`, `frontend/src/components/ActivityDetail.test.tsx`, new `frontend/src/hooks/useDetailNeighbors.test.ts`; backend tests only if endpoints are added |
| `alembic/` | None | — |

## 3. Data model
No schema changes. All data needed (dates / ids of existing sleep sessions, strength sessions, and activities) is already exposed by current endpoints.

- `SleepSession.date` (`backend/models/...`, exposed at `GET /sleep`, `GET /sleep/latest?on_or_before=`)
- `Activity.start_date_local` + Apple `Workout` (exposed at `GET /activities` via `list_activity_feed` — `backend/routers/activities.py:58`)
- `StrengthSession.date` (exposed at `GET /strength/sessions?limit=` — `backend/routers/strength.py:128`)

No backfill needed.

## 4. External integration
**None.** No third-party API, OAuth, or sync work in scope. Mark this section as `N/A` for the orchestrator (no `integration-researcher` agent needed in phase 1).

### Resolved open questions

1. **Client-side vs server-side neighbor lookup?** **Recommendation: client-side**, reusing existing list endpoints, mirroring how the home page already works.
   - Home page uses a single source of truth date (`HomeLayout.selectedDate`) and refetches `fetchDashboardToday(dateStr)` per change — it does **not** call a "neighbor" endpoint. The chevrons in `Header.tsx:41-45` simply do `addDays(selectedDate, ±1)`. Sparse-aware neighbor logic does not exist on home because home has data every day.
   - For the detail pages we already fetch:
     - Sleep: `fetchSleepSessions(30)` (`frontend/src/components/Sleep.tsx:22`) — 30-day window of every session, both sources.
     - Lifting: `fetchStrengthSessions(limit)` — list of sessions by date.
     - Workout: `fetchActivities({ days, limit })` (`frontend/src/api/activities.ts:121`) — already used by `History.tsx`.
   - **Window**: load up to **365 days** for neighbor calculation (single cached call). If the user runs off the end, show the arrow disabled.
   - **Fallback** (not adopted): server-side endpoints `GET /sleep/neighbors`, `GET /activities/{id}/neighbors`, `GET /strength/session/{date}/neighbors`.

2. **Workout detail: cross-source navigation or per-source?** **Cross-source within URL family.**
   - From a Strava run, prev/next steps to the previous/next Strava or Apple workout (not to a lifting session).
   - From a lifting session, prev/next steps to the previous/next lifting session only.
   - Justification: matches today's URL scheme without forcing a router switch mid-navigation.

3. **Sleep & Recovery: single page or separate?** **Single page** at `/sleep`. `/recovery` is a trends/chart page with date-range selectors (out of scope). URL contract: `/sleep?date=YYYY-MM-DD`.

## 5. Backend tasks
**None.**

## 6. Frontend tasks
1. **Create `frontend/src/components/ui/DetailNavArrows.tsx`** — small presentational component with two `ChevronLeft`/`ChevronRight` buttons, disabled-state styling copied from `Header.tsx:71-80`. Props: `onPrev`, `onNext`, `hasPrev`, `hasNext`, `loading`.
2. **Create `frontend/src/hooks/useDetailNeighbors.ts`** — three small hooks:
   - `useSleepNeighbors(currentDate: string | undefined)`: calls `fetchSleepSessions(365)`, dedupes per night.
   - `useActivityNeighbors(currentId: number, currentSource: ActivitySource | null)`: calls `fetchActivities({ days: 365, limit: 500 })`, returns prev/next `{ id, source }`. Preserve `source` query param.
   - `useLiftingNeighbors(currentDate: string)`: calls `fetchStrengthSessions(500)`.
3. **Wire `SleepRecoveryDetailsCard.tsx`** — Sticky header gets arrows on the right. `navigate('/sleep?date=...')`.
4. **Wire `ActivityHeader.tsx`** — Sticky header gets arrows on the right. `navigate('/activities/{id}?source=...')`.
5. **Wire `LiftingDetail.tsx`** — Header gets arrows on the right. `navigate('/workouts/lifting/{date}')`.
6. **Keyboard handling** (optional, low-cost) — bind ArrowLeft/ArrowRight at the detail page level. Skip if it conflicts with form inputs.
7. **Loading UX** — disabled (greyed) arrows while loading, not hidden.

## 7. Migration tasks
**None.** No schema changes.

**Risk: trivial**

## 8. Tests to add
- `frontend/src/hooks/useDetailNeighbors.test.ts` (new) — hook returns correct prev/next, returns `null` when current is first/last, returns `null` when list empty.
- Render tests in `SleepRecoveryDetailsCard.test.tsx`, `ActivityDetail.test.tsx`, `LiftingDetail.test.tsx` — arrows render, disabled at edges, navigate to correct URL.

## 9. Parallelism plan
Phase 1 skipped — no integration-researcher, no db-migrator, no migration-safety-checker.

```
phase 2 (single agent):
  - frontend-engineer → DetailNavArrows component + useDetailNeighbors hook + wire into all 3 detail pages + tests
    (Single agent because the wiring depends on the component/hook contract — splitting risks interface mismatch.)

phase 3 (sequential):
  - test-runner
  - code-reviewer + qa-verifier + security-reviewer (parallel)
  - PR opener
```

## 10. Risks and rollback
- **Production risk: very low.** Frontend-only change, no DB, no API contract change.
- **Edge cases:**
  - 365-day window cap: arrow may appear disabled when older record exists outside window. Accept for v1.
  - Apple/Strava id collisions: must keep `?source=apple_health|strava` on every navigation step.
  - Sleep night-labeling skew: WHOOP and Eight Sleep can label the same night ±1 calendar day. Collapse to unique sorted set of dates per night.
  - `/sleep` without `?date=` shows latest night; next arrow disabled, prev jumps to second-newest.
- **Rollback:** revert the PR. No data mutated, no migration.

---

Relevant absolute file paths:
- `/home/user/Health-tracker/frontend/src/App.tsx`
- `/home/user/Health-tracker/frontend/src/components/HomeLayout.tsx`
- `/home/user/Health-tracker/frontend/src/components/dashboard/Header.tsx` (reference styling)
- `/home/user/Health-tracker/frontend/src/components/Sleep.tsx`
- `/home/user/Health-tracker/frontend/src/components/sleep/SleepRecoveryDetailsCard.tsx`
- `/home/user/Health-tracker/frontend/src/components/ActivityDetail.tsx`
- `/home/user/Health-tracker/frontend/src/components/activity/ActivityHeader.tsx`
- `/home/user/Health-tracker/frontend/src/pages/LiftingDetail.tsx`
- `/home/user/Health-tracker/frontend/src/pages/History.tsx`
- `/home/user/Health-tracker/frontend/src/lib/historyEvents.ts`
- `/home/user/Health-tracker/frontend/src/api/sleep.ts`
- `/home/user/Health-tracker/frontend/src/api/activities.ts`
- `/home/user/Health-tracker/frontend/src/api/strength.ts`
- `/home/user/Health-tracker/frontend/src/hooks/useApi.ts`
