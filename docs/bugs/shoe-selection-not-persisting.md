# Bug diagnosis: Shoe selection on workout detail page snaps back to "— None —"

## 1. Symptom restated

On the workout (activity) detail page, the user successfully creates a new shoe via the inline "+ Add a shoe" affordance. The new shoe appears as an option in the steady-state `<select>` dropdown. When the user taps the option to tag the activity with that shoe, the dropdown immediately rebounds to the "— None —" sentinel option rather than landing on the picked shoe. Expected: the dropdown shows the chosen shoe's name after the tap, persists across reload, and the activity is tagged with that shoe (so the shoe's cumulative mileage updates).

The relevant surface is the running-shoe selector that ships with the just-merged shoe-mileage UI feature (PR #72, frontend commit `a3a8e80`, on top of backend PR #65 `6fd783b`).

## 2. Reproduction (best-effort, read-only)

There is no existing end-to-end test that covers the user-visible cycle "user picks an option in the controlled `<select>` → activity reloads → dropdown reflects the new `shoe_id`". The closest tests are:

- Frontend unit test `frontend/src/components/shoes/ShoeSelector.test.tsx` — asserts that `patchActivityShoe` is **called** with the right `(activityId, shoeId, source)` triple (lines 90-109), but the parent `onChange` is a `vi.fn()` and the mocked PATCH response is `{shoe_id: null}` (lines 48-52), so the test never asserts that the dropdown re-renders with the chosen value.
- Backend integration tests `tests/test_routers/test_shoes.py::test_patch_shoe_then_get_activity_returns_shoe_id_strava` (lines 620-657) and `…_apple` (lines 660-688) — do a real PATCH followed by GET and assert `body["shoe_id"] == shoe_id` on the GET. These pass.
- Frontend `ActivityDetail` test (`frontend/src/components/ActivityDetail.test.tsx:93-95`) stubs `ShoeSelector` to a dumb `<div>Shoe selector</div>`, so the wiring `currentShoeId={activity.shoe_id ?? null} / onChange={reload}` is never exercised under test.

Manual reproduction:

1. Run backend + frontend locally (`uvicorn backend.main:app --reload --port 8000` and `cd frontend && npm run dev`).
2. Navigate to a Run (foot-sport) activity detail page, e.g. `/activities/<id>`.
3. With no shoes yet, click "+ Add a shoe", create one, observe the partial-failure copy ("Created … but failed to tag it on this run") or the success path.
4. Once the steady-state dropdown is showing the shoe as an option, pick it.
5. Watch the dropdown — it should land on the shoe but reverts to "— None —".

Targeted runnable check (read-only, exercises the suspect lines):

```
cd frontend && npx vitest run src/components/shoes/ShoeSelector.test.tsx
python -m pytest tests/test_routers/test_shoes.py -k 'patch_shoe_then_get'
```

Both will pass on `main`, which is the diagnostic point: the regression test that would have caught this — "dropdown `select.value` reflects the picked shoe after the PATCH-reload cycle completes" — doesn't exist.

## 3. Ranked hypotheses

### H1. Stale `currentShoeId` snaps the controlled `<select>` back to `""` during the in-flight PATCH because `useApi`'s `query.data` is returned by reference as `query.data ?? null` and the parent never gets a chance to repaint between user input and the PATCH-induced refetch on slow Railway round-trips. (Most likely UX-visible mechanism.)

Files implicated:
- `frontend/src/components/shoes/ShoeSelector.tsx:54-67` (the `handleChange` coroutine)
- `frontend/src/components/shoes/ShoeSelector.tsx:147-156` (controlled `<select value={currentShoeId ?? ""}>`)
- `frontend/src/components/ActivityDetail.tsx:152-157` (props `currentShoeId={activity.shoe_id ?? null}` and `onChange={reload}`)
- `frontend/src/hooks/useApi.ts:42-44` (`reload = () => query.refetch()`)

Mechanism: the dropdown is a *controlled* component. When the user taps a shoe option, React fires onChange synchronously, `handleChange` runs `setBusy(true)` (which queues a re-render), then `await`s the PATCH. Between the tap and the eventual refetch landing, React re-renders with the *unchanged* `currentShoeId` (still `null`, because no one has called `setState` on the parent yet) and forcibly resets `select.value` back to `""`. So the browser shows "— None —" for the entire duration of the PATCH + refetch round-trip. If the PATCH then fails silently (network blip, 5xx, CORS), `setActionError` displays an inline error and the dropdown stays on "— None —" forever. On Railway, a cold-start PATCH followed by a cold-start GET refetch can be several seconds — long enough that the user reads "stays on '— None —'" as the steady state.

This is not a race condition per se — it's the expected behavior of a controlled select with a value derived from server-fetched parent state, with **no optimistic UI**. The selector does not call `setData` on the activity query to apply the new `shoe_id` optimistically; it waits for the GET to return. Every other workout-detail selector (`RPECard`, `LocationPicker`) hides this latency behind a "Saving…" button that doesn't reset its visual state mid-PATCH, but `ShoeSelector` lays the persistence latency directly on top of the dropdown's visible value.

Falsification: open DevTools Network tab while reproducing; if `PATCH /api/activities/:id/shoe` returns 200 with `{"shoe_id": <chosen id>}` and a subsequent `GET /api/activities/:id` returns `{"shoe_id": <chosen id>}`, the dropdown should eventually settle on the chosen value (just with a long visible flicker). If both responses are correct but the dropdown still doesn't settle, H1 is falsified and we're looking at a cache/observer issue (H2 or H3).

### H2. The `useApi` activity-detail query observer doesn't re-attach after `invalidateShoes(["activities"])` due to query-key shape mismatch when the URL has no `?source=` param.

Files implicated:
- `frontend/src/hooks/useShoes.ts:61-66` (`invalidateShoes`)
- `frontend/src/hooks/useApi.ts:22-28` (the activity query)
- `frontend/src/components/ActivityDetail.tsx:36-39` (`useApi(["activities", "detail", activityId, source], …)`, where `source` may be `null` when the URL omits `?source=`)

Mechanism: `invalidateShoes` calls `client.invalidateQueries({ queryKey: ["activities"] })` — a prefix match that *should* hit `["activities", "detail", activityId, null]`. If TanStack Query's prefix match does the wrong thing with `null` query-key segments (it shouldn't, but worth checking), the activity-detail query never refetches and the dropdown's `currentShoeId` stays as the original `null`. The manual `reload()` from `onChange` is the safety net here, but it's fired-and-forgotten (`onChange()` is called without `await`), so any error in the refetch is silently swallowed.

Falsification: log `query.dataUpdatedAt` before and after the PATCH in `ActivityDetail`; if it doesn't advance, the refetch isn't happening (H2 confirmed). If it advances but the data still has `shoe_id: null`, the backend GET is at fault (H4).

### H3. The frontend `Shoe.id` returned by `createShoe` and the `s.id` rendered in `<option value={s.id}>` are typed `number` in TS but arrive as `string` from the JSON response on some path (e.g. a number > `Number.MAX_SAFE_INTEGER`, which Postgres `bigint` produces). Then `<select value={currentShoeId ?? ""}>` (a number) never matches `<option value={"123"}>` (a string).

Files implicated:
- `frontend/src/api/shoes.ts:17-32` (`Shoe.id: number`)
- `frontend/src/api/activities.ts:165-170` (`ActivityShoeUpdate.shoe_id: number | null`)
- `frontend/src/components/shoes/ShoeSelector.tsx:152` (`handleChange(val === "" ? null : Number(val))` — already defensively coerces; this is fine)
- `frontend/src/components/shoes/ShoeSelector.tsx:159` (`<option value={s.id}>`)
- `backend/models/shoe.py:33+` (the `shoes.id` column is `Integer`, not `BigInteger`, so `Number.MAX_SAFE_INTEGER` is not relevant here — strike most of this; included for completeness)

Mechanism: Speculation — the typing is correct (`Integer` PKs deserialise as JS `number`), so this is unlikely to be the actual cause. Including it as a low-likelihood placeholder for "ID type mismatch on the select" — the standard suspect for "controlled select won't change" bugs.

Falsification: log `typeof currentShoeId`, `typeof activeShoes[0].id`, and `select.value` immediately before and after the change.

### H4. `db.refresh(activity)` after the PATCH commit does not actually re-load `shoe_id` because of a stale identity-map row or session-state issue when the same activity was just hydrated by an in-flight GET in the same `AsyncSession`.

Files implicated:
- `backend/routers/activities.py:320-331` (Strava PATCH branch — `db.commit()` then `db.refresh(activity)` then return `activity.shoe_id`).
- `backend/routers/activities.py:355-361` (Apple Workout PATCH branch — same shape).

Mechanism: Speculation — SQLAlchemy's `AsyncSession.refresh` reloads all mapped columns from the database. The PATCH endpoint creates a fresh `AsyncSession` via `Depends(get_db)` so identity-map contamination from a previous request shouldn't be possible. The integration tests in `test_shoes.py` (`test_patch_shoe_then_get_activity_returns_shoe_id_strava`) cover the round-trip and pass. I'm listing this so the falsification step explicitly tests it.

Falsification: in the user's Railway environment, hit the PATCH endpoint directly with `curl` and then `curl` the GET. If `GET /api/activities/:id` returns `{"shoe_id": null}` immediately after a successful PATCH (200 with `{"shoe_id": <id>}`), H4 is confirmed and we have a server-side persistence bug. Otherwise, H4 is falsified.

### H5. The `ShoeSelector` `<option>` for the just-created shoe is rendered, but the new shoe is filtered out of `activeShoes` because `useShoesList("active")` returns a cached response that predates the create — the user sees the new shoe in the dropdown only because the inline-create flow renders it via `tagToRetired`-style logic that I missed.

Files implicated:
- `frontend/src/components/shoes/ShoeSelector.tsx:38-52`
- `frontend/src/hooks/useShoes.ts:21-23`

Mechanism: Speculation — `handleInlineCreate` calls `invalidateShoes(queryClient)` (line 82-89), which invalidates `["shoes"]` and triggers a refetch of `useShoesList("active")`. The new shoe should appear after the refetch. Unlikely to be the cause but easy to verify.

Falsification: log `activeShoes` and `currentShoeId` on render when the bug occurs. If `currentShoeId === createdShoe.id` but `activeShoes.find(s => s.id === currentShoeId)` is `undefined`, then `tagToRetired` is `true` and the new shoe renders only as a disabled "(retired) #<id>" option — which would explain the symptom precisely (the controlled select can't be set to a disabled option, so it falls back to `""`).

## 4. Recommended fix

Most likely real bug: **H1 — the controlled `<select>` flickers back to "— None —" during PATCH + refetch because nothing applies the new `shoe_id` optimistically.** The integration tests on both sides confirm the data round-trip is correct, but the test gap is exactly the post-tap re-render of the dropdown — confirming the bug is at that seam.

Minimum-scope fix (one of these patterns, in order of intrusiveness):

1. **Optimistic local state in `ShoeSelector`.** Hold a `selectedId` `useState<number | null | undefined>(undefined)` that is set in `handleChange` *before* the await, and used as the `<select value>` (falling back to `currentShoeId` when `undefined`). Reset to `undefined` once the parent's `onChange` resolves (or on next `currentShoeId` prop change via `useEffect`). Touches only `frontend/src/components/shoes/ShoeSelector.tsx`.
2. **Optimistic cache write via `setData` on the activity query.** Have `onChange` accept the new `shoe_id` and call `queryClient.setQueryData(["activities", "detail", activityId, source], (prev) => ({...prev, shoe_id: newId}))` synchronously after the PATCH resolves, before triggering the refetch. Touches `ShoeSelector.tsx` + `ActivityDetail.tsx` (the `onChange` signature).
3. **Show a "Saving…" disabled state with the chosen label.** Display the *target* shoe's name on the disabled select while `busy === true` rather than falling back to `currentShoeId ?? ""`. Touches only `ShoeSelector.tsx`.

Option 1 is the smallest change and matches how `RPECard` and `LocationPicker` hide their own latency.

New/updated tests required:
- `frontend/src/components/shoes/ShoeSelector.test.tsx`: extend `"calls patchActivityShoe when the user picks a shoe"` to also assert `expect(select.value).toBe("2")` *after* the awaited PATCH resolves (even though the mocked PATCH returns `shoe_id: null` — the visual selection should reflect the user's choice immediately while the network call is pending). Add a second case that asserts `select.value === ""` if `patchActivityShoe` rejects (selection rolls back).
- `frontend/src/components/ActivityDetail.test.tsx`: drop the `vi.mock("./shoes/ShoeSelector", …)` stub for one new test case that renders the real `ShoeSelector`, fires `fetchActivity` returning `shoe_id: null` initially, fires `patchActivityShoe` returning `shoe_id: 7`, fires `fetchActivity` returning `shoe_id: 7` on reload, and asserts the dropdown shows shoe id 7 — no flicker visible to the user.

Migration required: **no**. The bug is in the rendered UI's handling of round-trip latency, not the schema or persistence layer. `b6e9c4a7d51f_running_shoes.py` is correct.

If the diagnostic in H1's falsification step shows the PATCH or GET is *not* echoing the new `shoe_id` on Railway specifically, switch to **H4** as the real bug — that would point at the `db.refresh` semantics under Postgres + asyncpg with the FK-cascade-on-set-null column. The fix in that case would be to skip the refresh and read `payload.shoe_id` back into the response payload directly (since we just committed it).

## 5. Out-of-scope cleanup spotted

(Recording, not fixing — orchestrator can spin these off.)

- `AGENTS.md` claims the "current head" is `e1a3b7d2c9f4`, but `b6e9c4a7d51f` (shoes) has been merged on top of it. The doc note explicitly says "Confirm anytime: `alembic heads`" — but the dangling stale value invites future agents to make bad assumptions.
- `frontend/src/components/shoes/ShoeSelector.tsx:154` uses inline `style={{ flex: 1, maxWidth: 360 }}` and a mix of CSS variables and hard-coded sizes; this is inconsistent with the Tailwind-plus-tokens convention called out in AGENTS.md "Stack" section. No functional impact.
- `frontend/src/components/ActivityDetail.tsx:152-157` passes `source={activity.source ?? null}` but `frontend/src/api/activities.ts:182-192` documents that the `?source=` query is ignored by the backend's PATCH endpoint (because PATCH dual-resolves). The plumbing is dead code on the wire.
- `frontend/src/components/shoes/ShoeSelector.tsx:167` renders `<option value={currentShoeId ?? ""} disabled>` for the retired-tag case. Some browsers (esp. iOS Safari) refuse to set a `<select>`'s value to a `disabled` `<option>`, which can cause the select to fall back to the first non-disabled option (i.e. "— None —") even when `currentShoeId` is the retired one. This is a *separate* latent bug from H1 and worth its own fix once H1 is in.
- `backend/routers/activities.py:291-362`: the PATCH `/shoe` endpoint does Strava-first dual resolution but does not accept the `?source=` disambiguator, unlike the GET. On ID collisions between a Strava `Activity` and an Apple `Workout`, the user could view the Apple side via `?source=apple_health` and tag a shoe that actually lands on the Strava row. The GET would then still show `shoe_id: null` on the Apple-rendered detail — a different but related "tag doesn't appear" symptom. Worth a follow-up.
- `frontend/src/components/shoes/ShoeSelector.tsx:54-67`: `handleChange` calls `onChange()` without awaiting it. Since `onChange` is `reload` (async), any refetch error is swallowed. Not the cause of the reported bug, but degrades observability.
