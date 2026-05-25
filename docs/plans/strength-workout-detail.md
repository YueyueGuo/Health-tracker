# Strength Training Workout Detail / Review Page

## 1. Feature summary
A dedicated detail page for a completed manual strength training session, reachable by tapping a Strength row on the home page (`YesterdayActivityCard`, `frontend/src/components/dashboard/YesterdayActivityCard.tsx`) or in History (`frontend/src/components/history/HistoryEventCard.tsx`). The page shows a top summary card (date, duration, total volume, exercise count, set count), per-exercise cards with each set's weight × reps × RPE × HR, and a visual superset grouping where exercises were performed back-to-back. Read-only review; editing remains in `/record`.

## 2. Gaps analysis (do this first — it's the user's explicit ask)

### What exists today
- **One model only**: `StrengthSet` (`backend/models/strength.py:20-57`). No `LiftingSession`, no `Exercise`, no `SupersetGroup`. A "session" is the *implicit grouping by `date`*, computed at read time (`backend/services/strength.py:44-77`, `80-164`).
- **Per-set fields persisted**: `id`, `activity_id` (nullable FK → `activities`), `date`, `exercise_name` (free-text string, 100 chars), `set_number`, `reps`, `weight_kg`, `rpe`, `notes`, `performed_at` (added in migration `b3c6d9e8a1f4`), `created_at`, `updated_at`.
- **Endpoints** (`backend/routers/strength.py`):
  - `GET /api/strength/sessions?limit=` — list aggregates (`date, exercise_count, total_sets, total_volume_kg, activity_id`).
  - `GET /api/strength/session/{session_date}` — **already a detail endpoint** keyed by ISO date; returns `sets[]`, `exercises[]` (with `max_weight, total_volume, est_1rm`), optional `hr_curve[]` + `activity_start_iso` when the linked Strava activity's streams are cached (`backend/services/strength_hr.py:105-173`).
  - `POST /api/strength/sets`, `PATCH /api/strength/sets/{id}`, `DELETE /api/strength/sets/{id}`.
  - `GET /api/strength/progression/{exercise_name}`, `GET /api/strength/exercises`.
- **Aggregates already computed in Python** (not SQL): `total_volume`, `max_weight`, `est_1rm` (Epley, `backend/services/strength.py:22-38`). HR averaging per set is in `backend/services/strength_hr.py:39-78`.
- **Frontend types** match (`frontend/src/api/strength.ts:5-56`). `fetchStrengthSessionOptional(date)` already exists.
- **Superset awareness in UI input only**: `ExerciseDraft.linkedToNext: boolean` (`frontend/src/components/record/types.ts:14-16`) drives a visual chain in the recording flow (`ExerciseCard.tsx:127-143`). **It is dropped in `buildPayload` (`frontend/src/pages/Record.tsx:218-247`) and never reaches the API.** This is the core schema gap.
- **No detail route on frontend**: History dispatches Strength rows via `navigateTo: s.activity_id != null ? '/activities/${s.activity_id}' : null` (`frontend/src/lib/historyEvents.ts:173-189`). Sessions without a linked Strava activity have **no detail page at all**. Home's `YesterdayActivityCard` shows an inline summary but has no tap-through.
- **Workout-level fields missing**: no `duration_seconds`, `started_at`/`ended_at`, no muscle-group tags. Duration today is derived only from the linked Strava activity (`activity.moving_time`) — orphan sessions have none.

### What's missing
1. **Supersets**: no persistence. Adding requires a schema change.
2. **Session-level metadata**: no `duration_seconds`, no name/title, no body-part tagging. For orphan (un-linked) sessions, there's no duration source at all — the workout-level "duration" tile on the visual mock needs either (a) `started_at`/`ended_at` columns on `strength_sets` (or a session row) or (b) compute from `min(performed_at)` and `max(performed_at)` across the session as a heuristic.
3. **Exercise dictionary**: `exercise_name` is free text; there's no `Exercise` table, no muscle-group mapping. The visual mock probably groups by muscle — assume out of scope for v1; revisit later (open question).
4. **Detail route + page on the frontend**.
5. **Navigation wiring** from home + history (currently dead-ends for orphan sessions).
6. **Bug B (lifting save) precondition**: `docs/audit-001-handoff.md` documents this as a known surface and `tests/test_routers/test_strength.py:34-77` is the regression gate. AGENTS.md claims head is `c2f7a4e91b85`; the `b3c6d9e8a1f4` migration that adds `performed_at` is in its ancestor chain, so the schema is current. **Assume Bug B is fixed on `main` for this plan**, but flag in risks if not.

### Open questions (flag to integration-researcher / spec author, but ship with defaults)
- Should session duration use stored `started_at`/`ended_at`, or derive from `performed_at` min/max? **Default: add `started_at`/`ended_at` nullable on `strength_sets`** (filled by the recording flow's `SessionHeader` timer), fall back to `performed_at` range.
- Does the user want PR/1RM badges in the header? **Default: include `est_1rm` per exercise (already computed) and a "Top set" badge per card — no cross-session PR comparison in v1.**
- Should the detail page be editable inline? **Default: read-only review; tap a set to deep-link back to `/record?date=` for edits (deferred follow-up).**
- Muscle-group / body-part filter? **Default: out of scope for v1.**

## 3. Affected surfaces

| Surface | Change | Files |
|---|---|---|
| `backend/models/` | Add superset + duration columns | `backend/models/strength.py` |
| `backend/routers/strength.py` | Extend `StrengthSetInput` / `StrengthSetPatch` with superset_group_id + started_at/ended_at; allow saving these | `backend/routers/strength.py` |
| `backend/services/strength.py` | Extend `session_summary` payload: `duration_sec`, ordered `exercises[]` carrying `superset_group_id` and `order_index`; compute totals in Python (existing pattern) | `backend/services/strength.py` |
| `alembic/` | New migration off head `c2f7a4e91b85`: add 4 nullable columns to `strength_sets` | new revision file under `alembic/versions/` |
| `frontend/src/App.tsx` | Add route `/workouts/lifting/:date` inside `<AppShell>` | `frontend/src/App.tsx` |
| `frontend/src/api/strength.ts` | Extend `StrengthSet` / `StrengthSetInput` / `ExerciseBreakdown` / `StrengthSessionDetail` types | `frontend/src/api/strength.ts` |
| `frontend/src/pages/` | New `LiftingDetail.tsx` page | `frontend/src/pages/LiftingDetail.tsx` (new) |
| `frontend/src/components/lifting/` (new dir) | `SessionSummaryCard`, `ExerciseDetailCard`, `SupersetBracket`, `SetRow` | new files |
| `frontend/src/lib/historyEvents.ts` | Update `strengthToEvent` → `navigateTo: '/workouts/lifting/${s.date}'` always | `frontend/src/lib/historyEvents.ts:173-189` |
| `frontend/src/components/dashboard/YesterdayActivityCard.tsx` | Wrap StrengthSection in a tap target → `/workouts/lifting/{date}` | `frontend/src/components/dashboard/YesterdayActivityCard.tsx:173-219` |
| `frontend/src/pages/Record.tsx` | Send `superset_group_id` + `started_at`/`ended_at` in `buildPayload` (derive group_ids from runs of `linkedToNext`) | `frontend/src/pages/Record.tsx:218-247, 434-457` |
| `tests/` | New router + service + frontend tests | see §8 |

## 4. Data model

New columns on `strength_sets` (all nullable, backward compatible):

| Column | Type | Notes |
|---|---|---|
| `superset_group_id` | `Integer NULL` | Sets/exercises that share a value were performed in a superset. Scoped to a session (date). Null = standalone. |
| `order_index` | `Integer NULL` | Display order across the session. Lets the detail page render exercises in the recorded sequence rather than alphabetical. Falls back to `min(performed_at)` per exercise. |
| `started_at` | `DateTime(timezone=True) NULL` | Session start, stamped by the recorder's "Start" button. Optional. |
| `ended_at` | `DateTime(timezone=True) NULL` | Session end, stamped by the recorder's "Finish" tap. Optional. |

**Index**: add `ix_strength_sets_date_superset` on `(date, superset_group_id)` — supports the per-session grouped read pattern. (Not strictly necessary at current data volume but cheap.)

No new tables. No backfill required — all new columns are nullable; existing rows render as standalone (no superset, alphabetical order, duration falls back to `performed_at` min/max).

**Relation to existing tables**: `strength_sets.activity_id` continues to FK `activities.id` (`ondelete=SET NULL`); the Strava `WeightTraining` `moving_time` is still the preferred source for duration when linked.

## 5. External integration

**Empty.** No third-party APIs. Strava integration is already in place via `activity_id` linking and read-only HR-stream attach (`backend/services/strength_hr.py`). No webhooks, no OAuth changes, no new secrets. Confirm explicitly in the PR description.

## 6. Superset modeling — design decision

**Recommendation: (a) `superset_group_id: int | None` on `strength_sets`.**

Rationale: a session never spans more than ~10 exercises; a separate `SupersetGroup` table would add a join, a write path, and an FK-cascade question for a property that's effectively a tag. The integer is scoped to the session (date), assigned by the client when saving (e.g. monotonic 1, 2, 3 from `linkedToNext` runs), and lets the frontend render a superset by grouping adjacent exercises with the same id — matching the existing `ExerciseCard` linked-border visual idiom. If we later want richer metadata (rest target, round count), we can promote without a destructive migration by adding columns to a future `superset_groups` table keyed by `(date, superset_group_id)`.

## 7. Backend tasks

Each is sized for one agent run.

1. **Model**: add the four columns to `backend/models/strength.py` (`superset_group_id`, `order_index`, `started_at`, `ended_at`).
2. **Migration**: see §9. Adds the columns + composite index; no data backfill.
3. **Pydantic schemas** in `backend/routers/strength.py`:
   - Extend `StrengthSetInput` with `superset_group_id: int | None = None`, `order_index: int | None = None`.
   - Extend `StrengthSessionCreate` with `started_at: datetime | None = None`, `ended_at: datetime | None = None`. The POST handler writes those onto **each** row of the session (denormalized; cheap, avoids a parent table). Use `_normalize_performed_at` for tz attach.
   - Extend `StrengthSetPatch` with `superset_group_id`, `order_index`.
4. **`session_summary`** in `backend/services/strength.py:80-164`:
   - Order exercises by `min(order_index)` per exercise, falling back to `min(performed_at)`, then `exercise_name`.
   - For each exercise emit `superset_group_id` (the modal value across that exercise's sets) and `order_index`.
   - Compute `duration_sec`: prefer `ended_at - started_at` (take max/min across the session's rows since they're denormalized), else `max(performed_at) - min(performed_at)`, else `None`.
   - Add aggregate fields to the top-level payload: `total_sets`, `total_volume_kg`, `total_reps`, `exercise_count`, `duration_sec`, `started_at`, `ended_at`.
   - Keep computation in Python (existing pattern, no per-session SQL aggregate function call). Justification: payload is small (single date's rows, typically < 100), the existing 1RM/HR merge logic already iterates the same list, and one-pass Python keeps the code style consistent with `_set_dict` and `attach_hr_to_sets`.
5. **Backward-compat**: keep the existing `GET /api/strength/session/{session_date}` shape additive — new fields appear, existing keys unchanged. The activity-detail consumer (`ExercisesTable.tsx`) keeps working.
6. **Router-level**: no new endpoints required — the date-keyed detail endpoint is sufficient.

## 8. Frontend tasks

1. **Types**: in `frontend/src/api/strength.ts`, add `superset_group_id?: number | null`, `order_index?: number | null` to `StrengthSet`; add `duration_sec?: number | null`, `total_sets`, `total_reps`, `total_volume_kg`, `exercise_count`, `started_at`, `ended_at` to `StrengthSessionDetail`; add `superset_group_id?: number | null`, `order_index?: number | null` to `ExerciseBreakdown` and `StrengthSetInput`.
2. **Recording → persist supersets**: in `frontend/src/pages/Record.tsx:218-247`, walk `exercises` in order and assign `superset_group_id` to each run of `linkedToNext` (e.g. emit a new int when entering a group, reuse for connected exercises, null when the previous exercise had `linkedToNext === false`). Assign `order_index = i` across exercises (0-based). Forward `started_at` (from the run timer's first start) and `ended_at` (now) on `StrengthSessionCreate`.
3. **Route**: in `frontend/src/App.tsx`, add `<Route path="/workouts/lifting/:date" element={routeElement(<LiftingDetail />)} />` inside the `<AppShell>` group, sibling to `/activities/:id`. Add a `const LiftingDetail = lazy(() => import("./pages/LiftingDetail"));`.
4. **Page**: `frontend/src/pages/LiftingDetail.tsx`:
   - Read `:date` param via `useParams`.
   - `useApi(['strength', 'session', date], () => fetchStrengthSessionOptional(date))`.
   - States: loading skeleton, error, 404 ("No strength session on this date" → back button), success.
   - Layout: `<SessionSummaryCard>`, then a grouped list — adjacent `ExerciseBreakdown` rows sharing a non-null `superset_group_id` are wrapped in a `<SupersetBracket>` (left bar + label "Superset A · 2 exercises · 3 rounds"); standalone ones render as a normal `<ExerciseDetailCard>`.
   - Reuse existing `Card`, `Dumbbell`/`Heart`/`Timer` icons. Respect `useUnits()` for kg ↔ lb.
5. **Components**:
   - `frontend/src/components/lifting/SessionSummaryCard.tsx` — date heading, duration (use `formatHmsCompact` from `activity/utils`), total volume, exercise count, set count, optional linked-activity chip → `/activities/{activity_id}`.
   - `frontend/src/components/lifting/ExerciseDetailCard.tsx` — name, est_1rm pill, set-by-set table (Set, kg/lb, reps, RPE, HR avg/max if present).
   - `frontend/src/components/lifting/SupersetBracket.tsx` — `border-l-2 border-l-brand-green` wrapper that nests its child cards visually, matching the recording-screen pattern (`ExerciseCard.tsx:36-42`).
6. **History wiring**: in `frontend/src/lib/historyEvents.ts:173-189`, always set `navigateTo: '/workouts/lifting/${s.date}'`. Drop the linked-activity-dependent branching (the detail page itself surfaces the activity link inside).
7. **Home wiring**: in `frontend/src/components/dashboard/YesterdayActivityCard.tsx:173-219`, wrap the `StrengthSection` block in a `<Link to="/workouts/lifting/{workoutDate}">` (or a `button` calling `navigate`). Preserve the existing nested Strava card's own behavior — only the strength sub-card becomes tappable.
8. **Loading / empty / error**: standard `AppShell` patterns used by `/history` and `/sleep`.

The frontend can stub against the new fields by hand-mocking `StrengthSessionDetail` in tests while the backend lands the migration + service changes — the contract is small.

## 9. Migration tasks

Single Alembic revision off head `c2f7a4e91b85` (the strength-touching head; `37d57cfdb27d` is the apple-health head, no overlap):

- **Slug**: `strength_supersets_and_duration`
- **`revision`**: pick a fresh hex (e.g. `f2a8d3c1e9b4`)
- **`down_revision = "c2f7a4e91b85"`**
- **Upgrade**:
  - `op.add_column("strength_sets", sa.Column("superset_group_id", sa.Integer(), nullable=True))`
  - `op.add_column("strength_sets", sa.Column("order_index", sa.Integer(), nullable=True))`
  - `op.add_column("strength_sets", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))`
  - `op.add_column("strength_sets", sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True))`
  - `op.create_index("ix_strength_sets_date_superset", "strength_sets", ["date", "superset_group_id"], unique=False)`
- **Downgrade**: drop index then four `op.drop_column` calls.
- **SQLite-safe**: uses `op.add_column`, not `batch_alter_table` (per AGENTS.md). All columns nullable so no `server_default` is needed and the scheduler can keep running through the migration.
- **No backfill** — existing rows are valid as-is (no superset, alphabetical fallback ordering, null duration).

## 10. Tests to add

- `tests/test_services/test_strength.py` (extend):
  - `test_session_summary_orders_by_order_index` — set `order_index` out of alphabetical order, assert returned `exercises[]` order respects it.
  - `test_session_summary_emits_superset_group_id` — two exercises with `superset_group_id=1`, one standalone; assert payload reflects.
  - `test_session_summary_duration_from_started_ended` and `test_session_summary_duration_fallback_to_performed_at_range`.
  - `test_session_summary_session_aggregates` — `total_sets`, `total_reps`, `total_volume_kg`, `exercise_count` correctness with a mix of weighted and bodyweight rows.
- `tests/test_routers/test_strength.py` (extend):
  - `test_create_sets_persists_superset_and_duration` — POST with `superset_group_id` on inputs and `started_at`/`ended_at` on the payload; assert GET round-trip.
  - `test_patch_set_updates_superset_group_id`.
  - Contract shape test: assert the new keys (`duration_sec`, `total_sets`, etc.) are present in `GET /api/strength/session/{date}`.
- `tests/test_services/test_strength_hr.py` — no change (HR pathway untouched), but rerun.
- Frontend:
  - `frontend/src/pages/LiftingDetail.test.tsx` (new) — mock `fetchStrengthSessionOptional`, assert summary card + supersetted exercise grouping + standalone exercise render. Use `MemoryRouter` with `/workouts/lifting/2026-05-24` and a `Route` setup mirroring `App.tsx`.
  - `frontend/src/components/lifting/SupersetBracket.test.tsx` (new) — render-smoke that the bracket wraps children with the brand-green left border.
  - `frontend/src/lib/historyEvents` — add a case asserting Strength events route to `/workouts/lifting/{date}` even when `activity_id` is null.
  - `frontend/src/pages/Record.test.tsx` — extend to assert that consecutive exercises with `linkedToNext: true` produce the same `superset_group_id` in the POST payload (snapshot the body of the `createStrengthSession` mock).

## 11. Parallelism plan

```
phase 1 (parallel):
  - db-migrator       → writes the Alembic revision (4 add_columns + 1 index)
  - integration-researcher (light) → confirms open questions (duration source,
                                      PR badges in v1, editability) and bounces
                                      back the defaults documented above
                                      ─ NO external API research needed

phase 2 (parallel, depends on phase 1):
  - backend-engineer  → model fields + service payload + Pydantic shapes
                        + router wiring; lands the GET contract first so the
                        frontend can switch from stub to real data
  - frontend-engineer → types, route, page, components, history+home wiring,
                        Record.tsx supersets persistence; stubs the new fields
                        in fixtures until backend lands, then removes stubs

phase 3 (sequential):
  - test-runner       → pytest + frontend vitest + npm run build
  - code-reviewer     → check the additive contract, SQLite-safe migration,
                        no removal of existing keys in session_summary
```

API contract the frontend can stub against (return shape from `GET /api/strength/session/{date}`):

```jsonc
{
  "date": "2026-05-24",
  "activity_id": 12345,
  "started_at": "2026-05-24T17:30:00",
  "ended_at": "2026-05-24T18:25:00",
  "duration_sec": 3300,
  "total_sets": 18,
  "total_reps": 142,
  "total_volume_kg": 4220.5,
  "exercise_count": 5,
  "sets": [ /* StrengthSet[] with new fields */ ],
  "exercises": [
    {
      "name": "Bench Press",
      "superset_group_id": 1,
      "order_index": 0,
      "sets": [ /* … */ ],
      "max_weight": 80,
      "total_volume": 1200,
      "est_1rm": 92.0
    },
    /* … */
  ],
  "hr_curve": [[0, 78], /* … */],
  "activity_start_iso": "2026-05-24T17:28:00"
}
```

## 12. Risks and rollback

- **Migrations are the highest risk** in Railway. Mitigation: all four columns nullable, no `server_default`, `op.add_column` (not `batch_alter_table`) so the scheduler keeps running. The new index is small. Rollback: `alembic downgrade c2f7a4e91b85` cleanly drops index + columns.
- **Bug B (lifting save) precondition**: `CLAUDE.md` flags manual save as broken; `docs/audit-001-handoff.md` lists it as the regression gate. If `main` still has Bug B unfixed, the new POST fields won't help because the underlying write never reaches DB — call out as a precondition risk and confirm `tests/test_routers/test_strength.py::test_create_sets_round_trips_performed_at` is green on `main` before starting.
- **Order-of-deploy**: the frontend route works against the existing payload (new fields will be `undefined`), so deploying frontend first is non-breaking. Backend-first is also safe. No coordinated deploy needed.
- **History dedup**: `frontend/src/lib/historyEvents.ts:248-278` already dedupes a Strava `WeightTraining` activity when a strength row links to it. Switching the navigateTo to `/workouts/lifting/{date}` means the user no longer lands on the Strava activity detail; the detail page must surface "View linked Strava activity →" prominently (`SessionSummaryCard` chip) so HR streams / Strava commentary remain reachable.
- **Rollback plan**: revert the feature PR. The migration downgrade is destructive only for data we just wrote (superset_group_id / order_index / started_at / ended_at). Volume/reps/RPE history is untouched. Revert is one `alembic downgrade -1` + a `git revert`.
