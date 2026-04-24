"""Workout classifier.

Rules-based, interpretable. Reads from enriched Activity + ActivityLap +
zones_data. Designed to be easy to swap out later for an ML model once
labeled training data is available.

Public API:
    classify(activity, laps) -> Classification
    classify_and_persist(activity, laps) -> Classification  (sets columns)

Types (mutually exclusive):
    Runs:  easy | tempo | intervals | race
    Rides: recovery | endurance | tempo | mixed | race

Flags (orthogonal, zero or more):
    Runs:  is_long, has_speed_component, has_warmup_cooldown
    Rides: is_long, is_hilly
    Either: altitude_low | altitude_moderate | altitude_high (at most one)
"""
from __future__ import annotations

import logging
import statistics
from dataclasses import asdict, dataclass, field

from backend.models import Activity, ActivityLap
from backend.services.time_utils import utc_now

logger = logging.getLogger(__name__)

# ── Thresholds (tunable). Keep at module level so they're easy to tweak. ────

# A lap below this moving_time AND distance is likely a lap-button artifact
# (e.g. queueing up at the track). Drop from feature calculation.
_ARTIFACT_MIN_MOVING_S = 30
_ARTIFACT_MAX_DISTANCE_M = 50

# Auto-mile / auto-km split detection (ignoring the last, possibly-partial lap).
_AUTO_MILE_M = 1609.34
_AUTO_KM_M = 1000.0
_AUTO_SPLIT_TOLERANCE_M = 5.0

# Run type thresholds.
_RUN_STEADY_SPEED_CV = 0.10       # CV below this = steady pace
_RUN_TEMPO_MEAN_PACE_ZONE = 3.0   # mean pace zone >= this suggests tempo
_RUN_INTERVALS_MIN_MAX_ZONE = 4   # at least one lap at pace_zone >= 4
_RUN_INTERVALS_SPEED_CV = 0.15    # high variance is another interval signal

# Long-run flag.
_RUN_LONG_DURATION_S = 90 * 60    # 90 min
_RUN_LONG_DISTANCE_M = 16_000     # 16 km (~10 mi)

# Ride type thresholds.
_RIDE_RECOVERY_MAX_DURATION_S = 45 * 60
_RIDE_TEMPO_MIN_VI = 1.00
_RIDE_TEMPO_MAX_VI = 1.10
_RIDE_MIXED_MIN_VI = 1.10
_RIDE_LONG_DURATION_S = 120 * 60  # 2 hr
_RIDE_LONG_DISTANCE_M = 50_000    # 50 km
_RIDE_HILLY_M_PER_KM = 15.0

# Altitude tier thresholds in meters above sea level. Tuned conservatively
# for a sea-level athlete — the low-tier floor is ~2,000 ft (610 m) where
# aerobic effort typically starts to feel noticeably harder.
_ALT_LOW_M = 610       # ~2,000 ft
_ALT_MODERATE_M = 1500  # ~5,000 ft
_ALT_HIGH_M = 2500      # ~8,200 ft

# Strava `workout_type` codes (undocumented-but-stable).
# Runs: 0=default, 1=race, 2=long_run, 3=workout (speed/structured)
# Rides: 10=default, 11=race, 12=workout


@dataclass
class Classification:
    type: str                                # e.g. "easy" | "intervals"
    flags: list[str] = field(default_factory=list)
    confidence: float = 0.5
    features: dict = field(default_factory=dict)

    def to_persist(self) -> dict:
        """Shape for storage on the Activity row."""
        return {
            "classification_type": self.type,
            "classification_flags": self.flags,
            "classified_at": utc_now(),
        }


# ── Public entry points ─────────────────────────────────────────────────────


def classify(activity: Activity, laps: list[ActivityLap]) -> Classification | None:
    """Dispatch to sport-specific classifier.

    Returns None for sports we don't classify (e.g. WeightTraining).
    """
    sport = (activity.sport_type or "").lower()
    if "run" in sport:
        return _classify_run(activity, laps)
    if "ride" in sport or "cycle" in sport or "bike" in sport:
        return _classify_ride(activity)
    # WeightTraining, Yoga, Swim, Hike, etc. — skip for now.
    return None


def classify_and_persist(
    activity: Activity, laps: list[ActivityLap]
) -> Classification | None:
    """Classify and mutate the Activity fields (caller commits)."""
    result = classify(activity, laps)
    if result is None:
        return None
    for k, v in result.to_persist().items():
        setattr(activity, k, v)
    return result


# ── Run classifier ──────────────────────────────────────────────────────────


def _classify_run(
    activity: Activity, laps: list[ActivityLap]
) -> Classification:
    features = _run_features(activity, laps)

    # Strava race marker trumps heuristics.
    if activity.workout_type == 1:
        flags = _run_flags(activity, laps, features, run_type="race")
        return Classification(
            type="race", flags=flags, confidence=0.95, features=features
        )

    usable_laps = features["usable_lap_count"]

    # Intervals: bimodal pace pattern. Strongest signal first.
    if (
        features.get("max_pace_zone") is not None
        and features["max_pace_zone"] >= _RUN_INTERVALS_MIN_MAX_ZONE
        and not features["is_auto_splits"]
        and usable_laps >= 3
    ):
        run_type = "intervals"
        confidence = 0.9
    elif (
        features["speed_cv"] is not None
        and features["speed_cv"] >= _RUN_INTERVALS_SPEED_CV
        and features.get("max_pace_zone") is not None
        and features["max_pace_zone"] >= 3
    ):
        # High variance AND at least one tempo-or-harder lap. Gating on
        # max_pace_zone prevents walks / stop-and-go jogs (which have
        # high CV but never leave zone 1) from being called intervals.
        run_type = "intervals"
        confidence = 0.7
    # Tempo: steady but elevated.
    elif (
        features["speed_cv"] is not None
        and features["speed_cv"] < _RUN_STEADY_SPEED_CV
        and features["mean_pace_zone"] is not None
        and features["mean_pace_zone"] >= _RUN_TEMPO_MEAN_PACE_ZONE
    ):
        run_type = "tempo"
        confidence = 0.85
    # Easy: steady low-intensity.
    elif (
        features["speed_cv"] is not None
        and features["speed_cv"] < _RUN_STEADY_SPEED_CV
    ):
        run_type = "easy"
        confidence = 0.85
    else:
        # Fall through: unknown shape, but no interval markers → call it easy with
        # low confidence. Lets the user see it and override if needed.
        run_type = "easy"
        confidence = 0.4

    flags = _run_flags(activity, laps, features, run_type=run_type)
    return Classification(
        type=run_type, flags=flags, confidence=confidence, features=features
    )


def _run_features(
    activity: Activity, laps: list[ActivityLap]
) -> dict:
    usable = [
        lap for lap in laps
        if (lap.moving_time or 0) >= _ARTIFACT_MIN_MOVING_S
        or (lap.distance or 0) >= _ARTIFACT_MAX_DISTANCE_M
    ]

    speeds = [lap.average_speed for lap in usable if lap.average_speed]
    distances = [lap.distance for lap in usable if lap.distance]
    pace_zones = [lap.pace_zone for lap in usable if lap.pace_zone is not None]
    hrs = [lap.average_heartrate for lap in usable if lap.average_heartrate]

    is_auto_splits = _detect_auto_splits(distances)

    speed_cv = (
        statistics.stdev(speeds) / statistics.mean(speeds)
        if len(speeds) >= 2 and statistics.mean(speeds) > 0
        else None
    )
    mean_pace_zone = statistics.mean(pace_zones) if pace_zones else None
    max_pace_zone = max(pace_zones) if pace_zones else None

    # Very crude bimodality: gap between max and min HR across laps.
    hr_spread = max(hrs) - min(hrs) if len(hrs) >= 2 else None

    return {
        "lap_count": len(laps),
        "usable_lap_count": len(usable),
        "is_auto_splits": is_auto_splits,
        "speed_cv": speed_cv,
        "mean_pace_zone": mean_pace_zone,
        "max_pace_zone": max_pace_zone,
        "hr_spread": hr_spread,
        "duration_s": activity.moving_time,
        "distance_m": activity.distance,
    }


def _run_flags(
    activity: Activity,
    laps: list[ActivityLap],
    features: dict,
    *,
    run_type: str,
) -> list[str]:
    flags: list[str] = []

    # Long run — applies to any type, but most commonly easy.
    if (
        (activity.moving_time or 0) >= _RUN_LONG_DURATION_S
        or (activity.distance or 0) >= _RUN_LONG_DISTANCE_M
    ):
        flags.append("is_long")

    # Speed component: easy run with one or more fast laps (strides/fartlek-ish).
    if (
        run_type == "easy"
        and features.get("max_pace_zone") is not None
        and features["max_pace_zone"] >= _RUN_INTERVALS_MIN_MAX_ZONE
    ):
        flags.append("has_speed_component")

    # Warmup/cooldown: first and last usable lap both slower than the middle.
    usable = [
        lap for lap in laps
        if (lap.moving_time or 0) >= _ARTIFACT_MIN_MOVING_S
    ]
    if len(usable) >= 4:
        speeds = [lap.average_speed for lap in usable if lap.average_speed]
        if len(speeds) >= 4:
            middle = speeds[1:-1]
            middle_avg = sum(middle) / len(middle)
            if speeds[0] < middle_avg * 0.95 and speeds[-1] < middle_avg * 0.95:
                flags.append("has_warmup_cooldown")

    alt = _altitude_flag(activity.base_elevation_m)
    if alt:
        flags.append(alt)

    return flags


def _detect_auto_splits(distances: list[float]) -> bool:
    """True if all non-final lap distances are ~1 mile or ~1 km."""
    if len(distances) < 2:
        return False
    main = distances[:-1]  # ignore the final partial lap
    mile_match = all(abs(d - _AUTO_MILE_M) < _AUTO_SPLIT_TOLERANCE_M for d in main)
    km_match = all(abs(d - _AUTO_KM_M) < _AUTO_SPLIT_TOLERANCE_M for d in main)
    return mile_match or km_match


# ── Ride classifier ─────────────────────────────────────────────────────────


def _classify_ride(activity: Activity) -> Classification:
    features = _ride_features(activity)

    if activity.workout_type == 11:
        flags = _ride_flags(activity, features)
        return Classification(
            type="race", flags=flags, confidence=0.95, features=features
        )

    duration = activity.moving_time or 0
    vi = features.get("variability_index")
    avg_power = activity.average_power
    has_power = activity.device_watts is True

    if duration > 0 and duration <= _RIDE_RECOVERY_MAX_DURATION_S and (
        (avg_power is not None and avg_power < 100) or not has_power
    ):
        ride_type = "recovery"
        confidence = 0.6
    elif vi is not None and vi >= _RIDE_MIXED_MIN_VI:
        ride_type = "mixed"
        confidence = 0.75
    elif vi is not None and _RIDE_TEMPO_MIN_VI <= vi < _RIDE_TEMPO_MAX_VI and (
        avg_power is not None and avg_power >= 180
    ):
        # Tempo needs power signal; otherwise default to endurance.
        ride_type = "tempo"
        confidence = 0.7
    else:
        ride_type = "endurance"
        # Confidence depends on whether we have useful signals at all.
        confidence = 0.7 if has_power or activity.average_hr else 0.4

    flags = _ride_flags(activity, features)
    return Classification(
        type=ride_type, flags=flags, confidence=confidence, features=features
    )


def _ride_features(activity: Activity) -> dict:
    vi = None
    if activity.weighted_avg_power and activity.average_power:
        vi = activity.weighted_avg_power / activity.average_power

    elevation_per_km = None
    if activity.distance and activity.total_elevation is not None:
        km = activity.distance / 1000.0
        if km > 0:
            elevation_per_km = activity.total_elevation / km

    return {
        "variability_index": vi,
        "elevation_per_km": elevation_per_km,
        "duration_s": activity.moving_time,
        "distance_m": activity.distance,
        "has_device_watts": activity.device_watts is True,
    }


def _ride_flags(activity: Activity, features: dict) -> list[str]:
    flags: list[str] = []
    if (
        (activity.moving_time or 0) >= _RIDE_LONG_DURATION_S
        or (activity.distance or 0) >= _RIDE_LONG_DISTANCE_M
    ):
        flags.append("is_long")
    if (features.get("elevation_per_km") or 0) >= _RIDE_HILLY_M_PER_KM:
        flags.append("is_hilly")
    alt = _altitude_flag(activity.base_elevation_m)
    if alt:
        flags.append(alt)
    return flags


def _altitude_flag(elevation_m: float | None) -> str | None:
    """Return the altitude tier flag (or ``None`` for sea-level workouts).

    Tier bands:
        < 610 m   → no flag (sea level, default case)
        610–1500  → ``altitude_low``
        1500–2500 → ``altitude_moderate``
        ≥ 2500    → ``altitude_high``
    """
    if elevation_m is None:
        return None
    if elevation_m >= _ALT_HIGH_M:
        return "altitude_high"
    if elevation_m >= _ALT_MODERATE_M:
        return "altitude_moderate"
    if elevation_m >= _ALT_LOW_M:
        return "altitude_low"
    return None


# ── Convenience for tests / notebooks ────────────────────────────────────────


def describe(c: Classification) -> str:
    """Human-readable one-liner."""
    flags = f" [{', '.join(c.flags)}]" if c.flags else ""
    return f"{c.type}{flags} (confidence={c.confidence:.2f})"


def dump(c: Classification) -> dict:
    return asdict(c)
