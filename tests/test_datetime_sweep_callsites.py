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

See ``docs/audit-001-datetime-sweep-audit.md``.
"""
from __future__ import annotations

from datetime import datetime, timezone

from backend.routers.strength import _normalize_performed_at
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


def test_normalize_performed_at_handles_none():
    assert _normalize_performed_at(None) is None


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
