# Plan: History page type filter + type tag on cards

## 1. Feature summary
On the History page, users can filter the timeline by workout *type* — the existing rules-based classification (`easy | tempo | intervals | race` for runs; `recovery | endurance | mixed | race` for rides). Each history card also gains a prominent type tag (badge) next to the title, alongside the existing source pill, since the user considers type more important than source. This is a **frontend-only** change: the classification data already lives on every activity row and is already returned by the History feed endpoint, so no backend or database work is required.

## 2. Affected surfaces

| surface | change | files |
|---|---|---|
| `frontend/src/lib/` | extend filter union, `FILTERS` list, and `applyHistoryFilter`; surface `classification_type`/`classification_flags` on `HistoryEvent`; map them in `activityToEvent` | `frontend/src/lib/historyEvents.ts` |
| `frontend/src/components/history/` | render a type badge on the card next to title/source | `frontend/src/components/history/HistoryEventCard.tsx` |
| `frontend/src/components/history/` | two-tier filter UI: keep existing category/sport row, add a type sub-filter row | `frontend/src/components/history/HistoryFilters.tsx` |
| `frontend/src/pages/` | hold new filter state and pass it to filters + `applyHistoryFilter` | `frontend/src/pages/History.tsx` |
| `frontend/src/components/` | reuse existing `ClassificationBadge` for the card tag | `frontend/src/components/ClassificationBadge.tsx` (existing, likely no change) |
| `backend/` | none | — |
| `alembic/` | none | — |
| `frontend/src/api/` | none — `ActivitySummary` already carries `classification_type` + `classification_flags` | (`frontend/src/api/activities.ts` for reference only) |

## 3. Data model
No schema change. The relevant fields already exist on the `activities` table and the `ActivitySummary` API shape:
- `classification_type: ClassificationType` — `easy | tempo | intervals | race | recovery | endurance | mixed | null` (defined in `frontend/src/api/activities.ts`).
- `classification_flags: string[] | null` — e.g. `is_long`, `has_speed_component`, `has_warmup_cooldown`, `is_hilly`.
- Produced by the rules classifier `backend/services/classifier.py`.
- Already returned by the History feed: `backend/routers/dashboard.py` (`/dashboard/history`) → `list_activity_feed` (`backend/services/activity_feed.py`) → `_activity_summary` (`backend/routers/activities.py:572`), which includes `classification_type` (`:600`) and `classification_flags` (`:601`).

Important nuance for the frontend: **Apple Health workouts and strength sessions are not classified.** The Apple-only summary path sets `classification_type: None` / `classification_flags: None` (`backend/routers/activities.py:681-682`), and the classifier returns `None` for `WeightTraining`/non-run/non-ride sports. The filter and badge must treat null type as "Unclassified" and never crash on null.

No backfill needed. (Historic rows that were never classified simply show no type tag.)

## 4. External integration
None. No new clients, auth, sync, credentials, rate limits, or webhooks. `integration-researcher` is **not needed**.

## 5. Backend tasks
None. The `/dashboard/history` endpoint and `_activity_summary` serializer already expose `classification_type` and `classification_flags` (`backend/routers/activities.py:600-601`).

## 6. Frontend tasks
Ordered, each small enough for one agent run:

1. `frontend/src/lib/historyEvents.ts`
   - Add `classificationType` and `classificationFlags` to the `HistoryEvent` interface (typed off `ClassificationType` from `../api/activities`).
   - In `activityToEvent`, copy `a.classification_type` / `a.classification_flags` onto the event.
   - Add a new filter dimension for type: a separate `TypeFilterId` union (`"AllTypes" | "easy" | "tempo" | "intervals" | "race" | "recovery" | "endurance" | "mixed" | "unclassified"`) and a `TYPE_FILTERS` list, kept independent from the existing sport/category `FilterId`. Do **not** overload the existing `FilterId`.
   - Add `applyTypeFilter(events, typeFilter)` that matches `event.classificationType`; map `null` to the `"unclassified"` bucket. Keep existing category/sport semantics intact.

2. `frontend/src/components/history/HistoryFilters.tsx`
   - Render a second pill row for `TYPE_FILTERS` below the existing sport row, following the existing pill styling/markup. Wire `activeType` + `onTypeChange` props mirroring the existing `active`/`onChange` pattern.

3. `frontend/src/pages/History.tsx`
   - Add `const [activeType, setActiveType] = useState<TypeFilterId>("AllTypes")`.
   - Pass `activeType` + `setActiveType` into `HistoryFilters`.
   - Apply both filters in the `useMemo` — compose existing `applyHistoryFilter` with the new type filter.
   - A non-`AllTypes` type filter narrows to activity events that match, which naturally drops sleep/strength rows.

4. `frontend/src/components/history/HistoryEventCard.tsx`
   - Render a type tag next to the title. Reuse the existing `ClassificationBadge` passing `event.classificationType` and `event.classificationFlags` (use its `compact` prop to keep the card tight).
   - Place it in the title row so it sits beside `<SourceBadge>`. Per the user, type is more important than source — order it before the source pill and let source remain the smaller/secondary pill.
   - Render nothing when `classificationType` is null so Apple/strength/sleep cards aren't cluttered.

## 7. Migration tasks
No migration. The `classification_type` and `classification_flags` columns already exist and are already serialized by the History endpoint. No new tables, no `op.execute`, no alters.

**`Risk: trivial`** (no schema change at all). The orchestrator does **not** need to spawn `migration-safety-checker`.

## 8. Tests to add
Frontend (Vitest, alongside existing specs):
- `frontend/src/lib/historyEvents.test.ts` — `activityToEvent` carries `classificationType`/`classificationFlags`; type-filter function filters runs by `intervals`/etc.; `null` classification maps to `"unclassified"`; `"AllTypes"` returns everything; type filter excludes sleep/strength rows.
- `frontend/src/components/history/HistoryEventCard.test.tsx` — renders the type tag when set; renders no type tag (no crash) when null; type tag appears alongside the source pill.
- `frontend/src/pages/History.test.tsx` — selecting a type pill narrows the rendered cards.

Backend: none.

## 9. Parallelism plan
```
phase 1 (single agent, sequential within file deps):
  - frontend-engineer:
      step 1  historyEvents.ts        (types + filter logic)   -- prerequisite
      step 2  HistoryFilters.tsx       (depends on TYPE_FILTERS / TypeFilterId)
      step 3  History.tsx              (depends on steps 1-2)
      step 4  HistoryEventCard.tsx     (depends on step 1 HistoryEvent fields)
    Note: no integration-researcher, no db-migrator, no backend-engineer needed.

phase 2 (sequential, depends on phase 1):
  - test-runner    -> vitest (frontend) + npm run typecheck + npm run build
  - code-reviewer
```
There is no backend or migration track to parallelize against.

## 10. Risks and rollback
- **Production risk: very low.** Frontend-only, no migration, no Railway DB impact, no API contract change.
- Main functional risk is **null-handling**: Apple Health workouts, strength sessions, and sleep rows have `classification_type === null`. Mitigated by the explicit `"unclassified"` mapping and null-guarded badge (tests cover this).
- Secondary risk: historic Strava rows that were never classified show as unclassified. Expected; out of scope to backfill (a `scripts/classify_all.py` run would populate older rows).
- **Rollback:** revert the PR. No data migration to undo.
