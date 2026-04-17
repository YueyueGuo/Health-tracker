"""Tests for backend.clients.strava rate-limit parsing + helpers.

Focuses on the headers and quota-state helpers; full OAuth/client-method
coverage is out of scope for the backfill fix and can come later.
"""
from __future__ import annotations

import httpx
import pytest

from backend.clients import strava as strava_mod
from backend.clients.strava import StravaClient, StravaRateLimitError


@pytest.fixture(autouse=True)
def reset_quota_state():
    """Reset the module-level quota state between tests."""
    strava_mod._quota_state.update(
        short_used=None,
        short_limit=100,
        long_used=None,
        long_limit=1000,
        read_short_used=None,
        read_short_limit=100,
        read_long_used=None,
        read_long_limit=1000,
        updated_at=None,
    )
    yield


# ── Header parsing ──────────────────────────────────────────────────


def test_parses_combined_quota_headers():
    StravaClient._update_quota_from_headers(httpx.Headers({
        "X-Ratelimit-Usage": "72,642",
        "X-Ratelimit-Limit": "200,2000",
    }))
    q = StravaClient.quota_usage()
    assert q["short_used"] == 72
    assert q["long_used"] == 642
    assert q["short_limit"] == 200
    assert q["long_limit"] == 2000
    # Read quotas untouched, remain at defaults
    assert q["read_short_used"] is None
    assert q["read_long_used"] is None


def test_parses_read_quota_headers():
    """The read-only quota family is the one that actually stops our backfill
    at 1000/day even when combined has room. It MUST be parsed separately.
    """
    StravaClient._update_quota_from_headers(httpx.Headers({
        "X-Readratelimit-Usage": "99,1000",
        "X-Readratelimit-Limit": "100,1000",
    }))
    q = StravaClient.quota_usage()
    assert q["read_short_used"] == 99
    assert q["read_long_used"] == 1000
    assert q["read_short_limit"] == 100
    assert q["read_long_limit"] == 1000


def test_parses_both_families_in_one_response():
    StravaClient._update_quota_from_headers(httpx.Headers({
        "X-Ratelimit-Usage": "1,1020",
        "X-Ratelimit-Limit": "200,2000",
        "X-Readratelimit-Usage": "1,1000",
        "X-Readratelimit-Limit": "100,1000",
    }))
    q = StravaClient.quota_usage()
    assert q["long_used"] == 1020
    assert q["long_limit"] == 2000
    assert q["read_long_used"] == 1000
    assert q["read_long_limit"] == 1000


def test_malformed_usage_header_is_ignored():
    StravaClient._update_quota_from_headers(httpx.Headers({
        "X-Ratelimit-Usage": "not,valid,header",
    }))
    q = StravaClient.quota_usage()
    assert q["short_used"] is None
    assert q["long_used"] is None


# ── quota_exhausted ─────────────────────────────────────────────────


def test_quota_exhausted_false_with_no_data():
    assert StravaClient.quota_exhausted() is False


def test_quota_exhausted_combined_daily():
    strava_mod._quota_state.update(long_used=1950, long_limit=2000)
    assert StravaClient.quota_exhausted(fraction=0.95) is True


def test_quota_exhausted_read_daily_trips_even_when_combined_has_room():
    """This was the actual backfill bug: combined at 1020/2000 (well under)
    but read at 1000/1000 — client must report exhausted.
    """
    strava_mod._quota_state.update(
        long_used=1020, long_limit=2000,
        read_long_used=1000, read_long_limit=1000,
    )
    assert StravaClient.quota_exhausted() is True


def test_quota_exhausted_read_short():
    strava_mod._quota_state.update(read_short_used=100, read_short_limit=100)
    assert StravaClient.quota_exhausted() is True


def test_quota_exhausted_respects_fraction():
    strava_mod._quota_state.update(long_used=500, long_limit=2000)  # 25%
    assert StravaClient.quota_exhausted(fraction=0.95) is False
    assert StravaClient.quota_exhausted(fraction=0.20) is True


# ── which_quota_exhausted (diagnostics) ─────────────────────────────


def test_which_quota_exhausted_identifies_read_daily():
    strava_mod._quota_state.update(
        long_used=1020, long_limit=2000,
        read_long_used=1000, read_long_limit=1000,
    )
    hit = StravaClient.which_quota_exhausted()
    assert hit == ["read-daily"]


def test_which_quota_exhausted_identifies_multiple():
    strava_mod._quota_state.update(
        short_used=200, short_limit=200,
        read_long_used=1000, read_long_limit=1000,
    )
    hit = StravaClient.which_quota_exhausted()
    assert "combined-15m" in hit
    assert "read-daily" in hit


def test_which_quota_exhausted_empty_when_clear():
    strava_mod._quota_state.update(short_used=10, long_used=100)
    assert StravaClient.which_quota_exhausted() == []


# ── daily_quota_exhausted (backfill-specific helper) ────────────────


def test_daily_quota_exhausted_distinguishes_from_short():
    """A 15-min short-window hit is survivable (sleep 15min), but a daily
    hit needs a full day. The backfill loop uses daily_quota_exhausted
    specifically so it bails instead of looping.
    """
    # Short-window tripped, daily clear → NOT considered daily-exhausted.
    strava_mod._quota_state.update(
        short_used=200, short_limit=200,
        long_used=100, long_limit=2000,
    )
    assert StravaClient.daily_quota_exhausted() is False

    # Read daily tripped → daily-exhausted, even if combined has room.
    strava_mod._quota_state.update(read_long_used=1000, read_long_limit=1000)
    assert StravaClient.daily_quota_exhausted() is True


# ── 429 handling ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_raises_on_429_and_parses_retry_after(monkeypatch):
    """Verify a 429 raises StravaRateLimitError carrying retry_after and
    that quota state is updated from the 429 response headers too.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={
                "X-Ratelimit-Usage": "1,1020",
                "X-Ratelimit-Limit": "200,2000",
                "X-Readratelimit-Usage": "1,1000",
                "X-Readratelimit-Limit": "100,1000",
                "Retry-After": "42",
            },
            text="Rate Limit Exceeded",
        )

    client = StravaClient()
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client._access_token = "token"
    client._token_expires_at = 9_999_999_999  # skip refresh
    try:
        with pytest.raises(StravaRateLimitError) as exc:
            await client._get("/activities/123")
        assert exc.value.retry_after == 42
        # Headers from the 429 should still update quota state so the caller
        # can decide to bail (daily exhausted) vs retry (short window).
        q = StravaClient.quota_usage()
        assert q["read_long_used"] == 1000
        assert StravaClient.daily_quota_exhausted() is True
    finally:
        await client.close()
