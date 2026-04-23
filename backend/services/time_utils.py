"""Shared time helpers for service and router code.

The database currently stores ``DateTime`` columns as naive values, while API
timestamps are usually emitted as timezone-aware UTC strings. Keeping those
choices explicit avoids drifting back to deprecated naive-UTC calls.
"""

from __future__ import annotations

from datetime import date, datetime, timezone


def utc_now() -> datetime:
    """Timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)


def utc_now_naive() -> datetime:
    """Current UTC datetime with tzinfo stripped for naive DB columns."""
    return utc_now().replace(tzinfo=None)


def local_today() -> date:
    """Current local calendar date for local, single-user analytics windows."""
    return datetime.now().date()
