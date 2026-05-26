# Running Shoe Mileage — Frontend Plan

Companion to `docs/plans/running-shoe-mileage.md`. Backend (PR #65, commit `6fd783b`) is merged. This plan ships only the UI: settings entry, `/shoes` list + detail, create/edit/retire flows, the activity-detail shoe selector, and the empty-state inline-create flow.

## 1. Summary

- Surface a "Running shoes" entry from `/settings`.
- New `/shoes` list page with active/retired toggle, per-card progress bars (amber at >=80%, red at >=100%), and an "Add shoe" CTA.
- New `/shoes/:id` detail page with metadata header, progress to target, tagged-activity list (paginated), inline Retire/Unretire with confirmation modal.
- Create/Edit forms (modal) backed by `POST /api/shoes` and `PATCH /api/shoes/{id}`.
- Shoe selector slot on `ActivityDetail` (Strava + Apple) that PATCHes `/api/activities/{id}/shoe`.
- Empty-state inline-create flow: from the activity detail selector, if `GET /api/shoes` returns `[]`, user can create a shoe in-place and the new id is auto-tagged onto the current activity in one save.
- Distance display reuses `useUnits` (km vs mi); the API contract stays in meters end-to-end (see open question 1 of the backend plan).

## 2. Scope

**In (P0):**
- Settings entry card linking to `/shoes`.
- `/shoes` list page (active default, retired toggle, empty state, add-shoe CTA, per-card progress bar + warning chip).
- `/shoes/:id` detail page (header, progress, tagged-activities list with `limit/offset` pagination, retire/unretire, edit).
- `ShoeForm` modal used for both create and edit.
- `RetireConfirmModal`.
- `ShoeSelector` row on `ActivityDetail.tsx` (writes `/api/activities/{id}/shoe`).
- Inline-create flow inside `ShoeSelector` when the active-shoe list is empty, chaining `POST /api/shoes` -> `PATCH /api/activities/{id}/shoe` without leaving the page.
- Tests colocated next to each new component/page.

**Out / deferred (P1+):**
- Retroactive sweep view ("tag last 90 days of runs").
- Wear suggestion / auto-suggest UI.
- Drag-reorder shoe cards.
- Notifications when a shoe crosses 80%.
- "Duplicate shoe" affordance.

## 3. Data model

None (frontend only). TypeScript types live with the new API client (see Section 6).

## 4. Affected surfaces

| surface | change | files |
|---|---|---|
| `frontend/src/api/` | new shoes API client | `frontend/src/api/shoes.ts` (new) |
| `frontend/src/api/` | extend activity tagger | `frontend/src/api/activities.ts` (add `patchActivityShoe`, extend `ActivitySummary` / `ActivityDetail` with `shoe_id: number \| null`) |
| `frontend/src/hooks/` | shoes query hooks | `frontend/src/hooks/useShoes.ts` (new) |
| `frontend/src/pages/` | shoes list page | `frontend/src/pages/Shoes.tsx` (new) |
| `frontend/src/pages/` | shoe detail page | `frontend/src/pages/ShoeDetail.tsx` (new) |
| `frontend/src/components/shoes/` | shoe feature folder | new directory (matches `components/settings/`, `components/lifting/`) |
| `frontend/src/components/shoes/ShoeCard.tsx` | per-shoe list-card | new |
| `frontend/src/components/shoes/ShoeProgressBar.tsx` | reusable progress bar with status colors | new |
| `frontend/src/components/shoes/ShoeStatusToggle.tsx` | active/retired segmented control | new |
| `frontend/src/components/shoes/ShoeForm.tsx` | create + edit form (modal body) | new |
| `frontend/src/components/shoes/ShoeFormModal.tsx` | dialog shell wrapping ShoeForm | new |
| `frontend/src/components/shoes/RetireConfirmModal.tsx` | confirm modal for retire | new |
| `frontend/src/components/shoes/ShoeActivitiesList.tsx` | tagged-activity table with pagination | new |
| `frontend/src/components/shoes/ShoeSelector.tsx` | dropdown used on activity detail, owns empty-state inline create | new |
| `frontend/src/components/shoes/ShoeTypeBadge.tsx` | small chip rendering `everyday`/`workout`/`race`/`long_run`/`trail` | new |
| `frontend/src/components/settings/ShoesSettingsCard.tsx` | settings entry-point card | new |
| `frontend/src/pages/Settings.tsx` | mount `<ShoesSettingsCard />` next to existing sections | modified |
| `frontend/src/components/ActivityDetail.tsx` | wire `<ShoeSelector>` into the right rail (Run/Hike/Walk sport views) | modified |
| `frontend/src/App.tsx` | register `/shoes` and `/shoes/:id` under `AppShell` | modified |
| `frontend/src/lib/shoeFormatting.ts` | distance/percent display helpers tied to `useUnits` | new |

Folder-structure decision: `pages/Shoes.tsx` + `pages/ShoeDetail.tsx` mirror `History`, `Profile`, and `Record` (top-level routed views), with the feature components under `components/shoes/` like `components/lifting/`. This matches the convention better than parking everything under `components/shoes/` (the latter is used when there is no dedicated route, e.g. `components/sleep/`).

## 5. External integration

None. No new third-party APIs, OAuth flows, or webhooks. Skip `integration-researcher`.

## 6. API surface (frontend client)

All requests use `fetchJson` from `frontend/src/api/http.ts`. Types track the Pydantic shapes in `backend/routers/shoes.py:35-87`.

### `frontend/src/api/shoes.ts`

```ts
export type ShoeStatus = "active" | "retired";
export type ShoeType = "everyday" | "workout" | "race" | "long_run" | "trail";
export type ShoeListFilter = "active" | "retired" | "all";

export interface Shoe {
  id: number;
  name: string;
  brand: string | null;
  model: string | null;
  shoe_type: ShoeType;
  status: ShoeStatus;
  total_usable_distance_m: number | null;
  purchased_on: string | null;            // ISO date (YYYY-MM-DD)
  retired_at: string | null;              // ISO datetime
  notes: string | null;
  created_at: string;                     // ISO datetime
  updated_at: string;                     // ISO datetime
  cumulative_distance_m: number;          // server-computed; 0 when no tagged activities
  percent_used: number | null;            // null when total_usable_distance_m is null; can exceed 100
}

export interface ShoeDetail extends Shoe {
  tagged_activity_count: number;
}

export interface ShoeCreate {
  name: string;                           // 1..120
  brand?: string | null;                  // <= 64
  model?: string | null;                  // <= 120
  shoe_type?: ShoeType;                   // defaults to "everyday" server-side
  total_usable_distance_m?: number | null; // > 0
  purchased_on?: string | null;
  notes?: string | null;
}

export interface ShoePatch {
  name?: string;
  brand?: string | null;
  model?: string | null;
  shoe_type?: ShoeType;
  total_usable_distance_m?: number | null;
  purchased_on?: string | null;
  notes?: string | null;
  // NOTE: status is intentionally NOT here. Retire/unretire are verb endpoints.
}

export interface ShoeActivityRow {
  id: number;
  source: "strava" | "apple";
  name: string | null;
  sport_type: string | null;
  start_date: string | null;
  distance_m: number | null;
}

export interface ShoeActivitiesPage {
  items: ShoeActivityRow[];
  total: number;
}

export function listShoes(filter: ShoeListFilter = "active"): Promise<Shoe[]>;
export function getShoe(id: number): Promise<ShoeDetail>;
export function createShoe(payload: ShoeCreate): Promise<Shoe>;
export function patchShoe(id: number, payload: ShoePatch): Promise<Shoe>;
export function retireShoe(id: number): Promise<Shoe>;
export function unretireShoe(id: number): Promise<Shoe>;
export function listShoeActivities(
  id: number,
  opts?: { limit?: number; offset?: number },
): Promise<ShoeActivitiesPage>;
```

### `frontend/src/api/activities.ts` additions

```ts
export function patchActivityShoe(
  activityId: number,
  shoeId: number | null,
  source?: ActivitySource | null,
): Promise<ActivityDetail>;
// PATCH /api/activities/{id}/shoe with body { shoe_id }; passes ?source= when caller supplies it,
// mirroring fetchActivity in the same file (lines 136-139).
```

Also extend `ActivitySummary` and `ActivityDetail` with `shoe_id: number | null` so the selector can render the current selection straight from the existing `useApi(["activities","detail",...])` cache.

Source-of-truth crosswalk: backend Pydantic shapes are `ShoeOut` / `ShoeDetailOut` / `ShoeCreate` / `ShoePatch` at `backend/routers/shoes.py:63-87`. The activity tagger body is `ActivityShoePatch` at `backend/routers/shoes.py:86-87`, served by the activity-tag endpoint in `backend/routers/activities.py` (per Section 6 of the backend plan).

## 7. Service / business logic (frontend hooks + state)

**Decision: use React Query (`useApi`) for reads, plain `fetchJson` for mutations + an explicit `queryClient.invalidateQueries` after each mutation.**

Rationale: React Query is already the de-facto pattern. `frontend/src/hooks/useApi.ts` wraps it, `renderWithQuery` provides the test wrapper, and `useApi(["activities","detail",id])` is the very cache the shoe selector needs to invalidate after a PATCH. Adopting React Query here keeps the activity-detail page in sync for free (instead of plumbing a manual `reload` callback down through `ActivityDetail` -> sport view -> selector). The `useGoals`-style imperative `reload` works for the single-page settings sections but would force us to either prop-drill `reload` into the selector or duplicate state, and it would not refresh the `/shoes` list when a shoe is tagged or retired from `ActivityDetail`. The cost is one extra hook file; the benefit is automatic cross-route freshness.

`frontend/src/hooks/useShoes.ts` exports:
- `useShoesList(filter)` -> `useApi(["shoes","list",filter], () => listShoes(filter))`
- `useShoeDetail(id)` -> `useApi(["shoes","detail",id], () => getShoe(id))`
- `useShoeActivities(id, page)` -> `useApi(["shoes","activities",id,page], () => listShoeActivities(id, page))`
- `invalidateShoes(queryClient)` helper that invalidates `["shoes"]` and `["activities"]` after any mutation (single call site for the rule "shoes changed -> the activity-detail shoe row may be stale").

Mutations stay imperative (a plain async function + local `busy/error` state, like `GoalForm.tsx:22-41`). After success, call `invalidateShoes(queryClient)`. Do not introduce `useMutation` for P0 — keep the surface area minimal and consistent with `GoalRow`/`GoalForm`.

`frontend/src/lib/shoeFormatting.ts`:
- `formatShoeDistance(meters, units)` — thin wrapper over `formatDistance` from `useUnits`; chooses 0 vs 1 decimal as appropriate for shoe totals (the existing helper hides decimals below the unit threshold which is fine here).
- `formatPercentUsed(percent)` — `"—"` when null, `"42%"` when defined; rounding rule = `Math.round`.
- `progressTone(percent)` — returns `"ok" | "warn" | "danger"` (`<80`, `>=80 && <100`, `>=100`). Drives the chip and bar fill color, matches §11 of backend plan.
- `parseDistanceInput(value, units)` — converts UI input (e.g. `500` km or `300` mi) to meters before POST; supports the unit toggle on the form.

## 8. Migration tasks

None — frontend only.

## 9. Tests to add

Colocated with their components. Patterns mirror `frontend/src/components/GoalsSection.test.tsx`, `frontend/src/pages/Settings.test.tsx`, and `frontend/src/components/ActivityDetail.test.tsx`. All use `renderWithQuery` from `frontend/src/test/renderWithQuery.tsx` and mock `../api/shoes` + `../api/activities`.

### `frontend/src/pages/Shoes.test.tsx`
- `renders empty state with primary "Add your first shoe" CTA when listShoes returns []`
- `renders one card per active shoe with name, type badge, and progress bar`
- `clicking Retired toggle re-fetches with status=retired`
- `clicking Add shoe opens the ShoeFormModal`
- `creating a shoe via the modal triggers listShoes invalidate and the new card renders`
- `cards with percent_used >= 80 show the amber warning chip`
- `cards with percent_used >= 100 show the red overdue chip`
- `clicking a card navigates to /shoes/:id`

### `frontend/src/pages/ShoeDetail.test.tsx`
- `renders header with name, brand/model, and shoe_type badge`
- `renders progress bar with cumulative_distance_m vs total_usable_distance_m`
- `omits progress bar when total_usable_distance_m is null and renders "no target" placeholder`
- `clicking Edit opens prefilled ShoeFormModal`
- `submitting edit calls patchShoe and refreshes detail`
- `clicking Retire opens RetireConfirmModal; confirming calls retireShoe`
- `retired shoe shows Unretire button that calls unretireShoe`
- `renders first page of tagged activities`
- `Next page calls listShoeActivities with offset=limit`
- `shoes with zero tagged activities show "No activities tagged yet"`

### `frontend/src/components/shoes/ShoeCard.test.tsx`
- `renders name + brand + model when present`
- `omits brand/model gracefully when null`
- `renders percent_used "—" when total_usable_distance_m is null`
- `respects unit system (km vs mi)` via mocked `useUnits`

### `frontend/src/components/shoes/ShoeProgressBar.test.tsx`
- `applies "ok" tone below 80%`
- `applies "warn" tone in [80, 100)`
- `applies "danger" tone at >= 100%`
- `renders nothing or placeholder when total target is null`

### `frontend/src/components/shoes/ShoeForm.test.tsx`
- `submits create payload trimming whitespace; brand/model/notes coerced to null when empty`
- `converts km/mi input to meters before POST` (covers `parseDistanceInput`)
- `rejects empty name; disables Save button`
- `rejects negative total_usable_distance_m client-side`
- `Edit mode prefills all fields including shoe_type and purchased_on`

### `frontend/src/components/shoes/ShoeSelector.test.tsx`
- `renders current shoe by id and "None" when activity.shoe_id is null`
- `selecting a shoe calls patchActivityShoe(activityId, shoeId, source)`
- `selecting "None" calls patchActivityShoe with shoe_id=null`
- `retired shoes are not in the dropdown options`
- `empty-state: when listShoes returns [], dropdown renders an "Add a shoe" affordance`
- `empty-state inline create: clicking "Add a shoe" opens form; on save it POSTs createShoe, then PATCHes activity with the new id, then invalidates ["activities","detail",id] and ["shoes"]`
- `shows error and keeps form open when createShoe rejects`
- `shows error and keeps the previous shoe_id when patchActivityShoe rejects`

### `frontend/src/components/shoes/RetireConfirmModal.test.tsx`
- `confirms triggers onConfirm`
- `cancel closes without calling onConfirm`
- `disables confirm button while busy`

### `frontend/src/components/settings/ShoesSettingsCard.test.tsx`
- `renders link/card pointing to /shoes`

### `frontend/src/pages/Settings.test.tsx` (modified)
- Add a stub `vi.mock("../components/settings/ShoesSettingsCard", ...)` and an `expect(screen.getByText("Shoes stub")).toBeInTheDocument()` assertion (matches the existing GoalsSection stub pattern at `frontend/src/pages/Settings.test.tsx:5-7`).

### `frontend/src/components/ActivityDetail.test.tsx` (modified)
- Add `vi.mock("../components/shoes/ShoeSelector", ...)` stub.
- Assert the stub renders on `Run` / `Hike` / `Walk` sport views and is omitted on `Strength` and `Ride` (per the UX decision below).

## 10. Parallelism plan

```
phase 1 (skipped):
  - integration-researcher    -> no external integration
  - db-migrator               -> no migration
phase 2 (sequential, frontend only):
  - frontend-engineer         -> api client + hooks + pages + components + tests
                                 (no backend-engineer; backend already shipped in PR #65)
phase 3 (parallel — review):
  - code-reviewer
  - skip security-reviewer    (no new auth/data egress surfaces)
  - skip migration-safety-checker (no migration)
  - skip performance-sentinel (expected diff < ~1500 LOC, no hot path changes)
phase 4 (sequential):
  - test-runner               -> npm run typecheck, npm run build, vitest
  - PR
```

## 11. Open questions

1. **Form units.** Backend stores `total_usable_distance_m`. The form should accept the user's preferred unit via `useUnits`: imperial users type "500" and we send `500 * 1609.344`; metric users type "800" and we send `800000`. Confirm — open question #1 of the backend plan flagged this as a UI-side concern. Recommendation: bind to `useUnits` and show the active unit suffix; no canonical-unit pinning.
2. **Default lifespan suggestion.** Backend leaves `total_usable_distance_m` null by default. Should the form pre-fill a sensible default per `shoe_type` (e.g. race=400 km, everyday=800 km) so the progress bar is usable out of the box? Recommend NO for P0: a placeholder hint string ("typical: 500–800 km") in the input is enough and avoids opinionated defaults — matches open question #3 of the backend plan.
3. **Where does the shoe selector show?** Recommendation: only on Run / Hike / Walk sport views inside `ActivityDetail.tsx` (the `ActivityDetailRun` branch in `frontend/src/components/ActivityDetail.tsx:194-198`). Ride and Strength stay out. Confirm.
4. **Empty-state copy.** "Add your first shoe" vs "Track a new pair" — pick one for the list empty state, the settings entry, and the in-selector affordance so all three match.
5. **Pagination size for tagged activities.** Backend max `limit=200`, default `50`. Recommend `limit=20` in the UI (matches History page density). Confirm.
6. **Retired-shoe sort.** Default order from backend is `created_at desc`. For the Retired toggle, do we want `retired_at desc` instead so most-recently-retired comes first? Not currently supported — would require either client-side sort or a backend query-param. Recommend client-side sort by `retired_at desc` for P0; flag for backend follow-up if it gets heavy.
7. **Confirmation strength on retire.** Modal vs `window.confirm`. The existing `GoalRow` uses `window.confirm` (`vi.stubGlobal("confirm", ...)` in `Settings.test.tsx:76`). Recommend a real modal (`RetireConfirmModal`) for retire because the backend stamps `retired_at` as a side-effect and the action is functionally permanent for that pair — give the user the explanation the spec calls out: "They'll be hidden from the active list but history is preserved."

---

## A. Settings entry point (UX)

**Recommendation:** a link card, not an inline section.

- The user said "Add a 'Gear' or 'Shoes' link." Inline editing on Settings (`GoalsSection`-style) would balloon the settings page once shoes have edit/retire/tagging UIs, and the shoe detail page already needs its own route for the tagged-activity list anyway.
- New component `frontend/src/components/settings/ShoesSettingsCard.tsx`: renders inside `Settings.tsx` between `<GoalsSection />` and `<SyncSection />`. Visual: `card` class, title "Running shoes", short subtitle ("Track mileage on each pair, retire old ones, tag them on runs."), and a primary button "Manage shoes" -> `react-router-dom` `<Link to="/shoes">`.
- A small live summary in the card is cheap and motivating: "3 active · Vaporfly 3 at 78%". Uses `useShoesList("active")` and picks the highest-`percent_used` non-null entry. Skip if `listShoes` returns `[]` and show "No shoes yet" + the same Manage link.

## B. `/shoes` list page (UX)

Route: `/shoes` under `<AppShell>` (matches `/history`, `/profile`). Element: `<Shoes />`.

Layout, top to bottom:
1. **Page header** — "Running shoes" + a subtitle "Tag a shoe on a run to track its mileage."
2. **Toolbar row** — segmented control (`ShoeStatusToggle`) [Active | Retired], pushed left; "Add shoe" button (primary) pushed right.
3. **Cards grid** — `ShoeCard` per shoe. One card per row on narrow viewports, two columns on wide. Each card shows:
   - Row 1: name (bold, links to `/shoes/:id`), `ShoeTypeBadge`.
   - Row 2 (muted): brand · model (if either present).
   - Row 3: `ShoeProgressBar` — fills `cumulative_distance_m / total_usable_distance_m`. Tones: `<80%` neutral/green, `80–99%` amber chip "Approaching end of life", `>=100%` red chip "Overdue — consider retiring". When `total_usable_distance_m` is null, render no bar — just `"312 km logged · no target set"`.
   - Row 4 (small): purchased on (if set), tagged-activity count (only on detail; skip on the card to keep the list query lean).
   - Card has a hover-only "Edit" pencil that opens `ShoeFormModal` in edit mode, and a kebab with "Retire" / "Unretire".
4. **Empty state** — when `listShoes("active")` returns `[]`: full-width onboarding card centered, title "No shoes yet", subtitle "Track each pair so you know when to replace them.", primary CTA "Add your first shoe" that opens `ShoeFormModal`. The toolbar's "Add shoe" button stays visible too.
5. **Retired empty state** — when the toggle is `Retired` and that filter returns `[]`: muted helper "Nothing retired yet." (no CTA).

Distance display defers to `useUnits` via `formatShoeDistance`. The toggle in the page header is not duplicated here — it lives globally (per `useUnits`).

## C. Shoe detail page (UX)

Route: `/shoes/:id` under `<AppShell>`. Element: `<ShoeDetail />` (`frontend/src/pages/ShoeDetail.tsx`).

Layout:
1. **Header**:
   - Back link to `/shoes`.
   - Name (h1), `ShoeTypeBadge`, status pill (`active` / `retired`).
   - Brand · Model row (muted).
   - Right-aligned action cluster: `Edit` (opens `ShoeFormModal` prefilled), `Retire` (active only) / `Unretire` (retired only).
2. **Stat strip** — three tiles:
   - Cumulative distance (`formatShoeDistance(cumulative_distance_m, units)`).
   - Lifespan target (`formatShoeDistance(total_usable_distance_m, units)` or `"No target"`).
   - Percent used (`formatPercentUsed(percent_used)` + the tone chip).
3. **Progress bar** — wide `ShoeProgressBar`, same color rules as the list card.
4. **Metadata block** — purchased on, retired on (when retired), notes (multi-line).
5. **Tagged activities** — `ShoeActivitiesList`. Table-like:
   - Columns: date, name, sport_type, distance.
   - Empty state: "No activities tagged yet. Open a run and pick this shoe from the shoe selector."
   - Pagination: `page-size=20`, `<Prev/Next>` buttons driven by the `total` field. Stable until we need infinite scroll.

**Retire flow:** clicking `Retire` opens `RetireConfirmModal`. Body: "Retire {name}? It will be hidden from the active list, but its history and tagged activities are preserved. You can unretire it later from the Retired filter." Confirm calls `retireShoe(id)`, closes the modal, refetches `["shoes","detail",id]` and invalidates `["shoes","list"]`. Idempotency is handled server-side (backend plan §6) — the UI only needs to refresh.

**Unretire flow:** no modal; one click calls `unretireShoe(id)` then refreshes. Reasoning: unretiring is non-destructive.

## D. Activity detail shoe selector + empty-state inline create (UX)

### Where it lives in `ActivityDetail.tsx`
The selector slots into the right-rail action stack at `frontend/src/components/ActivityDetail.tsx:144-172`, alongside `<RPECard>` and `<LocationPicker>`, **only on run-like sport views**. The `pickSportView` switch at `ActivityDetail.tsx:186-200` already separates `Ride` / `Strength` / `Run|Hike|Walk|Other`; render `<ShoeSelector>` outside the sport view but gated:

```tsx
const isFootSport = pickSportView(activity) === ActivityDetailRun;
// ... in the JSX:
{isFootSport && (
  <ShoeSelector
    activityId={activityId}
    source={activity.source ?? null}
    currentShoeId={activity.shoe_id ?? null}
    onChange={reload}
  />
)}
```

This puts it next to `<RPECard>` for Strava activities and in the same slot for Apple Health activities (RPE is hidden for Apple but the selector is not — Apple Health workouts can also be tagged per the backend dual-resolution endpoint at the activity-router PATCH endpoint).

### Steady-state interaction
- Renders as a small card: label "Shoes", a select with `"— None —"` plus one option per **active** shoe (retired shoes are filtered client-side; existing tag to a retired shoe is preserved per backend §7 — render it as a disabled-styled option with "(retired)" suffix and the current selection set to it so the user sees the truth without being able to re-select it).
- Changing the select fires `patchActivityShoe(activityId, shoeId, source)`. On success: invalidate `["activities","detail",activityId,source]` so the parent `useApi` refetches and `activity.shoe_id` updates. Optimistic update on the select itself; revert on error and show inline message.
- Selecting `"— None —"` sends `{ shoe_id: null }`.

### Empty-state inline create flow
This is the user-explicit requirement. Goal: from a run's detail page, a user with zero shoes can create one and have it tagged onto the current run **in a single save, without losing context**.

Trigger: `useShoesList("active")` resolves to `[]`. The select collapses to a single button: "+ Add a shoe".

Click expands the `ShoeSelector` in place (no full-page modal — keep the activity context visible above):

1. Inline `ShoeForm` body renders below the label. Same component used by `ShoeFormModal` (modal is just the shell). Auto-focus the name input.
2. Two buttons: "Save & tag", "Cancel".
3. On submit:
   - `const created = await createShoe(payload);`
   - `await patchActivityShoe(activityId, created.id, source);`
   - `queryClient.invalidateQueries({ queryKey: ["shoes"] })` and `queryClient.invalidateQueries({ queryKey: ["activities","detail",activityId,source] })`.
   - Collapse the form back to the normal selector; the new shoe is now the selected option.
4. Error handling: if `createShoe` fails, keep the form open with the error message — nothing is tagged yet. If `patchActivityShoe` fails after `createShoe` succeeded, the shoe still exists (so it shows in the list view); we surface "Created the shoe but failed to tag it on this run — try the dropdown above" and refresh the selector. This avoids the worst failure mode (orphaned tag pointing nowhere) and keeps the user in place.
5. The user stays on `ActivityDetail`. No navigation to `/shoes` and no full-page modal — the user explicitly called this out as a "don't lose context" flow.

Once the user has at least one active shoe, the selector renders the normal dropdown forever; the inline-create affordance is replaced by a small "+ New shoe" item at the bottom of the dropdown menu (P1, but cheap — same `ShoeForm` reuse). For P0 ship only the empty-state inline-create as required.

## Risks and rollback

- No migration, no scheduler change — production risk is bounded to the frontend bundle. A bad release shows a broken settings card or selector; the `/api/shoes` and `/api/activities/{id}/shoe` endpoints already shipped in PR #65 and are not changed here.
- Rollback: revert the PR. No data is rewritten by frontend-only changes (every mutation routes through existing backend endpoints).

`Risk: trivial` (this is a frontend-only PR with no migration; the orchestrator's migration-safety-checker is skipped).
