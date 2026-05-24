# audit-001 — Validation of the timezone-aware datetime sweep

*Companion to `docs/audit-001-initial.md` and `docs/audit-001-plan.md`.
Validates the per-column changes made by commits `e87220f` and `35d648f`,
which added `timezone=True` to every `DateTime` declaration across
`backend/models/`. The original audit flagged four columns as
intentionally naive-local; this document confirms whether the sweep
was safe for each, lists the call sites that write to them, and
records the targeted fixes applied here.*

---

## Background

| Commit | Scope |
|---|---|
| `e87220f` | `sync_log` + `analysis_cache` only. Unblocked the immediate sync failure (asyncpg rejected tz-aware Python datetimes against TIMESTAMP WITHOUT TIME ZONE casts). |
| `35d648f` | Sweep across the other ten model files: `activity`, `goal`, `recovery`, `strength`, `sleep`, `recommendation_feedback`, `user_location`, `user_profile`, `whoop_workout`, `weather`. |

The actual Railway Postgres columns were already `timestamp with time
zone` per the audit's diagnostic (`docs/audit-001-findings.md`); the
sweep aligns the SQLAlchemy declarations to that DB state.

asyncpg behaviour cheat-sheet:

| Python value | DB column type | Behaviour |
|---|---|---|
| naive `datetime` | `timestamp` | OK (no implicit tz). |
| tz-aware `datetime` | `timestamp` | **Refused** — the original bug. |
| naive `datetime` | `timestamptz` | Accepted, treated as **UTC** implicitly. |
| tz-aware `datetime` | `timestamptz` | Accepted, value preserved. |

So the sweep can't itself crash the writes on Postgres. It can,
however, leave naive call sites implicitly relabeled as UTC — which is
fine for values that are already in UTC (Whoop) but **mislabels**
values that were intentionally naive-local (Eight Sleep `bed_time` /
`wake_time` and frontend `performed_at`). The actual stored numeric
wall-clock value is unchanged because that's what asyncpg has been
implicitly doing all along; only the displayed tz label in DB tools
changes.

---

## Columns the sweep changed

Exhaustive list from `git show 35d648f` and `git show e87220f`, plus
the canonical list maintained in
`alembic/versions/a9d2f6c1e3b7_pg_identity_and_tz.py` (`TIMEZONE_COLUMNS`).

| Column | File:line | Audit notes (pre-sweep) |
|---|---|---|
| `Activity.start_date` | `backend/models/activity.py:34` | Was already tz-aware in semantics (Strava ISO with offset). Sweep is a no-op fix. |
| `Activity.start_date_local` | `backend/models/activity.py:35` | **Documented as intentionally naive-local** in `docs/audit-001-initial.md` §1. |
| `Activity.enriched_at` | `backend/models/activity.py:63` | Internal stamp from `utc_now()`. tz-aware. |
| `Activity.classified_at` | `backend/models/activity.py:68` | Internal stamp from `utc_now()`. tz-aware. |
| `Activity.rated_at` | `backend/models/activity.py:93` | Internal stamp — was naive (`utc_now_naive()`). |
| `Activity.created_at` | `backend/models/activity.py:95` | DB `func.now()`. |
| `ActivityLap.start_date` | `backend/models/activity.py:135` | Internal; written from enrichment payload. |
| `AnalysisCache.created_at` | `backend/models/sync_log.py:36` | DB `func.now()`. |
| `AnalysisCache.expires_at` | `backend/models/sync_log.py:39` | Internal stamp — was naive (`utc_now_naive() + ttl`). |
| `Goal.created_at` | `backend/models/goal.py:30` | DB `func.now()`. |
| `Goal.updated_at` | `backend/models/goal.py:33` | DB `func.now()`. |
| `RecommendationFeedback.created_at` | `backend/models/recommendation_feedback.py:29` | DB `func.now()`. |
| `Recovery.created_at` | `backend/models/recovery.py:26` | DB `func.now()`. |
| `SleepSession.bed_time` | `backend/models/sleep.py:20` | **Documented as intentionally naive-local** in `docs/audit-001-initial.md` §1. |
| `SleepSession.wake_time` | `backend/models/sleep.py:21` | **Documented as intentionally naive-local** in `docs/audit-001-initial.md` §1. |
| `SleepSession.created_at` | `backend/models/sleep.py:50` | DB `func.now()`. |
| `StrengthSet.performed_at` | `backend/models/strength.py:48` | **Documented as intentionally naive-local** in `docs/audit-001-initial.md` §1. |
| `StrengthSet.created_at` | `backend/models/strength.py:50` | DB `func.now()`. |
| `StrengthSet.updated_at` | `backend/models/strength.py:53` | DB `func.now()`. |
| `SyncLog.started_at` | `backend/models/sync_log.py:18` | Default `func.now()`. (Fixed in `e87220f`.) |
| `SyncLog.completed_at` | `backend/models/sync_log.py:20` | `utc_now()` (tz-aware). (Fixed in `e87220f`.) |
| `UserLocation.created_at` | `backend/models/user_location.py:30` | DB `func.now()`. |
| `UserProfile.updated_at` | `backend/models/user_profile.py:25` | DB `func.now()`. |
| `WeatherSnapshot.created_at` | `backend/models/weather.py:30` | DB `func.now()`. |
| `WhoopWorkout.start` | `backend/models/whoop_workout.py:28` | Written from Whoop `_parse_dt` — was naive-UTC. |
| `WhoopWorkout.end` | `backend/models/whoop_workout.py:29` | Same. |
| `WhoopWorkout.created_at` | `backend/models/whoop_workout.py:55` | DB `func.now()`. |
| `WhoopWorkout.updated_at` | `backend/models/whoop_workout.py:57` | DB `func.now()`. |

---

## Per-column investigation

For each of the four columns the original audit flagged as naive, plus
the auxiliary columns where the sweep introduced a naive→tz-aware
write asymmetry. `server_default=func.now()` writes are skipped — those
are generated entirely by Postgres and never carry a Python value.

### `Activity.start_date_local` — accepted as-is (no fix)

**Write sites.**

| Site | File:line | Datetime shape |
|---|---|---|
| Strava Phase A upsert | `backend/services/sync.py:166-168` | `datetime.fromisoformat(raw[...].replace("Z", "+00:00"))` — **tz-aware** (Strava attaches a `Z`; the replace coerces it to `+00:00` and `fromisoformat` produces a tz-aware value). |

**Diagnosis.** tz-aware everywhere.

**Decision.** Accepted as-is. The audit's "naive-local" description in
§1 of `docs/audit-001-initial.md` is a historical artifact from the
SQLite era — Strava's "local" timestamp comes through `fromisoformat`
as tz-aware. No fix needed.

---

### `SleepSession.bed_time` / `SleepSession.wake_time` — fixed at call sites

**Write sites.**

| Site | File:line | Pre-fix shape |
|---|---|---|
| Eight Sleep upsert | `backend/services/eight_sleep_sync.py:288-291` (via `_extract_fields`) | **Naive-local** (`_to_local` returns `astimezone(tz).replace(tzinfo=None)`). |
| Whoop upsert | `backend/services/whoop_sync.py:218-219` | **Naive-UTC** (`_parse_dt` strips tzinfo). |

**Diagnosis.** Mixed. Both sources wrote naive datetimes — but they
disagreed on semantics (Eight Sleep stored wall-clock-local; Whoop
stored UTC). asyncpg's implicit "naive → UTC" coercion silently
relabeled Eight Sleep's local wall clock as UTC, the same drift the
audit warned about.

**Decision.** Fix at the call sites by attaching UTC tzinfo before
INSERT.

* `backend/services/whoop_sync.py:_parse_dt` — drop the trailing
  `.replace(tzinfo=None)` so the helper returns tz-aware UTC. Every
  caller (`_cycle_start_date`, `_sleep_wake_date`, `_upsert_sleep`,
  `_upsert_workout`) is already safe with either shape (the `.date()`
  callers don't care, and the model writes now get a tz-aware value).
* `backend/services/eight_sleep_sync.py:_sync_window` — after
  `_extract_fields`, attach UTC tzinfo to the naive-local `bed_time`
  / `wake_time` outputs. This matches asyncpg's existing implicit
  bind behaviour exactly — the numeric value Postgres stores is
  unchanged — but makes the contract explicit in Python so any future
  reader of `bed_time` sees a tz-aware datetime consistently.
  Leaving `_to_local` alone keeps the existing unit tests
  (`test_to_local_*`, `test_extract_fields_returns_bed_time_in_local_tz`)
  passing without modification.

The chosen "naive → UTC at boundary" fix is the minimal one. A full
correctness pass (attaching the user's *real* local tz so Eight Sleep's
DB-stored timestamps display correctly in tz-aware tooling) is a
separate concern called out in **Follow-ups**.

> **Scope honesty.** For Eight Sleep specifically, the values coming out
> of `_extract_fields` represent naive *local* wall-clock — yet this PR
> labels them as UTC. That preserves the on-disk numeric value
> Postgres has been storing all along (because asyncpg has been
> implicitly tagging naive-local writes as UTC for the entire history
> of the `timestamptz` column), but it does **not** fix the semantic
> contract — a downstream consumer that does tz math on `bed_time`
> will read "23:00 UTC" when the user actually went to bed at "23:00
> local", and will be off by the user's UTC offset. This PR chose
> "preserve observed Postgres value" over "fix the semantic
> contract"; the real correctness fix (attach the user's actual
> resolved `ZoneInfo`) is deferred to **Follow-up #3** and gated on
> `W1-eightsleep-tokens`.

---

### `StrengthSet.performed_at` — fixed at call sites

**Write sites.**

| Site | File:line | Pre-fix shape |
|---|---|---|
| `POST /api/strength/sets` | `backend/routers/strength.py:117` (`create_sets`) | **Naive-local** — frontend sends `toNaiveLocalIso(new Date())` (`frontend/src/components/record/datetime.ts:4-10`); Pydantic parses it to a naive `datetime`. |
| `PATCH /api/strength/sets/{id}` | `backend/routers/strength.py:149` (`update_set`) | Same. |

**Diagnosis.** Naive everywhere on the write side.

**Decision.** Fix at the router boundary with a small helper
``_normalize_performed_at`` that attaches `timezone.utc` to naive
inputs. The numeric wall-clock value is preserved — asyncpg has been
implicitly tagging the naive value as UTC for as long as the DB column
has been `timestamptz`, so no data drift. The helper also short-circuits
on `None` and on already-tz-aware inputs.

Applied at both `create_sets` and `update_set` (the PATCH path was
quietly accepting naive `performed_at` via `setattr` directly).

---

### Other naive-write sites observed (out of audit scope, listed for completeness)

These are **not** for the original four naive-local columns — they're
sites where the sweep upgraded a column to tz-aware while the
producing Python code still emits naive datetimes. Fixing them was
out of scope for this audit, but they're listed here so the next agent
doesn't have to rediscover them.

| Column | Site | Note |
|---|---|---|
| `Activity.rated_at` | `backend/routers/activities.py:170` | `activity.rated_at = utc_now_naive()`. Functionally fine on asyncpg (implicit UTC); explicit fix is a one-line swap to `utc_now()`. |
| `AnalysisCache.created_at` | `backend/services/insight_cache.py:45,52` | `now = utc_now_naive()` written to a tz-aware column. Same implicit-UTC story; explicit fix would use `utc_now()`. |
| `AnalysisCache.expires_at` | `backend/services/insight_cache.py:46,51,60` | Same; the `< utc_now_naive()` comparison at `:27` would also benefit from a tz-aware swap. |

These were intentionally left alone because the audit's stated scope
is the four naive-local columns, and the audit task explicitly
mentioned "Don't optimize call sites for style". If a follow-up agent
chooses to tighten the contract, the smallest possible diff is:

* `routers/activities.py`: swap one `utc_now_naive()` → `utc_now()`.
* `services/insight_cache.py`: replace the three `utc_now_naive()`
  calls with `utc_now()`; both the read (`expires_at < ...`) and write
  paths become consistently tz-aware.

### Query-side naive cutoffs (not a write problem, called out for the record)

Numerous service / router queries use naive cutoff datetimes
(`utc_now_naive() - timedelta(days=N)` or `datetime.combine(date,
time.min)`) compared against now-tz-aware columns like
`Activity.start_date`. Examples:

* `backend/routers/dashboard.py:98, 133`
* `backend/routers/activities.py:51`
* `backend/services/workout_snapshot.py:49-50, 145`
* `backend/services/correlations.py:73`
* `backend/services/metrics.py:25-26, 118, 121`
* `backend/services/training_load_snapshot.py:65`
* `backend/services/goals_feedback_snapshot.py:80, 122`
* `backend/services/weekly_summary.py:35-36`

asyncpg accepts naive datetime parameters against `timestamptz`
columns (treats them as UTC), so these comparisons do not crash. They
are, however, semantically imprecise the same way write-side calls
were. A follow-up PR could standardise these via a single
`utc_now()`-based helper. **Not addressed in this audit-PR.**

---

## Fixes applied in this PR

| File | Change |
|---|---|
| `backend/services/whoop_sync.py` | `_parse_dt` no longer strips tzinfo; returns tz-aware UTC. Docstring updated. |
| `backend/services/eight_sleep_sync.py` | `_sync_window` attaches UTC tzinfo to `bed_time` / `wake_time` after `_extract_fields`. |
| `backend/routers/strength.py` | New helper `_normalize_performed_at` attaches UTC tzinfo to naive `performed_at`; applied in both `create_sets` (POST) and `update_set` (PATCH). |

No model files changed — the sweep is left intact per the task's
"don't revert wholesale" guidance.

## New tests

| File | What it asserts |
|---|---|
| `tests/test_datetime_sweep.py` | Round-trips a tz-aware UTC datetime through each of the four flagged columns (`Activity.start_date_local`, `SleepSession.bed_time`, `SleepSession.wake_time`, `StrengthSet.performed_at`) on SQLite and (when `TEST_POSTGRES_URL` is set) Postgres. The Postgres branch additionally asserts tzinfo is preserved on read. |
| `tests/test_datetime_sweep_callsites.py` | Unit tests for the call-site fixes: `_normalize_performed_at` (naive → tz-aware, tz-aware passthrough, None passthrough) and `_parse_dt` (returns tz-aware UTC, normalises offsets, returns None on invalid). |

Verified locally:

```
$ python -m pytest tests/
============================= 413 passed in 10.95s =============================
$ ruff check .
All checks passed!
```

(Original suite: 404 tests. This PR adds 9.)

---

## Follow-ups (not handled here)

1. **Tighten the auxiliary call sites** noted above
   (`Activity.rated_at`, `AnalysisCache.created_at` /`expires_at`) by
   switching `utc_now_naive()` → `utc_now()`. Small mechanical diff.
2. **Standardise query-side cutoffs.** Replace the scattered
   `utc_now_naive() - timedelta(...)` and `datetime.combine(date,
   time.min)` patterns with a single `utc_window_start(days)` helper
   in `backend/services/time_utils.py` that emits tz-aware UTC
   datetimes. Functionally neutral on Postgres; gets rid of the
   implicit-UTC subtlety entirely.
3. **Eight Sleep "local wall-clock" semantics.** The current fix tags
   the naive-local output of `_to_local` as UTC at the write boundary,
   matching what asyncpg was doing implicitly. This means the value
   stored in Postgres is wall-clock-treated-as-UTC, which displays
   correctly only when the caller knows to ignore the tz label. A
   proper fix would attach the resolved `ZoneInfo` from `_resolve_tz`
   instead of UTC — but the sleep_analytics consumers
   (`_hour_of_day`, `bed_time.std_hours`) read these values as
   wall-clock numbers via `.hour`, which works either way. Worth
   revisiting once Eight Sleep is moved into the unified
   `oauth_tokens` flow (`W1-eightsleep-tokens` brief).
4. **Audit `oauth_token` writes.** The `oauth_tokens.expires_at`
   column has been tz-aware from the start (commit `f9c2e1a45b80`).
   The Whoop client (`backend/clients/whoop.py:201-211`) writes
   tz-aware values; Strava (`backend/clients/strava.py`) and Eight
   Sleep paths should be spot-checked to confirm the same — out of
   scope here but adjacent to this audit.
