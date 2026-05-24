# 0002. Apple Health: polymorphic `health_data_points` base + typed `workouts` subtype

## Status

Accepted — 2026-05-24.

## Context

The Health Tracker now needs to ingest workouts from two distinct sources:

* **Strava**, which already lands in the existing `activities` table
  (Strava-shaped: `strava_id`, `sport_type`, zones, streams, laps, weather
  enrichment, elevation enrichment, classifier flags, RPE, etc.). It is
  the live source of truth for everything the dashboard, classifier,
  insights, and scheduler currently read.
* **Apple Health**, pushed in via an iOS-Shortcut webhook. HealthKit
  is the canonical wearable source on this user's wrist (Apple Watch),
  so when both Strava and Apple Health have the "same" workout, Apple
  wins.

We also want the door open to other HealthKit data types (steps, sleep,
HRV, heart-rate samples) without another migration of the base table
every time.

Three shapes were considered:

1. **Add Apple-only columns to `activities`.** Cheap migration but mixes
   sources in a single Strava-shaped table; "Apple wins" becomes a
   complicated source-priority column; new data types (steps, sleep)
   have no obvious home.
2. **Project every Strava activity into a new generic table.** Cleanest
   long-term model, but requires moving thousands of Railway rows in
   one shot during the migration window, and rewriting the classifier /
   weather / insights / scheduler / strength code paths that read
   `activities` directly. High risk on a single-user production DB for
   no immediate user-visible benefit.
3. **Polymorphic `health_data_points` base + typed subtype tables, with
   `activities` kept untouched** (this ADR's choice).

## Decision

Introduce three new tables alongside the existing `activities` table:

* **`health_data_points`** — polymorphic base. Carries
  `(source, data_type, external_id)` as a natural composite-unique key,
  plus `start_time` / `end_time`, `raw_payload`, audit timestamps, and
  a self-referential `superseded_by_id` so dedup can point one row at
  the canonical one that replaced it.
* **`workouts`** — joined-table-inheritance subtype keyed by the same
  `id` as its parent `health_data_points` row, holding workout-specific
  metrics (`activity_type`, `duration_s`, `active_energy_kcal`,
  `distance_m`, `avg_speed_mps`, `avg_pace_s_per_km`, `avg_hr`,
  `max_hr`, `total_elevation_m`). Also has a nullable `activity_id` FK
  back to `activities` for the back-link when both sources exist for
  the same workout.
* **`workout_laps`** — mirrors the shape of `activity_laps`, child of
  `workouts` with a `(workout_id, lap_index)` unique constraint.

The `activities` table is **not** migrated into `health_data_points`.
It picks up three nullable additive columns instead:

* `source` — backfilled to `'strava'`.
* `external_id` — backfilled to `CAST(strava_id AS TEXT)`.
* `superseded_by_id` — indexed plain integer, **no FK** (cross-table
  reference into `health_data_points.id`; keeping it FK-less avoids a
  circular DDL dependency and stays SQLite-friendly).

Source-enum validation is enforced in application code, not via a CHECK
constraint, so SQLite downgrades and Postgres upgrades stay symmetric.

## Rationale

* **No risky data move on Railway.** Three new tables + three nullable
  columns + two idempotent UPDATE backfills. Each step is independently
  reversible; `alembic downgrade -1` cleanly removes everything.
* **Existing code stays correct.** Classifier, weather, insights,
  strength, scheduler, weekly-summary, correlations, and every router
  that touches `activities` continues to work unchanged. `Activity` is
  still the canonical Strava-shaped row.
* **Forward-compatible.** Future HealthKit data types plug in as new
  `data_type` values (`steps`, `sleep`, `heart_rate`, …) with their own
  typed subtype tables when they need typed columns, without another
  migration of the polymorphic base.
* **Dedup is explicit.** `Activity.superseded_by_id` and
  `HealthDataPoint.superseded_by_id` make "which row replaced this?"
  a first-class queryable concept. The default `/api/activities`
  listing filters out non-null `superseded_by_id`; callers that need
  the unfiltered set (scheduler enrichment, debug tools) pass
  `include_superseded=True`.

## Consequences

* **Dedup walks two tables.** `workout_dedup` queries both `activities`
  (start_date window + normalized sport) and `health_data_points` /
  `workouts` (start_time window + normalized sport). This is acceptable
  for a single-user dataset; both tables are indexed on
  `(data_type, start_time)` / `start_date`.
* **`activities.superseded_by_id` has no FK.** App code is responsible
  for not pointing it at a nonexistent `health_data_points.id`.
  Acceptable trade-off to avoid the cross-table FK dependency.
* **Two homes for "workout"-shaped data going forward.** New sources
  (e.g. a second wearable) should go into `health_data_points` +
  `workouts`, **not** `activities`. `activities` stays the Strava-shaped
  legacy home; do not add new sources to it. If we ever need to
  consolidate, the projection from `activities` → `health_data_points`
  can be done as a one-off batch script with no schema change.
* **Apple Health UUID nuance.** A workout edited on the watch may emit
  a new UUID; we'll create a second `health_data_points` row and dedup
  it against the first via the 10-minute window. Documented in the plan
  §12; revisit if it bites the user in practice.

## References

* Plan: `docs/plans/apple-health-workouts.md` (§5 Data model, §9
  Migration tasks, §12 Risks).
* Migration: `alembic/versions/37d57cfdb27d_apple_health_workouts.py`.
* AGENTS.md → Migrations (SQLite-vs-Postgres compatibility rules, DAG
  history convention).
