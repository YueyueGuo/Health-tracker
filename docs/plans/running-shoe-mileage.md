# Running Shoe Mileage Tracking — Backend Plan

## 1. Summary
- Add an account-level "running shoes" concept the user can create, edit, retire, and tag onto runs.
- Each shoe carries a name/model, status (`active|retired`), shoe type (`everyday|workout|race|long_run|trail`), and a configurable `total_usable_distance_m` so the UI can show "you've put 312 / 800 km on these."
- Cumulative distance is computed on demand from tagged Strava activities (and Apple Health workouts) — no stored counter, no triggers, no backfill script.
- Existing activities/workouts get a nullable `shoe_id` FK that the user can set at any time (P0: from the activity detail page; the schema also supports a future "retroactive sweep" view).
- P0 ships the schema + CRUD + tagging API. Auto-suggesting shoes from workout type is intentionally deferred to P1/P2; the `shoe_type` enum on shoes is the future hook.

## 2. Scope

**In (P0, this PR — backend only):**
- `shoes` table + Pydantic schemas + `/api/shoes` router (list / get / create / patch / retire / unretire / activities).
- Nullable `shoe_id` FK on `activities` (Strava) and on `workouts` (Apple Health joined-table-inheritance row at `backend/models/workout.py`).
- Endpoints to tag/untag a shoe on an activity, with dual-resolution to support Apple Health ids (mirrors the existing `PATCH /api/activities/{id}/feedback` pattern at `backend/routers/activities.py:188-245`).
- Computed cumulative distance + percent-used response field on shoe detail (and bulk-included on list).
- Empty-state signal: `GET /api/shoes` returning `[]` is the contract the frontend uses to render a "create your first shoe" CTA.

**Out (P1/P2 — deferred, schema supports it):**
- Auto-suggestion of `shoe_id` based on `shoe.shoe_type` ↔ activity classification (e.g. `race` shoe for race-day activities). Schema already exposes the inputs — no further migration needed when it lands.
- Retroactive sweep UI ("tag the last 90 days of runs"). Backend supports this with the existing PATCH; no new API.
- Wear/lifespan alerts (e.g. "you've passed 80%"). Backend already returns the percent — frontend concern.
- Multi-user scoping. Single-user app today; existing tables (`activities`, `goals`, `user_profile`) have no `user_id`, so `shoes` matches that convention. Verified by reading `backend/models/__init__.py` and `backend/models/goal.py`.

**Backend-only:** no `frontend-engineer` in this PR; see section 11 for the design hand-off list.

## 3. Data model

### New table: `shoes`
| column | type | null | default | notes |
|---|---|---|---|---|
| `id` | Integer PK autoincrement | no | — | matches `goals`, `activities` |
| `name` | String(120) | no | — | user label, e.g. "Vaporfly 3 — blue" |
| `brand` | String(64) | yes | — | optional |
| `model` | String(120) | yes | — | optional |
| `shoe_type` | String(24) | no | `'everyday'` | one of `everyday`, `workout`, `race`, `long_run`, `trail`. Validated by router-layer regex (see §6); no DB CHECK so widening the enum doesn't require a migration. |
| `status` | String(12) | no | `'active'` | one of `active`, `retired`. Indexed. |
| `total_usable_distance_m` | Float | yes | `null` | user-configurable lifespan in meters. Null = "no target set"; `percent_used` returns null. |
| `purchased_on` | Date | yes | — | optional, useful for sorting / display |
| `retired_at` | DateTime(timezone=True) | yes | — | stamped when `status` transitions to `retired` |
| `notes` | Text | yes | — | freeform |
| `created_at` | DateTime(timezone=True) | no | `func.now()` | matches existing convention |
| `updated_at` | DateTime(timezone=True) | no | `func.now()` + `onupdate=func.now()` | matches `goals` (`backend/models/goal.py:34-36`) |

Indexes: `ix_shoes_status` (most reads filter by `status='active'`), `ix_shoes_shoe_type` (cheap, future auto-suggest will read it).

### New columns on existing tables
- `activities.shoe_id` — `Integer NULL`, `ForeignKey("shoes.id", ondelete="SET NULL")`, indexed. Lives next to the existing user-supplied block at `backend/models/activity.py:94-96`. Nullable, no default, no CHECK → metadata-only ALTER on Postgres.
- `workouts.shoe_id` — same shape on the Apple Health workout row at `backend/models/workout.py:30-66`. Nullable, indexed, FK with `ondelete=SET NULL`.

### Relationships
- `Shoe.activities` → `relationship("Activity", back_populates="shoe")` (read-only convenience; cumulative-distance query uses `SUM` directly).
- `Shoe.apple_workouts` → `relationship("Workout", back_populates="shoe")`.
- `Activity.shoe` / `Workout.shoe` → many-to-one back-refs.

### Cumulative distance, computed
For shoe `S`:
```
total_m =
    coalesce((select sum(distance)    from activities where shoe_id = S.id), 0)
  + coalesce((select sum(distance_m)  from workouts   where shoe_id = S.id), 0)
```
- Strava `Activity.distance` is meters (`backend/models/activity.py:42`).
- Apple `Workout.distance_m` is meters (`backend/models/workout.py:44`).
- Activity / workout deletes cascade via the table-level relationships; no soft-delete flag to filter on.
- Superseded Strava rows are still summed if they carry a `shoe_id`. The user will normally tag the canonical row; dedup is a feed concern, not an accounting concern. Document and move on.

### Backfill
None. Existing activities/workouts get `shoe_id = NULL`. The user PATCHes individual rows whenever they want. No script, no triggers.

## 4. Affected surfaces

| surface | change | files |
|---|---|---|
| `backend/models/` | new `Shoe` model | `backend/models/shoe.py` (new); `backend/models/__init__.py` (export) |
| `backend/models/activity.py` | add `shoe_id` FK + `shoe` relationship | `backend/models/activity.py` |
| `backend/models/workout.py` | add `shoe_id` FK + `shoe` relationship | `backend/models/workout.py` |
| `backend/routers/` | new shoe router | `backend/routers/shoes.py` (new) |
| `backend/routers/activities.py` | new `PATCH /{id}/shoe` (dual-resolves Strava + Apple ids) | `backend/routers/activities.py` |
| `backend/services/` | shoe-mileage helper (SUM-over-two-tables) | `backend/services/shoe_mileage.py` (new) |
| `backend/main.py` | wire `shoes.router` at `/api/shoes` | `backend/main.py` (next to line 155) |
| `alembic/versions/` | new revision off head `e1a3b7d2c9f4` | new file `alembic/versions/<rev>_running_shoes.py` |
| `tests/test_routers/` | new test module | `tests/test_routers/test_shoes.py` (new) |
| `tests/test_services/` | mileage computation tests | `tests/test_services/test_shoe_mileage.py` (new) |

## 5. External integration
None. Step 1 of the workflow skips `integration-researcher`.

## 6. API surface

All endpoints mounted at `prefix="/api/shoes"`, matching the `goals` wiring at `backend/main.py:155`.

| method | path | purpose | request | response |
|---|---|---|---|---|
| GET | `/api/shoes` | List shoes, default `active` only | `?status=active|retired|all` (default `active`) | `200 [ShoeOut, …]` — each item carries `cumulative_distance_m` and `percent_used` |
| GET | `/api/shoes/{shoe_id}` | Detail | — | `200 ShoeDetailOut` (same fields + `tagged_activity_count`) |
| POST | `/api/shoes` | Create | `ShoeCreate` | `201 ShoeOut` |
| PATCH | `/api/shoes/{shoe_id}` | Update name / brand / model / `shoe_type` / `total_usable_distance_m` / `notes` / `purchased_on` | `ShoePatch` (all optional) | `200 ShoeOut`. Status is NOT writable here. |
| POST | `/api/shoes/{shoe_id}/retire` | Retire (verb endpoint) | empty body | `200 ShoeOut`. Sets `status='retired'`, stamps `retired_at`. Idempotent. |
| POST | `/api/shoes/{shoe_id}/unretire` | Reactivate | empty body | `200 ShoeOut`. Clears `retired_at`. |
| GET | `/api/shoes/{shoe_id}/activities` | Convenience list of tagged activities/workouts | `?limit=&offset=` | `200 {items: [...]}` — P0. |

Tagging lives on the activity router for consistency with `PATCH /api/activities/{id}/feedback`:

| method | path | behaviour |
|---|---|---|
| PATCH | `/api/activities/{activity_id}/shoe` | Body `{shoe_id: int \| null}`. Resolves the id first against `Activity`, then against `HealthDataPoint`/`Workout` (mirror of `backend/routers/activities.py:201-226`). Rejects tagging a `retired` shoe (`400 "Cannot tag a retired shoe"`); allows untagging it; leaves existing tags pointing at retired shoes untouched (preserves history). |

### Retire vs PATCH-status: justification
A dedicated verb endpoint is cleaner than PATCH-status: retiring stamps `retired_at` (side effect a generic PATCH would have to special-case), the frontend "Retire" button has its own confirmation modal, and it mirrors the existing `POST /api/goals/{id}/set-primary` pattern at `backend/routers/goals.py:137`.

### Pydantic shapes (sketch — not code-prescriptive, just the contract)
```
ShoeCreate:
  name: str (1..120, required)
  brand: str | None (<=64)
  model: str | None (<=120)
  shoe_type: str = "everyday"  (regex ^(everyday|workout|race|long_run|trail)$)
  total_usable_distance_m: float | None (>0)
  purchased_on: date | None
  notes: str | None

ShoePatch: same fields, all optional. NO status field.

ShoeOut:
  id, name, brand, model, shoe_type, status,
  total_usable_distance_m, cumulative_distance_m, percent_used,
  purchased_on, retired_at, notes, created_at, updated_at
```
Validation pattern (`Field(pattern=...)`, no DB CHECK) follows `backend/routers/goals.py:38` exactly.

## 7. Service / business logic

`backend/services/shoe_mileage.py` (new):
- `async def cumulative_distance_m(db, shoe_id) -> float` — one query that sums two scalar selects (`Activity.distance` + `Workout.distance_m`), coalescing nulls to 0.
- `async def cumulative_distance_bulk(db, shoe_ids) -> dict[int, float]` — grouped variant so listing N shoes is two queries, not 2N.
- `def percent_used(total_usable_m, cumulative_m) -> float | None` — pure helper, returns null when target is null; values above 100 allowed (UI styles "overdue").

Business rules (enforced in router, not DB — matches `goals.py` convention):
- Retired shoes are not tag-eligible for new tags (`400` on the PATCH shoe endpoint).
- Existing tags to a now-retired shoe remain intact. Cumulative distance keeps reporting historical mileage.
- No DELETE endpoint in P0. Retire is the soft-delete. The FK is `ON DELETE SET NULL` so future hard-delete would just untag — explicitly out of scope.

## 8. Migration tasks

**Revision:** `<new_rev>_running_shoes` (db-migrator picks the hash).
**Parent / down_revision:** `e1a3b7d2c9f4` (current head — AGENTS.md line 51; verified by graph-walking `alembic/versions/*.py` `down_revision` chain — `e1a3b7d2c9f4` is the only revision no one else uses as parent).

Upgrade:
1. `op.create_table("shoes", …)` per §3. All `server_default`s are constants (`'active'`, `'everyday'`, `func.now()`); no raw SQL.
2. `op.create_index("ix_shoes_status", "shoes", ["status"])`.
3. `op.create_index("ix_shoes_shoe_type", "shoes", ["shoe_type"])`.
4. `op.add_column("activities", sa.Column("shoe_id", sa.Integer(), sa.ForeignKey("shoes.id", ondelete="SET NULL"), nullable=True))` — metadata-only on Postgres; SQLite-safe per AGENTS.md line 52.
5. `op.create_index("ix_activities_shoe_id", "activities", ["shoe_id"])`.
6. `op.add_column("workouts", sa.Column("shoe_id", sa.Integer(), sa.ForeignKey("shoes.id", ondelete="SET NULL"), nullable=True))`.
7. `op.create_index("ix_workouts_shoe_id", "workouts", ["shoe_id"])`.

Downgrade:
1. Drop the two `ix_*_shoe_id` indexes; `op.drop_column("workouts", "shoe_id")`; `op.drop_column("activities", "shoe_id")`.
2. Drop the two indexes on `shoes`; `op.drop_table("shoes")`.

SQLite safety: all `op.add_column` calls are on nullable columns with no default → no `batch_alter_table` needed. Matches `alembic/versions/c1a4e8f27b10_goals_rpe_feedback.py:71-73`.

Postgres safety: nullable column adds with no default and no CHECK are metadata-only DDL — no table rewrite even on the large `activities` table. The FK constraint is added inline at column creation; Postgres validates the FK against the just-created (empty) `shoes` table, which is trivial.

**`Risk: trivial`** — only new tables and new nullable FK columns whose target table (`shoes`) is created in the same migration. No backfill, no alter on existing populated data, no drops, no raw SQL. `migration-safety-checker` is skipped per the orchestrator's rule.

## 9. Tests to add

`tests/test_routers/test_shoes.py`:
- `test_list_shoes_empty_returns_empty_array` — fresh DB → `200 []` (frontend empty-state signal).
- `test_create_shoe_minimal` — only `name`; defaults applied.
- `test_create_shoe_full` — all optional fields round-trip.
- `test_create_shoe_invalid_type` — unknown enum value → `422`.
- `test_create_shoe_negative_distance` — `total_usable_distance_m = -1` → `422`.
- `test_patch_shoe_partial` — update only one field.
- `test_patch_shoe_does_not_change_status` — `status` not in schema, rejected.
- `test_retire_shoe`.
- `test_retire_is_idempotent`.
- `test_unretire_shoe`.
- `test_list_default_active_only`.
- `test_list_status_filter` — `?status=retired`, `?status=all`.
- `test_get_shoe_includes_cumulative_distance` — two activities (10km + 5km) → 15000m.
- `test_get_shoe_untagged_activities_do_not_count`.
- `test_get_shoe_percent_used`.
- `test_get_shoe_percent_used_null_when_no_target`.
- `test_retired_shoe_still_reports_distance`.
- `test_tag_activity_with_shoe`.
- `test_untag_activity` — body `{shoe_id: null}`.
- `test_tag_apple_workout_with_shoe` — id resolves via the dual-resolution path used in `backend/routers/activities.py:201-226`.
- `test_tag_nonexistent_activity_returns_404`.
- `test_tag_nonexistent_shoe_returns_400`.
- `test_cannot_tag_retired_shoe`.
- `test_existing_tag_to_retired_shoe_is_preserved`.
- `test_list_activities_for_shoe`.

`tests/test_services/test_shoe_mileage.py`:
- `test_cumulative_distance_sums_both_tables` — tagged `Activity` (10km) + tagged `Workout` (5km) → 15000.
- `test_cumulative_distance_empty` → `0.0`, not `None`.
- `test_cumulative_distance_bulk` — two shoes split across four activities.
- `test_percent_used_helper` — pure unit tests.

Follow existing conftest layout in `tests/test_routers/conftest.py`.

## 10. Parallelism plan

```
phase 1 (sequential):
  - db-migrator               → Alembic revision off e1a3b7d2c9f4
                                (no integration-researcher; no external integration)
phase 2 (sequential):
  - backend-engineer          → Shoe model, FK columns on Activity / Workout,
                                shoes router, shoe-mileage service, activity
                                tag endpoint, wire into main.py, write tests
                                (no frontend-engineer; design decoupled)
phase 3 (parallel — review):
  - code-reviewer
  - security-reviewer
  - skip qa-verifier            (per user)
  - skip performance-sentinel   (expected diff < 500 LOC)
  - skip migration-safety-checker (Risk: trivial)
phase 4 (sequential):
  - test-runner               → pytest + ruff
  - PR
```

## 11. Frontend interfaces required (hand-off to design)

The user has zero shoes today. Day one, every list endpoint returns `[]` — design must cover that and the steady state.

| surface | priority | description |
|---|---|---|
| Shoes list page (`/shoes` or under Settings) | P0 | Default-active list. Each card shows name, brand/model, shoe-type chip, `cumulative_distance_m`, and a progress bar against `total_usable_distance_m` ("X% used" when target set). Toggle for retired. Primary CTA "Add shoe". Empty state = full-bleed onboarding card. |
| Shoe create form (modal or sub-page) | P0 | Name (required), brand, model, shoe type (radio/dropdown), total usable distance (km/mi toggle is UI-only — backend stores meters), purchased on, notes. POST `/api/shoes`. |
| Shoe edit form | P0 | Same fields prefilled. PATCH `/api/shoes/{id}`. No status field — retire is separate. |
| Shoe detail view | P0 | Metadata header, progress to target, paginated list of tagged activities (`GET /api/shoes/{id}/activities`). Inline "Retire" button. |
| Retire confirmation modal | P0 | "Retire these shoes? They'll be hidden from the active list but history is preserved." → POST `/api/shoes/{id}/retire`. |
| Unretire affordance | P0 (cheap) | Inline on the retired list. POST `/unretire`. |
| Activity detail — shoe selector | P0 | Row on the activity detail (Strava + Apple). Reads `activity.shoe_id`. Dropdown of active shoes; "None" untags. PATCH `/api/activities/{id}/shoe`. |
| Activity detail — empty-state CTA | P0 | When the selector opens and `GET /api/shoes` returns `[]`, the dropdown collapses to "Add a shoe" that opens the create form inline; on save the new shoe is selected and PATCHed onto the current activity in one flow. |
| Retroactive tagging sweep view | P1 | List of recent runs with `shoe_id IS NULL` and an inline shoe picker per row. Backend already supports — no new endpoint. |
| Auto-suggest indicator on the selector | P1/P2 | Once auto-suggest lands, render "Suggested: Vaporfly (race)" as a pre-selected option. UI-only at that point. |
| Wear/lifespan warning chip | P1 | When `percent_used >= 80`, render an amber chip on the card / detail. Backend already returns `percent_used`. |

## 12. Open questions

- Units in the API: plan stores `total_usable_distance_m` and returns `cumulative_distance_m` in meters (matches `Activity.distance` and `Workout.distance_m`). Frontend converts for display. Confirm; if not, add `*_km` mirror fields (cheap, no DB change).
- Default `shoe_type` of `everyday` — acceptable, or should creation force the user to pick?
- Default `total_usable_distance_m`: plan leaves null (no target). Adding a default (e.g. 800 km) would force every shoe into the "% used" UI — flagging in case the user wants opinionated defaults.
- Shoe-type starter set is `everyday | workout | race | long_run | trail`. Easy to widen, but the values will eventually drive auto-suggest matching — pre-approve the list now to avoid churn later.
