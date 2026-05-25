"""Health Auto Export (HAE) payload parser.

HAE — the iOS app that exports Apple Health data — POSTs a JSON
envelope of the shape::

    {"data": {"workouts": [HAEWorkout, ...]}}

with all numeric fields wrapped as ``{"qty": <number>, "units": "<u>"}``
and timestamps formatted as ``"YYYY-MM-DD HH:MM:SS ±HHMM"``.

This module owns:

* Pydantic models that validate the wire shape (``HAEBatch``,
  ``HAEWorkout``, ``HAEQty``).
* ``parse_hae_datetime`` — the lone timestamp parser. Returns naive UTC
  to match the rest of the project's DB column convention.
* ``ParsedWorkout`` — flat dataclass the ingest service consumes (so
  ingest doesn't have to walk Pydantic models).
* ``flatten_hae_workout`` — the wire → ParsedWorkout mapper. Validates
  units (rejects mismatched units rather than silently converting).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict

# HAE → Settings → Units lets the user pick metric or imperial per
# metric type, and a US-defaults install ships imperial for distance /
# speed / elevation. Convert into the canonical unit we persist
# (meters, m/s, kcal, count/min). Stay narrow — unknown units still
# fail loud rather than silently guess.
_UNIT_CONVERSIONS: dict[str, dict[str, float]] = {
    "active_energy": {
        "kcal": 1.0,
        "Cal": 1.0,           # HAE writes food calorie interchangeably with kcal.
        "kJ": 1.0 / 4.184,    # 1 kJ = 0.239006 kcal.
    },
    "distance": {
        "m": 1.0,
        "km": 1000.0,
        "mi": 1609.344,       # international mile, exact.
        "yd": 0.9144,
        "ft": 0.3048,
    },
    "hr": {
        "count/min": 1.0,
        "bpm": 1.0,
    },
    "speed": {
        "m/s": 1.0,
        "km/h": 1000.0 / 3600.0,
        "mph": 0.44704,       # = 1609.344 / 3600.
    },
    "elevation": {
        "m": 1.0,
        "ft": 0.3048,
    },
}


class HAEQty(BaseModel):
    """HAE's wrapped scalar — ``{"qty": <number>, "units": "<unit>"}``."""

    model_config = ConfigDict(extra="ignore")

    qty: float
    units: str

    def as_unit(self, target_unit: str | set[str]) -> float:
        """Return ``qty`` if ``units`` matches; raise ``ValueError`` otherwise.

        ``target_unit`` may be a single string or a set of acceptable
        units (HAE writes ``"kcal"`` and ``"Cal"`` interchangeably for
        kilocalories on some firmwares).
        """
        accepted = {target_unit} if isinstance(target_unit, str) else target_unit
        if self.units not in accepted:
            raise ValueError(
                f"unexpected HAE units: got {self.units!r}, expected {sorted(accepted)!r}"
            )
        return float(self.qty)


# HAE can send any metric field in one of two shapes depending on the
# user's "Aggregate workout data" toggle: a scalar {qty, units} (HAEQty)
# or a per-minute time series [{date, qty, units, source}, ...]. Declared
# fields must accept either or pydantic 422s the whole batch.
HAEMetric = HAEQty | list[dict[str, Any]] | None


class HAEWorkout(BaseModel):
    """Single workout entry from an HAE batch.

    Numeric metric fields arrive either as a scalar :class:`HAEQty` or
    as a time-series list (see :data:`HAEMetric`). Extra series like
    ``heartRateData`` / ``route`` ride along via Pydantic's
    ``model_extra`` so they land intact in ``raw_payload``.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str
    name: str
    start: str
    end: str
    duration: float
    activeEnergyBurned: HAEMetric = None
    totalEnergy: HAEMetric = None
    distance: HAEMetric = None
    avgHeartRate: HAEMetric = None
    maxHeartRate: HAEMetric = None
    minHeartRate: HAEMetric = None
    avgSpeed: HAEMetric = None
    maxSpeed: HAEMetric = None
    elevationUp: HAEMetric = None
    flightsClimbed: HAEMetric = None
    stepCount: HAEMetric = None
    stepCadence: HAEMetric = None
    location: str | None = None


class _HAEData(BaseModel):
    model_config = ConfigDict(extra="ignore")
    workouts: list[HAEWorkout] = []


class HAEBatch(BaseModel):
    """Top-level HAE export envelope."""

    model_config = ConfigDict(extra="ignore")
    data: _HAEData


def parse_hae_datetime(s: str) -> datetime:
    """Parse HAE's ``"YYYY-MM-DD HH:MM:SS ±HHMM"`` into naive UTC.

    HAE always emits an explicit offset (the iOS shortcut uses
    ``ISO 8601 with timezone``). We normalize to UTC and strip
    ``tzinfo`` so the value lines up with how other models persist
    datetimes (see `backend.services.time_utils`).

    Raises ``ValueError`` on unparseable input.
    """
    if not s or not isinstance(s, str):
        raise ValueError(f"unparseable HAE datetime: {s!r}")
    try:
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S %z")
    except ValueError as e:
        raise ValueError(f"unparseable HAE datetime: {s!r}") from e
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


@dataclass
class ParsedWorkout:
    """Flat shape the ingest service consumes — no nested Pydantic.

    Includes the original HAE workout payload as ``raw_payload`` so the
    `health_data_points.raw_payload` column captures the full input
    (including heavy `heartRateData[]` / `route[]` arrays we don't
    project into typed columns in v1).
    """

    external_id: str
    activity_type: str
    start_time: datetime
    end_time: datetime
    duration_s: int | None
    active_energy_kcal: float | None
    distance_m: float | None
    avg_speed_mps: float | None
    avg_hr: float | None
    max_hr: float | None
    total_elevation_m: float | None
    raw_payload: dict[str, Any]


def _opt_qty(qty: HAEMetric, unit_key: str) -> float | None:
    """Convert an :class:`HAEQty` into our canonical unit.

    Recognises both the metric and imperial units HAE emits depending
    on the user's HAE → Settings → Units choice (see
    :data:`_UNIT_CONVERSIONS`). Unknown units still raise
    ``ValueError`` — silent unit guessing is worse than dropping a
    workout.

    Series-shaped values (HAE's ``[{date, qty, units}, ...]`` format,
    emitted when "Aggregate workout data" is off in HAE) return
    ``None`` — the raw series is still preserved in ``raw_payload``
    via ``model_dump``. We don't aggregate; that's a feature decision.
    """
    if qty is None or isinstance(qty, list):
        return None
    factors = _UNIT_CONVERSIONS[unit_key]
    if qty.units not in factors:
        raise ValueError(
            f"unexpected HAE units: got {qty.units!r}, "
            f"expected one of {sorted(factors)!r}"
        )
    return float(qty.qty) * factors[qty.units]


def flatten_hae_workout(hae: HAEWorkout) -> ParsedWorkout:
    """HAE → ParsedWorkout. Validates units; raises ``ValueError`` on mismatch.

    Imported by ``backend.services.apple_health_ingest``. Kept here so
    parser tests can exercise it without touching the DB.
    """
    from backend.services.sport_mapping import normalize_apple

    start_dt = parse_hae_datetime(hae.start)
    end_dt = parse_hae_datetime(hae.end)
    duration_s = int(hae.duration) if hae.duration is not None else None

    active_energy_kcal = _opt_qty(hae.activeEnergyBurned, "active_energy")
    distance_m = _opt_qty(hae.distance, "distance")
    avg_speed_mps = _opt_qty(hae.avgSpeed, "speed")
    avg_hr = _opt_qty(hae.avgHeartRate, "hr")
    max_hr = _opt_qty(hae.maxHeartRate, "hr")
    elevation_m = _opt_qty(hae.elevationUp, "elevation")

    return ParsedWorkout(
        external_id=hae.id,
        activity_type=normalize_apple(hae.name),
        start_time=start_dt,
        end_time=end_dt,
        duration_s=duration_s,
        active_energy_kcal=active_energy_kcal,
        distance_m=distance_m,
        avg_speed_mps=avg_speed_mps,
        avg_hr=avg_hr,
        max_hr=max_hr,
        total_elevation_m=elevation_m,
        raw_payload=hae.model_dump(by_alias=False),
    )
