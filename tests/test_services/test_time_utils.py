from __future__ import annotations

from datetime import date, timezone

from backend.services.time_utils import local_today, utc_now, utc_now_naive


def test_utc_now_is_timezone_aware_utc():
    now = utc_now()

    assert now.tzinfo is not None
    assert now.utcoffset() == timezone.utc.utcoffset(now)


def test_utc_now_naive_strips_tzinfo_for_db_columns():
    now = utc_now_naive()

    assert now.tzinfo is None


def test_local_today_returns_date():
    assert isinstance(local_today(), date)
