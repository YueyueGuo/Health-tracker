# Bug diagnosis: Shoe selection PATCH lands on wrong row; GET reads correct row → tag disappears on reload

## 1. Symptom restated

The user picks a shoe in the workout-detail dropdown on a foot-sport activity. The dropdown now **shows the correct shoe** after the tap (PR #73 / commit `25dfb75` added optimistic local state in `ShoeSelector.tsx`). When the user navigates away (e.g. to History) and back to the same activity, the dropdown reads `— None —`. Expected: the picked shoe survives a remount and reload because `activity.shoe_id` is persisted server-side. Actual: a fresh `GET /api/activities/{id}?source=...` returns `shoe_id: null`, so when the optimistic state seeds itself from `currentShoeId`, the dropdown reverts.

In other words, the optimistic UI fix from PR #73 successfully masked the visual flicker (H1 of `docs/bugs/shoe-selection-not-persisting.md`), but it also masked the underlying server-persistence bug flagged in that same doc as H4 / cleanup #4. We are now hitting that latent bug.

## 2. Reproduction (best-effort, read-only)

No existing test covers the exact path. The closest are:

- `tests/test_routers/test_shoes.py::test_tag_activity_id_collision_strava_wins` (lines 564-617) — *pins* the current buggy behavior. It seeds an `Activity` and a `HealthDataPoint`/`Workout` with the **same id**, PATCHes shoe, and asserts the response says `"source": "strava"`. The test never PATCHes with `?source=apple_health` because the endpoint ignores it.
- `tests/test_routers/test_shoes.py::test_patch_shoe_then_get_activity_returns_shoe_id_apple` (lines 660-688) — round-trips Apple but seeds *only* the Apple side. With no `Activity` row at that id, the PATCH's Strava lookup misses and the fallback Apple branch correctly writes `Workout.shoe_id`. So this test passes today but does NOT cover the collision case.

The regression test that would have caught the user's bug — "seed both an Apple Workout and a Strava Activity with **different** ids that happen to coincide numerically, PATCH the Apple side via `?source=apple_health`, then GET the Apple side and assert `shoe_id` is populated" — does not exist.

Targeted runnable check that exercises the suspect lines without mutating anything outside a temp test DB:

```
python -m pytest tests/test_routers/test_shoes.py -k "collision or roundtrip" -v
```

Both pass on `main`. That is the diagnostic point.

User-visible reproduction requires id-space collision between `activities.id` and `health_data_points.id`. Since both are independent `Integer autoincrement` PKs (`backend/models/activity.py:32`, `backend/models/health_data_point.py:53`) and the deployed Railway DB has both Strava and Apple ingestion live (PR #42 `5a99a0d`), collisions in the low integers are essentially guaranteed for the project owner's data.

## 3. Ranked hypotheses

### H1 (strong prior — most likely real bug). PATCH `/api/activities/{id}/shoe` ignores `?source=` and Strava-resolves first, so any tap on the Apple Health side of a colliding id writes to the wrong table. The subsequent `GET ?source=apple_health` reads the (still-null) `workouts.shoe_id` and the dropdown shows "— None —".

Files implicated:
- `backend/routers/activities.py:291-362` — `patch_activity_shoe` signature has no `source` parameter; lines 320-331 unconditionally do `select(Activity).where(Activity.id == activity_id)` and commit there if any Strava row matches.
- `backend/routers/activities.py:159-167` — GET *does* honor `source == "apple_health"` and routes to `get_apple_workout_detail`, which reads `workout.shoe_id` (via `_apple_workout_summary` at line 643).
- `backend/services/apple_workout_detail.py:80-86` — confirms the GET reads `workout.shoe_id`, not `activity.shoe_id`.
- `frontend/src/api/activities.ts:182-192` — `patchActivityShoe` already appends `?source=...` on the wire ("forward-compat" per the doc comment), so no frontend change is needed once the backend honors it.
- `frontend/src/components/ActivityDetail.tsx:152-156` — frontend passes `source={activity.source ?? null}` to `ShoeSelector`, which forwards it to `patchActivityShoe`.
- `tests/test_routers/test_shoes.py:564-617` — `test_tag_activity_id_collision_strava_wins` is the smoking gun: it pins the wrong behavior with an explicit assertion `body["source"] == "strava"` after PATCHing a colliding id.

Mechanism: User opens `/activities/<dp.id>?source=apple_health` for an Apple-Health workout whose `dp.id` happens to numerically equal some unrelated `Activity.id`. The frontend sends `PATCH /api/activities/<dp.id>/shoe?source=apple_health` with `{"shoe_id": N}`. The backend ignores `source`, finds a Strava `Activity` at that id (the unrelated row), writes `Activity.shoe_id = N`, commits, returns `{"source": "strava", "shoe_id": N}` (note: a careful user could spot this in DevTools — but the optimistic UI suppresses any visible cue). The fronted's `onChange` → `reload()` fires `GET /api/activities/<dp.id>?source=apple_health`, which calls `get_apple_workout_detail`, which reads `workout.shoe_id` — still `null`. The optimistic `pendingShoeId` clears on next prop change, the dropdown reverts to None.

Falsification: Backend integration test seeding `Activity(id=K)` AND `HealthDataPoint+Workout(id=K)` separately, PATCHing `/api/activities/K/shoe?source=apple_health` with `{"shoe_id": S}`, then GETting `/api/activities/K?source=apple_health`. Currently `body["shoe_id"]` is `null`; with the fix it should be `S`. Symmetric test for `?source=strava` ensures we don't regress Strava-side semantics.

### H2 (plausible — secondary contributor for non-colliding ids). Activity-detail query-cache key shape mismatch — `invalidateShoes` invalidates `["activities"]`, but the user's navigation pattern (navigate away → navigate back) doesn't depend on invalidation; it depends on a fresh fetch when the component remounts.

Files implicated:
- `frontend/src/hooks/useShoes.ts:61-66` (`invalidateShoes`)
- `frontend/src/hooks/useApi.ts:23-33` (`useQuery` with default `gcTime`)
- `frontend/src/components/ActivityDetail.tsx:36-39` (`useApi(["activities", "detail", activityId, source], …)`)

Mechanism: Even if the invalidate-and-reload step right after PATCH worked perfectly (which it does — the optimistic UI showed the value, and a successful refetch would have `shoe_id=N`), the user-reported symptom is on a *remount* after route navigation. On remount, TanStack Query refetches per `refetchOnMount` defaults — the query's `data` is whatever the most recent server response said. If the server response is wrong (H1), this hypothesis is moot. If the server response is right and the remount-refetch is somehow served from a stale cache that the optimistic write never reached, this would matter. But `ShoeSelector` doesn't call `setQueryData` on the activity-detail cache, so on success the cache reflects only the GET-after-reload response, not the PATCH echo. As long as the server is consistent, this path works. **Verdict: speculative — probably falsified once H1 is fixed.**

Falsification: After the H1 fix, verify the second-mount network call returns `{"shoe_id": <N>}` from `GET /api/activities/<id>?source=...`. If yes, H2 is moot.

### H3 (low likelihood — listed for completeness). Silent PATCH 5xx swallowed by the optimistic-state's catch block, leaving the UI green but no row mutated.

Files implicated:
- `frontend/src/components/shoes/ShoeSelector.tsx:75-94` — `handleChange` catches errors and rolls back `pendingShoeId`, calls `setActionError(getErrorMessage(e))`.

Mechanism: If `patchActivityShoe` throws, the catch block sets `actionError` and re-renders the inline `<div className="error">`. That's visible UX, not silent. The only "silent" path is if `fetchJson` somehow returned successfully on a 5xx; spot-check `frontend/src/api/http.ts` if needed, but the standard `fetchJson` raises on non-2xx. **Verdict: very unlikely.**

Falsification: Network tab on Railway shows the PATCH returns 200, not 5xx. The prior diagnosis already established the integration tests cover the 200 path.

### H4 (low likelihood — speculative). `db.refresh(activity)` returns stale data on Railway-asyncpg.

Files implicated:
- `backend/routers/activities.py:325-331`, `355-361`.

Mechanism: Speculative — was H4 in the prior diagnosis. The backend integration tests cover round-trip; H4 is only worth keeping if H1's falsification step shows the PATCH echoes the correct `source` and `shoe_id` on Railway yet a *subsequent same-source* GET returns null. With H1 in play, this is almost certainly not the bug.

Falsification: Direct curl `PATCH` followed by `GET` (same `source`) on Railway. If `GET` returns `null` even with `source` matched, escalate to H4.

### H5 (low likelihood — speculative). Apple Workout PATCH branch's `db.refresh(workout)` reads from the joined `HealthDataPoint` table and silently drops `workouts.shoe_id` due to a joined-table-inheritance quirk.

Files implicated:
- `backend/models/workout.py:31-69` — joined-table inheritance via `Workout.id` FK to `health_data_points.id`. `Workout.shoe_id` is on the `workouts` table directly.
- `backend/routers/activities.py:355-361`.

Mechanism: Speculative. The Apple `_apple` integration test (`test_patch_shoe_then_get_activity_returns_shoe_id_apple`) passes, which exercises exactly this branch with no Strava collision. So the joined-table refresh works. Only relevant if H1 turns out wrong.

Falsification: Already falsified by the existing passing Apple round-trip test.

## 4. Recommended fix

**Most likely real bug: H1.** Backend `PATCH /api/activities/{id}/shoe` must accept and honor `?source=` exactly like `GET /api/activities/{id}` does. The frontend already sends `?source=`. The only authoritative source-of-truth issue is the backend ignoring it on writes while honoring it on reads.

Minimum-scope fix (one file):

1. `backend/routers/activities.py` — `patch_activity_shoe` (line 291):
   - Add `source: str | None = Query(None, description=...)` parameter mirroring the GET (line 129-137).
   - Validate `source in (None, "strava", "apple_health")` exactly like GET (line 153-157).
   - When `source == "apple_health"`, skip the `Activity` lookup entirely and go straight to the HDP/Workout branch.
   - When `source == "strava"`, do the `Activity` lookup but do NOT fall through to Apple on miss (404 instead).
   - When `source is None`, retain the current Strava-first / Apple-fallback behavior for backward compatibility with old clients.

The fix is roughly +15 lines, zero schema changes, zero migration.

**Migration required: no.** The columns `activities.shoe_id` and `workouts.shoe_id` already exist and are correct.

**Update existing tests:** `tests/test_routers/test_shoes.py::test_tag_activity_id_collision_strava_wins` (line 564) currently *pins the bug*. Either:
- (a) repurpose it to assert "source=strava parameter is required to land on the Strava row when ids collide" (i.e. PATCH without `?source=` keeps the legacy Strava-first behavior, PATCH with `?source=apple_health` lands on the Workout), or
- (b) rename it and add a sibling `test_tag_activity_id_collision_source_apple_lands_on_workout`. Option (b) is clearer and keeps the historical "no-source = Strava-first" pin intact.

**New regression test (must fail on current `main`):**

`tests/test_routers/test_shoes.py::test_patch_shoe_with_source_apple_health_routes_to_workout_on_id_collision`

```
- Seed HealthDataPoint(id=K, source='apple_health', data_type='workout')
        + Workout(id=K)  with a known external_id and no Strava back-link.
- Seed Activity(id=K, strava_id=<distinct>)  separately (different actual run).
- POST /api/shoes  → shoe_id S
- PATCH /api/activities/K/shoe?source=apple_health  body={"shoe_id": S}
  Assert response.status_code == 200
  Assert body["source"] == "apple_health"
  Assert body["shoe_id"] == S
- GET /api/activities/K?source=apple_health
  Assert body["shoe_id"] == S           # the actual user-visible regression
- GET /api/activities/K?source=strava
  Assert body["shoe_id"] is None        # the unrelated Strava row was NOT touched
```

Optional symmetric test: `…_with_source_strava_routes_to_activity_on_id_collision` — same seed, PATCH `?source=strava`, GET both sides, assert only `Activity.shoe_id` mutated.

**Frontend tests:** No new frontend assertions are strictly required for this bug — the existing optimistic-UI tests already cover the dropdown. The wire-level test of `patchActivityShoe` is already in place. Optionally, add a single test in `tests/test_routers/test_shoes.py` that asserts `PATCH .../shoe?source=invalid` returns 400 (validation parity with GET).

If H1 is somehow not the bug (e.g. the user's data has no id collisions), the H1 fix is still correct as a defense-in-depth measure (PATCH and GET source semantics should match), and the next test to add is the curl-on-Railway diagnostic from H4's falsification step.

## 5. Out-of-scope cleanup spotted

(Recording only — orchestrator can spin these off.)

- `frontend/src/api/activities.ts:174-181` — the docstring on `patchActivityShoe` documents that the backend ignores `source`. Once the backend fix lands, update this comment so future agents don't think the parameter is dead.
- `tests/test_routers/test_shoes.py:564-617` — `test_tag_activity_id_collision_strava_wins` enshrines the **bug-as-spec**. After the fix this test should be renamed/repurposed to clearly state "default-source PATCH retains legacy Strava-first for back-compat; explicit `?source=apple_health` lands on the Workout".
- `backend/routers/activities.py:231-288` — `patch_activity_feedback` has the same "Strava-only-with-Apple-soft-refusal" shape but no `?source=` either. Since RPE/notes are Strava-only by design (line 261-267), this is fine, but worth a passing comment explaining why the PATCH `/shoe` endpoint deliberately differs from PATCH `/feedback`.
- `frontend/src/components/shoes/ShoeSelector.tsx:108` — the inline-create flow calls `patchActivityShoe(activityId, created.id, source)` with the same buggy `source` argument; once H1 is fixed, this path also benefits automatically. Worth a regression test that exercises it on a colliding id.
- `backend/models/activity.py:32` and `backend/models/health_data_point.py:53` — both autoincrement `Integer`. Long-term, consider namespacing (e.g. `apple_` prefix on HDP URLs, or a separate `/api/workouts/{id}` family) so the entire id-collision surface evaporates. The current `?source=` disambiguator is correct but it's a band-aid on a fundamental id-space overlap.
- `frontend/src/components/shoes/ShoeSelector.tsx:194` — the disabled-option-as-current-value pattern for retired tags is still latently buggy on iOS Safari (cleanup item from the prior diagnosis); independent of H1.
