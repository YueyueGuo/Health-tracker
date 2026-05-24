"""Tests for sport-type normalization across Apple Health (HAE) + Strava."""
from __future__ import annotations

import pytest

from backend.services.sport_mapping import (
    normalize_apple,
    normalize_strava,
    same_activity,
)


# ── normalize_apple ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Running", "run"),
        ("running", "run"),
        ("  Running  ", "run"),
        ("Outdoor Run", "run"),
        ("Cycling", "ride"),
        ("Outdoor Cycle", "ride"),
        ("Walking", "walk"),
        ("Hiking", "hike"),
        ("Pool Swim", "swim"),
        ("Open Water Swim", "swim"),
        ("Traditional Strength Training", "strength"),
        ("Functional Strength Training", "strength"),
        ("Yoga", "yoga"),
        ("HIIT", "hiit"),
        ("High Intensity Interval Training", "hiit"),
        ("Rowing", "row"),
        ("Elliptical", "elliptical"),
        ("Mixed Cardio", "cardio"),
    ],
)
def test_normalize_apple_known_buckets(name, expected):
    assert normalize_apple(name) == expected


def test_normalize_apple_unknown_falls_through_to_other():
    # Unknown HAE display strings preserve the workout instead of
    # raising / 422-ing the entire ingest.
    assert normalize_apple("Hopscotch") == "other"


def test_normalize_apple_empty_returns_other():
    assert normalize_apple("") == "other"
    assert normalize_apple(None) == "other"


# ── normalize_strava ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "sport_type,expected",
    [
        ("Run", "run"),
        ("TrailRun", "run"),
        ("VirtualRun", "run"),
        ("Ride", "ride"),
        ("VirtualRide", "ride"),
        ("GravelRide", "ride"),
        ("MountainBikeRide", "ride"),
        ("EBikeRide", "ride"),
        ("Walk", "walk"),
        ("Hike", "hike"),
        ("Swim", "swim"),
        ("WeightTraining", "strength"),
        ("Crossfit", "strength"),
        ("Yoga", "yoga"),
        ("HighIntensityIntervalTraining", "hiit"),
        ("Rowing", "row"),
        ("Elliptical", "elliptical"),
    ],
)
def test_normalize_strava_known_buckets(sport_type, expected):
    assert normalize_strava(sport_type) == expected


def test_normalize_strava_unknown_returns_none():
    # Strava's enum is closed; an unknown value means "no mapping"
    # rather than "other" — dedup must NOT match.
    assert normalize_strava("Skiing") is None


def test_normalize_strava_handles_case_variation():
    # Defensive — if a caller passes the value lower-case, we still
    # match the canonical CamelCase entry.
    assert normalize_strava("run") == "run"


def test_normalize_strava_empty_or_none():
    assert normalize_strava("") is None
    assert normalize_strava(None) is None


# ── same_activity (truth table) ─────────────────────────────────────


@pytest.mark.parametrize(
    "apple,strava",
    [
        ("Running", "Run"),
        ("Running", "TrailRun"),
        ("Running", "VirtualRun"),
        ("Cycling", "Ride"),
        ("Cycling", "GravelRide"),
        ("Walking", "Walk"),
        ("Hiking", "Hike"),
        ("Pool Swim", "Swim"),
        ("Traditional Strength Training", "WeightTraining"),
        ("Functional Strength Training", "WeightTraining"),
        ("HIIT", "HighIntensityIntervalTraining"),
    ],
)
def test_same_activity_true(apple, strava):
    assert same_activity(apple, strava) is True


@pytest.mark.parametrize(
    "apple,strava",
    [
        ("Running", "Ride"),
        ("Cycling", "Run"),
        ("Walking", "Run"),
        ("Yoga", "WeightTraining"),
        ("Running", "Walk"),
        # Unknown Strava → never match
        ("Running", "Skiing"),
        # "other" Apple → never match
        ("Hopscotch", "Run"),
    ],
)
def test_same_activity_false(apple, strava):
    assert same_activity(apple, strava) is False
