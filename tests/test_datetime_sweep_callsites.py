"""Call-site behaviour tests for the timezone-aware sweep fixes.

These cover the small normalisation hooks added when the audit
discovered that several call sites still passed naive datetimes to the
columns the sweep marked tz-aware:

* ``backend.routers.strength._normalize_performed_at`` — attaches UTC
  tzinfo to the frontend's naive-local ``performed_at`` value before
  INSERT.
* ``backend.services.whoop_sync._parse_dt`` — now returns tz-aware UTC
  rather than naive-UTC so ``WhoopWorkout.start`` /``end`` and
  ``SleepSession.bed_time``/``wake_time`` writes carry tzinfo.
* ``backend.services.eight_sleep_sync._attach_utc_to_sleep_times`` —
  attaches UTC tzinfo to naive ``bed_time`` / ``wake_time`` fields
  produced by ``_extract_fields``.

See ``docs/audit-001-datetime-sweep-audit.md``.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.routers.strength import _normalize_performed_at
from backend.services.eight_sleep_sync import _attach_utc_to_sleep_times
from backend.services.whoop_sync import _parse_dt


def test_normalize_performed_at_attaches_utc_to_naive():
    naive = datetime(2026, 4, 16, 18, 30, 0)
    out = _normalize_performed_at(naive)
    assert out is not None
    assert out.tzinfo is timezone.utc
    # Same wall-clock value — only the tzinfo label was added.
    assert out.replace(tzinfo=None) == naive


def test_normalize_performed_at_passes_through_tz_aware():
    aware = datetime(2026, 4, 16, 18, 30, 0, tzinfo=timezone.utc)
    out = _normalize_performed_at(aware)
    assert out is aware


def test_normalize_performed_at_passes_through_non_utc_offset():
    """A frontend that ever sends offset-aware ISO (e.g. ``-07:00``) must
    be passed through unchanged so the original instant is preserved."""
    pacific = timezone(timedelta(hours=-7))
    aware = datetime(2026, 5, 1, 18, 30, 0, tzinfo=pacific)
    out = _normalize_performed_at(aware)
    assert out is aware
    assert out.tzinfo is pacific
    # Same instant as 01:30 UTC the next day — the helper must not
    # silently relabel it as UTC.
    assert out.astimezone(timezone.utc) == datetime(
        2026, 5, 2, 1, 30, 0, tzinfo=timezone.utc
    )


def test_normalize_performed_at_handles_none():
    assert _normalize_performed_at(None) is None


def test_attach_utc_to_sleep_times_tags_naive_in_place():
    naive_bed = datetime(2026, 5, 1, 23, 15)
    naive_wake = datetime(2026, 5, 2, 7, 5)
    fields = {"bed_time": naive_bed, "wake_time": naive_wake, "total_sleep_sec": 28200}

    out = _attach_utc_to_sleep_times(fields)

    assert out is fields  # In-place + return for convenience.
    assert out["bed_time"].tzinfo is timezone.utc
    assert out["wake_time"].tzinfo is timezone.utc
    # Wall-clock value preserved.
    assert out["bed_time"].replace(tzinfo=None) == naive_bed
    assert out["wake_time"].replace(tzinfo=None) == naive_wake
    # Other fields untouched.
    assert out["total_sleep_sec"] == 28200


def test_attach_utc_to_sleep_times_passes_through_already_aware():
    aware = datetime(2026, 5, 1, 23, 15, tzinfo=timezone.utc)
    fields = {"bed_time": aware, "wake_time": None}

    out = _attach_utc_to_sleep_times(fields)

    assert out["bed_time"] is aware
    assert out["wake_time"] is None


def test_attach_utc_to_sleep_times_handles_missing_keys():
    """``_extract_fields`` may omit ``bed_time`` / ``wake_time`` on
    nights with no interval payload — the helper must not raise."""
    fields = {"total_sleep_sec": 0}
    out = _attach_utc_to_sleep_times(fields)
    assert out == {"total_sleep_sec": 0}


def test_whoop_parse_dt_returns_tz_aware_utc():
    """``_parse_dt`` must keep tzinfo so writes to ``bed_time`` /
    ``wake_time`` / ``WhoopWorkout.start`` / ``end`` are tz-aware."""
    out = _parse_dt("2026-04-26T05:47:00.000Z")
    assert out is not None
    assert out.tzinfo is not None
    # Converts to UTC regardless of source offset.
    assert out == datetime(2026, 4, 26, 5, 47, 0, tzinfo=timezone.utc)


def test_whoop_parse_dt_converts_offset_to_utc():
    out = _parse_dt("2026-04-26T01:47:00-04:00")
    assert out is not None
    assert out.tzinfo is not None
    assert out == datetime(2026, 4, 26, 5, 47, 0, tzinfo=timezone.utc)


def test_whoop_parse_dt_returns_none_for_invalid():
    assert _parse_dt(None) is None
    assert _parse_dt("") is None
    assert _parse_dt("not-a-date") is None
