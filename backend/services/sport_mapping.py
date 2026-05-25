"""Cross-source sport-type normalization.

Apple Health (via Health Auto Export) and Strava both emit human-
readable activity-type strings drawn from disjoint vocabularies. The
dedup pipeline needs a single normalized label so "Running" (Apple)
and "TrailRun" (Strava) collapse to the same bucket.

Public API
----------
- ``normalize_apple(name)`` — lowercase HAE display string → normalized.
- ``normalize_strava(t)`` — Strava ``sport_type`` → normalized or None.
- ``same_activity(apple_name, strava_type)`` — True iff both normalize
  to the same non-None bucket.

Unknown Apple types preserve as ``"other"`` so we never drop a workout
on ingest just because the mapping table is incomplete; unknown
Strava types return ``None`` so dedup conservatively declines to
match.
"""
from __future__ import annotations

# HAE emits display strings (e.g. "Running", "Cycling"); keys here are
# the lowercased forms (see `normalize_apple`).
APPLE_TO_NORMALIZED: dict[str, str] = {
    "running": "run",
    "outdoor run": "run",
    "indoor run": "run",
    "treadmill running": "run",
    "cycling": "ride",
    "outdoor cycle": "ride",
    "indoor cycle": "ride",
    "outdoor cycling": "ride",
    "indoor cycling": "ride",
    "walking": "walk",
    "hiking": "hike",
    "pool swim": "swim",
    "open water swim": "swim",
    "swimming": "swim",
    "traditional strength training": "strength",
    "functional strength training": "strength",
    "core training": "strength",
    "yoga": "yoga",
    "high intensity interval training": "hiit",
    "hiit": "hiit",
    "elliptical": "elliptical",
    "rowing": "row",
    "mixed cardio": "cardio",
}


# Strava ``sport_type`` is a closed enum on the Strava side. Values are
# CamelCase (e.g. "Run", "TrailRun", "VirtualRide", "WeightTraining").
# We keep the keys in their canonical CamelCase form and lowercase
# during lookup.
STRAVA_TO_NORMALIZED: dict[str, str] = {
    # Runs
    "Run": "run",
    "TrailRun": "run",
    "VirtualRun": "run",
    # Rides
    "Ride": "ride",
    "VirtualRide": "ride",
    "GravelRide": "ride",
    "MountainBikeRide": "ride",
    "EBikeRide": "ride",
    "EMountainBikeRide": "ride",
    "Handcycle": "ride",
    "Velomobile": "ride",
    # Walk / hike
    "Walk": "walk",
    "Hike": "hike",
    # Swim
    "Swim": "swim",
    # Strength
    "WeightTraining": "strength",
    "Workout": "strength",
    "Crossfit": "strength",
    # Yoga
    "Yoga": "yoga",
    # HIIT
    "HighIntensityIntervalTraining": "hiit",
    # Other cardio
    "Elliptical": "elliptical",
    "Rowing": "row",
    "VirtualRow": "row",
    "StairStepper": "cardio",
}


def normalize_apple(name: str | None) -> str:
    """Normalize an HAE display string. Returns ``"other"`` for unknowns.

    Empty / None input also normalizes to ``"other"`` rather than
    raising, so a missing ``name`` field doesn't drop the workout at
    ingest.
    """
    if not name:
        return "other"
    return APPLE_TO_NORMALIZED.get(name.strip().lower(), "other")


def normalize_strava(t: str | None) -> str | None:
    """Normalize a Strava ``sport_type``. Returns ``None`` if unknown.

    Strava's enum is closed, so an unknown value here means we genuinely
    don't have a mapping — dedup should *not* match in that case.
    """
    if not t:
        return None
    key = t.strip()
    # Strava sends CamelCase; tolerate lowercase callers by checking
    # the lower-cased key against a one-shot lower-case map.
    if key in STRAVA_TO_NORMALIZED:
        return STRAVA_TO_NORMALIZED[key]
    lower = key.lower()
    for k, v in STRAVA_TO_NORMALIZED.items():
        if k.lower() == lower:
            return v
    return None


def same_activity(apple_name: str | None, strava_type: str | None) -> bool:
    """True iff both names normalize to the same non-None, non-other bucket.

    ``other`` doesn't match anything — it's a "preserve the row but
    don't dedup it" sentinel.
    """
    a = normalize_apple(apple_name)
    s = normalize_strava(strava_type)
    if a == "other" or s is None:
        return False
    return a == s


# Inverse of `normalize_strava` for the subset the frontend's
# `classifyActivity` (frontend/src/lib/historyEvents.ts) recognizes.
# Apple workouts are stored with the normalized lowercase label
# ("run", "ride", "strength", …) but the detail-page sport switch
# in `ActivityDetail.tsx` reads CamelCase ("Run", "Ride",
# "WeightTraining"). This helper bridges the two without leaking the
# full Strava enum (we only need the buckets the frontend handles).
_NORMALIZED_TO_STRAVA_VIEW: dict[str, str] = {
    "run": "Run",
    "ride": "Ride",
    "strength": "WeightTraining",
    "walk": "Walk",
    "hike": "Hike",
    "swim": "Swim",
    "yoga": "Yoga",
    "other": "Workout",
}


def normalized_to_strava_view(name: str | None) -> str:
    """Map a normalized sport label to the CamelCase form the frontend uses.

    Returns ``"Workout"`` for unknown / None inputs so the frontend's
    fallback "Other" branch still gets a label that classifies cleanly.
    """
    if not name:
        return "Workout"
    return _NORMALIZED_TO_STRAVA_VIEW.get(name.strip().lower(), "Workout")
