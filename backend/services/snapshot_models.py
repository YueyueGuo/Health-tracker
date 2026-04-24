"""Pydantic contracts for dashboard insight input snapshots.

The public API still returns plain dictionaries for compatibility, but these
models validate the shape at assembly time and give the frontend a concrete
backend source of truth to mirror.

Type-sync checklist for changes in this file:
1. Update the matching TypeScript interfaces in ``frontend/src/api/insights.ts``.
2. Check nullability and optional-vs-required semantics explicitly.
3. Run backend snapshot tests plus ``npm test``, ``npm run typecheck``, and
   ``npm run build`` from ``frontend/``.

``tests/test_services/test_snapshot_contract_drift.py`` auto-detects
field-name drift between these Pydantic models and the TS interfaces. It
does not check types or nullability, which is why the manual checklist
above still matters — but it catches the "forgot to update the other side"
failure mode without requiring a codegen toolchain.
"""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel, ConfigDict, TypeAdapter


class SnapshotModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DailyLoadPoint(SnapshotModel):
    date: str
    value: float


class TrainingLoadSnapshot(SnapshotModel):
    acute_load_7d: float
    chronic_load_28d: float
    acwr: float | None
    monotony: float | None
    strain: float | None
    days_since_hard: int | None
    last_hard_date: str | None
    classification_counts_7d: dict[str, int]
    classification_counts_28d: dict[str, int]
    daily_loads: list[DailyLoadPoint]
    activity_count_7d: int


class SleepSnapshot(SnapshotModel):
    last_night_date: str | None = None
    last_night_score: int | None = None
    last_night_duration_min: int | None = None
    last_night_deep_min: int | None = None
    last_night_rem_min: int | None = None
    last_night_hrv: float | None = None
    last_night_resting_hr: float | None = None
    avg_score_7d: float | None = None
    avg_duration_min_7d: float | None = None
    avg_hrv_7d: float | None = None
    sleep_debt_min: int | None = None
    nights_of_data: int


class RecoverySnapshot(SnapshotModel):
    today_date: str | None = None
    today_score: float | None = None
    today_hrv: float | None = None
    today_resting_hr: float | None = None
    avg_score_7d: float | None = None
    trend: str | None = None


class WorkoutLapSnapshot(SnapshotModel):
    index: int
    distance_m: float | None
    moving_time_s: int | None
    pace: str | None
    avg_hr: float | None
    avg_watts: float | None
    pace_zone: int | None


class WorkoutWeatherSnapshot(SnapshotModel):
    temp_c: float | None
    feels_like_c: float | None
    humidity: int | None
    wind_speed_ms: float | None
    conditions: str | None


class PreWorkoutSleepSnapshot(SnapshotModel):
    date: str
    score: int | None
    duration_min: int | None
    hrv: float | None
    deep_min: int | None
    rem_min: int | None


class HistoricalComparisonSnapshot(SnapshotModel):
    classification: str
    sample_size: int
    window_days: int
    pace_percentile: int | None
    effort_percentile: int | None


class LatestWorkoutSnapshot(SnapshotModel):
    id: int
    strava_id: int
    name: str
    sport_type: str
    classification_type: str | None
    classification_flags: list[str]
    start_date: str | None
    start_date_local: str | None
    distance_m: float | None
    moving_time_s: int | None
    elapsed_time_s: int | None
    total_elevation_m: float | None
    avg_hr: float | None
    max_hr: float | None
    avg_speed_ms: float | None
    pace: str | None
    avg_power_w: float | None
    weighted_avg_power_w: float | None
    kilojoules: float | None
    suffer_score: int | None
    calories: float | None
    laps: list[WorkoutLapSnapshot]
    weather: WorkoutWeatherSnapshot | None
    pre_workout_sleep: PreWorkoutSleepSnapshot | None
    historical_comparison: HistoricalComparisonSnapshot | None


class GoalSnapshot(SnapshotModel):
    id: int
    race_type: str
    description: str | None
    target_date: str
    days_until: int
    weeks_until: int
    phase: str
    is_primary: bool
    status: str


class GoalsSnapshot(SnapshotModel):
    primary: GoalSnapshot | None
    secondary: list[GoalSnapshot]


class MeanSdSnapshot(SnapshotModel):
    mean: float
    sd: float


class SportBaselineSnapshot(SnapshotModel):
    sample_size: int
    pace_s_per_km: MeanSdSnapshot | None
    avg_hr: MeanSdSnapshot | None
    avg_power_w: MeanSdSnapshot | None


BaselinesSnapshot = dict[str, SportBaselineSnapshot | None]


class RecentRpeSnapshot(SnapshotModel):
    activity_id: int
    date: str
    sport_type: str
    classification: str | None
    rpe: int
    notes: str | None
    avg_hr: int | None
    suffer_score: int | None


class FeedbackDeclineSnapshot(SnapshotModel):
    date: str
    reason: str | None


class FeedbackSummarySnapshot(SnapshotModel):
    accepted: int
    declined: int
    total: int
    recent_declines: list[FeedbackDeclineSnapshot]


class EnvironmentalSnapshot(SnapshotModel):
    last_night_bed_temp_c: float
    last_night_date: str | None


class RecentActivitySnapshot(SnapshotModel):
    date: str
    sport: str
    classification: str | None
    duration_min: int | None
    distance_km: float | None
    avg_hr: int | None
    suffer_score: int | None
    pace: str | None


class FullSnapshot(SnapshotModel):
    today: str
    training_load: TrainingLoadSnapshot
    sleep: SleepSnapshot
    recovery: RecoverySnapshot
    latest_workout: LatestWorkoutSnapshot | None
    recent_activities: list[RecentActivitySnapshot]
    goals: GoalsSnapshot
    baselines: BaselinesSnapshot
    recent_rpe: list[RecentRpeSnapshot]
    feedback_summary: FeedbackSummarySnapshot
    environmental: EnvironmentalSnapshot | None


class DailyRecommendationCacheSignal(SnapshotModel):
    date: str
    training_load: TrainingLoadSnapshot
    sleep: SleepSnapshot
    recovery: RecoverySnapshot
    latest_id: int | None
    goals: GoalsSnapshot
    recent_rpe: list[RecentRpeSnapshot]
    feedback_summary: FeedbackSummarySnapshot
    environmental: EnvironmentalSnapshot | None


T = TypeVar("T", bound=BaseModel)


def validate_snapshot(payload: dict, model: type[T]) -> dict:
    """Validate ``payload`` against ``model`` and return the original dict."""
    model.model_validate(payload)
    return payload


def validate_snapshot_list(payload: list[dict], model: type[T]) -> list[dict]:
    """Validate a list of snapshot dictionaries without changing payload shape."""
    TypeAdapter(list[model]).validate_python(payload)
    return payload


def validate_baselines(payload: dict) -> dict:
    TypeAdapter(BaselinesSnapshot).validate_python(payload)
    return payload


def daily_recommendation_cache_signal(snapshot: dict) -> dict:
    """Small, explicit subset of a full snapshot that should invalidate daily recs."""
    FullSnapshot.model_validate(snapshot)
    signal = {
        "date": snapshot["today"],
        "training_load": snapshot["training_load"],
        "sleep": snapshot["sleep"],
        "recovery": snapshot["recovery"],
        "latest_id": (snapshot.get("latest_workout") or {}).get("id"),
        "goals": snapshot.get("goals"),
        "recent_rpe": snapshot.get("recent_rpe"),
        "feedback_summary": snapshot.get("feedback_summary"),
        "environmental": snapshot.get("environmental"),
    }
    DailyRecommendationCacheSignal.model_validate(signal)
    return signal
