# Diagnosis: Apple-Watch row routes to wrong activity on id collision

## 1. Symptom
On `/history`, tapping the Apple-Watch "Functional Strength Training" row
(May 23, sourced via HAE) opens the detail page for an unrelated Strava ride
(April 15). Expected: the Apple-Watch strength workout's own detail page.

Cause is an integer-id collision between the `activities` table (Strava) and
the `health_data_points` table (Apple Health) plus a routing layer that never
disambiguates by source.

## 2. Reproduction
- Conditions: an Apple Watch HAE workout with `health_data_points.id = N`, and
  a Strava activity with `activities.id = N` (the autoincrement counters in
  the two tables overlap).
- Steps: open `/history`, tap the Apple row → frontend calls
  `GET /activities/N` → `backend/routers/activities.py:129` resolves the
  Strava row first; the Apple branch
  (`apple_workout_detail.get_apple_workout_detail`) is only reached when the
  Strava lookup misses.
- Existing covered scenarios: `frontend/src/lib/historyEvents.test.ts:257-281`
  proves React keys are disambiguated but does NOT assert `navigateTo` differs.
  No backend test forces the collision either.

## 3. Ranked hypotheses

### H1 (confirmed): URL lacks a source qualifier; backend `/activities/{id}` resolves Strava-first on collision.
- Frontend: `frontend/src/lib/historyEvents.ts:181`
  ```
  navigateTo: `/activities/${a.id}`,
  ```
  Both Strava and Apple rows produce the same URL when `a.id` collides.
  Confirmed by tests at `frontend/src/lib/historyEvents.test.ts:182-228` which
  lock in `/activities/{id}` for both sources.
- Router: `frontend/src/App.tsx:41`
  ```
  <Route path="/activities/:id" element={routeElement(<ActivityDetail />)} />
  ```
  No source segment / query consumed.
- Page: `frontend/src/components/ActivityDetail.tsx:23-28` reads only `id`
  from params and calls `fetchActivity(id)`.
- API call: `frontend/src/api/activities.ts:136-137`
  ```
  return fetchJson<ActivityDetail>(`/activities/${id}`);
  ```
- Backend resolver: `backend/routers/activities.py:115-139`
  ```
  result = await db.execute(select(Activity).where(Activity.id == activity_id))
  activity = result.scalar_one_or_none()
  if not activity:
      ... apple fallback ...
  ```
  The docstring (`activities.py:124-127`) explicitly states "Strava wins on
  collisions; Apple-only ids only resolve after the Strava lookup misses."
  Whenever the Apple HDP id also happens to be a valid `activities.id`, the
  Strava row is returned every time.

### H2 (confirmed): PR #63 hardened the React key but not the URL.
- `git show 6c35d04 -- frontend/src/lib/historyEvents.ts` (PR #63) added
  `sourceKey` only on the `id` field used as the React key:
  ```
  id: `${sourceKey}-${a.id}`,
  navigateTo: `/activities/${a.id}`,
  ```
- The author's comment at `historyEvents.ts:160-167` acknowledges the
  id-space overlap and incorrectly trusts the backend to "resolve the right
  table" — but the backend resolves Strava-first on collision (see H1).

### H3 (ruled out): Strength row routing.
- Strength rows route to `/workouts/lifting/:date`
  (`historyEvents.ts:198`). An Apple-Watch "Functional Strength Training"
  workout comes through the activities list (`source = "apple_health"`,
  `sport_type = "strength"` per `_apple_workout_summary` →
  `normalized_to_strava_view`, see `backend/routers/activities.py:438`), not
  as a `StrengthSession`. It takes the activity path and is governed by H1.

### H4 (ruled out): Cache key collision in `useApi`.
- `ActivityDetail.tsx:25` keys the cache on `["activities", "detail", activityId]`.
  Even with cache cleared the wrong response would arrive (the fetch itself
  is ambiguous). Cache is downstream of the real defect.

## 4. Recommended fix

Disambiguate by source on BOTH sides of the call.

### Shape choice: query param `?source=apple_health`
A query param is additive and backward-compatible: legacy URLs
(`/activities/123` with no source) keep the current Strava-first behavior,
and the new `?source=apple_health` selects the HDP row explicitly. `?source=strava`
makes the Strava intent explicit. Avoids a parallel route and an unnecessary
detail-page duplicate (the existing `ActivityDetail` already branches on
`activity.source`).

### Backend (`backend/routers/activities.py`)
- Add `source: str | None = Query(None)` to `get_activity` (line 116).
- When `source == "apple_health"`, skip the `Activity` SELECT and call
  `get_apple_workout_detail` directly. 404 if it returns None.
- When `source == "strava"`, do the Strava lookup and 404 explicitly
  without falling through to Apple.
- When `source is None`, retain today's Strava-first / Apple-fallback for
  backward compatibility.
- Apply the same disambiguation to `GET /activities/{id}/streams`
  (`activities.py:327`) — same Strava-first / Apple-fallback structure.

### Frontend
- `frontend/src/lib/historyEvents.ts:181` — emit `navigateTo` as
  `/activities/${a.id}?source=${a.source}` when `a.source` is `apple_health`
  or `strava`. For legacy `null` source, keep `/activities/${a.id}`.
- `frontend/src/api/activities.ts:136-137` — `fetchActivity` should take an
  optional `source` arg and append it as a query string.
- `frontend/src/api/activities.ts:140-141` — same for `fetchActivityStreams`.
- `frontend/src/components/ActivityDetail.tsx:22-28` — read `source` via
  `useSearchParams` (or `URLSearchParams(location.search)`) and pass it to
  `fetchActivity` and `fetchActivityStreams`. Include it in the `useApi`
  cache keys so a colliding id can't share a cache entry across sources.

### Tests
- `frontend/src/lib/historyEvents.test.ts`: extend the existing collision
  test (line 257-281) to also assert `events.find(e => e.id === "apple-1").navigateTo !== events.find(e => e.id === "strava-1").navigateTo`,
  and assert the Apple URL contains `source=apple_health`. Update the
  existing test (line 182-196) which currently locks in the buggy behavior.
- Backend: add a regression test under `tests/routers/test_activities*.py`
  that seeds an `Activity(id=N)` and an Apple `HealthDataPoint(id=N,
  source="apple_health", data_type="workout")` + paired `Workout(id=N)`,
  then asserts:
  - `GET /activities/N` returns the Strava row (back-compat).
  - `GET /activities/N?source=apple_health` returns the Apple row.
  - `GET /activities/N?source=strava` returns the Strava row.
  - Same matrix for `/activities/N/streams`.
- `frontend/src/components/ActivityDetail.test.tsx`: assert the fetch URL
  includes `?source=apple_health` when the route is entered with that query
  and that the page renders the Apple branch.

### Migration?
No DB migration needed. Purely an API shape addition.

## 5. Out-of-scope cleanup spotted
- `backend/routers/activities.py:188-225` (`PATCH /activities/{id}/feedback`)
  and `backend/routers/activities.py:248-296` (`POST /activities/{id}/classify`)
  hand-roll the same Strava-first / Apple-fallback pattern. Same collision
  risk; worth unifying behind a single resolver helper in a follow-up.
- `backend/routers/activities.py:299-324` (`GET /activities/{id}/weather`)
  never even tries the Apple fallback — it 404s on any Apple id.
- `historyEvents.ts:160-167` comment is now actively misleading. Should be
  rewritten when the URL is fixed.
- No end-to-end test asserts the History row → backend detail path with a
  real id collision. The new regression should fill that gap.

## Key file paths
- `frontend/src/lib/historyEvents.ts` (line 181 — bug site)
- `frontend/src/App.tsx` (line 41 — route definition)
- `frontend/src/components/ActivityDetail.tsx` (lines 22-28 — id param, fetch)
- `frontend/src/api/activities.ts` (lines 136-141 — fetchActivity / fetchActivityStreams)
- `backend/routers/activities.py` (lines 115-139 — Strava-wins resolver; lines 327-356 — same pattern for streams)
- `backend/services/apple_workout_detail.py` (fallback resolver that gets bypassed)
- `frontend/src/lib/historyEvents.test.ts` (lines 182-228, 257-281 — tests that should be extended)
- PR #63 commit: `6c35d04`
