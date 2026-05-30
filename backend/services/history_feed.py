"""Unified cursor-paginated history feed.

Backs ``GET /api/dashboard/history-feed``. Merges three independently
ordered sources — activities (Strava + Apple, via ``list_activity_feed``),
sleep (``SleepSession``), and strength sessions (``list_sessions``) —
into ONE newest-first stream behind a single opaque cursor.

The merge problem: each source is ordered by its own date field, so
paging them together without dropping or duplicating rows at page
boundaries requires a single globally-comparable timeline key per row::

    (timestamp_naive_utc, source_rank, id)

* ``timestamp_naive_utc`` — the row's sort instant, normalized to a
  *naive* datetime so all three sources compare consistently. The client
  (``frontend/src/lib/historyEvents.ts``) sorts on:
  - activity: ``start_date_local or start_date``
  - sleep: ``wake_time or {date}T07:00:00``
  - strength: ``{date}T12:00:00``
  Activity values can be tz-aware (the columns are ``timestamptz``); we
  convert those to UTC then drop tzinfo. Sleep/strength stamps are
  already naive local and are used as-is (tzinfo stripped defensively).
* ``source_rank`` — activity=0, sleep=1, strength=2; breaks ties on
  equal timestamp across sources.
* ``id`` — activity ``id``, sleep ``id`` (ints). Strength has no integer
  id, so its ``date`` string is the within-source tiebreak.

The cursor encodes the composite key of the LAST row emitted on the
previous page as ``base64("{iso_ts}|{source_rank}|{id}")``. Paging is
strict composite less-than (newest-first): a row qualifies iff
``(ts, rank, id) < (cursor_ts, cursor_rank, cursor_id)``. A missing,
empty, or malformed cursor is treated as the first page (no lower
bound) — it never raises.

Each source is over-fetched ``limit + 1`` candidates from the same
cursor anchor (SQL ``<=`` on the timestamp lower bound; the strict
composite filter is then applied in Python to drop the cursor row and
anything ordered after it). The candidates are sort-merged on the
composite key (mirroring the Python merge in
``activity_feed.py``), the top ``limit`` are taken, ``next_cursor`` is
the composite key of the last taken row, and ``has_more`` is true iff
more candidates remained beyond ``limit``.
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime, time, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import SleepSession
from backend.routers.sleep import _sleep_dict
from backend.services.activity_feed import list_activity_feed
from backend.services.strength import list_sessions

# Source ordering for tie-breaks on equal timestamp.
_RANK_ACTIVITY = 0
_RANK_SLEEP = 1
_RANK_STRENGTH = 2

# Per-source over-fetch slack. The SQL window is bounded *inclusive* of the
# cursor's instant/day so same-boundary rows survive for the strict Python
# tiebreak; the strict filter then drops the cursor row plus anything
# sharing its exact boundary. ``_SLACK`` reserves extra over-fetch slots so
# those dropped rows never starve the ``limit + 1`` qualifying candidate set
# (which would otherwise flip ``has_more`` false and silently drop older
# rows). Given the data shapes (sleep unique on ``(source, date)`` → at most
# an eight_sleep + whoop pair per day; one strength session per ``date``;
# second-resolution activity timestamps), a small constant covers every
# realistic same-boundary cluster.
_SLACK = 8

# A composite timeline key: (timestamp_naive_utc, source_rank, id_str).
# ``id`` is rendered as a string so activity/sleep ints and strength's
# ``date`` string share one comparable tuple inside a single source. The
# cross-source compare only ever happens after ``source_rank`` has
# already separated the families, so the id type never mixes.
TimelineKey = tuple[datetime, int, str]


def _to_naive_utc(dt: datetime) -> datetime:
    """Normalize a datetime to naive UTC.

    tz-aware values (Strava/Apple ``timestamptz``) are converted to UTC
    then stripped of tzinfo; already-naive local values (Eight Sleep /
    Whoop bed/wake, strength stamps) are returned unchanged. The result
    is always naive so the three sources compare with the same wall
    instant the client sorts on.
    """
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _parse_iso(value: str) -> datetime:
    """Parse an ISO timestamp string to a naive-UTC datetime."""
    return _to_naive_utc(datetime.fromisoformat(value))


def _activity_key(row: dict[str, Any]) -> TimelineKey:
    raw = row.get("start_date_local") or row.get("start_date")
    ts = _parse_iso(raw) if raw else datetime.min
    return (ts, _RANK_ACTIVITY, str(row["id"]))


def _sleep_key(row: dict[str, Any]) -> TimelineKey:
    wake = row.get("wake_time")
    if wake:
        ts = _parse_iso(wake)
    else:
        ts = datetime.combine(_parse_date(row["date"]), time(7, 0, 0))
    return (ts, _RANK_SLEEP, str(row["id"]))


def _strength_key(row: dict[str, Any]) -> TimelineKey:
    ts = datetime.combine(_parse_date(row["date"]), time(12, 0, 0))
    return (ts, _RANK_STRENGTH, row["date"])


def _parse_date(value: str):
    from datetime import date as _date

    return _date.fromisoformat(value[:10])


# ── Cursor encode / decode ──────────────────────────────────────────


def encode_cursor(key: TimelineKey) -> str:
    """Opaque base64 of ``{iso_ts}|{source_rank}|{id}``."""
    ts, rank, id_str = key
    raw = f"{ts.isoformat()}|{rank}|{id_str}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str | None) -> TimelineKey | None:
    """Decode a cursor to its composite key, or ``None`` for first page.

    Empty / missing / malformed cursors return ``None`` (first page);
    decoding never raises.
    """
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        ts_str, rank_str, id_str = raw.split("|", 2)
        ts = datetime.fromisoformat(ts_str)
        if ts.tzinfo is not None:
            ts = _to_naive_utc(ts)
        return (ts, int(rank_str), id_str)
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None


# ── Feed ────────────────────────────────────────────────────────────


async def list_history_feed(
    db: AsyncSession,
    *,
    cursor: str | None,
    limit: int,
    include_superseded: bool,
) -> dict[str, Any]:
    """Merged, cursor-paginated newest-first history feed.

    Returns ``{activities, sleep, strength, next_cursor, has_more}``
    where the three arrays carry only the rows whose composite key
    landed in this page's window (so the client's ``buildHistoryEvents``
    consumes them unchanged).
    """
    cursor_key = decode_cursor(cursor)
    # The cursor's naive-UTC instant. ``None`` on the first page. Keyset
    # paging walks *backward* in time, so each source is bounded with an
    # inclusive *upper* bound at the cursor (SQL ``<=``); the strict
    # composite filter below then drops the cursor row itself and anything
    # ordered after it. The SQL bound is intentionally inclusive (and, for
    # the tz-aware activity columns, widened by a day) so a row whose
    # precise composite key is just shy of the cursor still survives SQL
    # and is judged by the exact Python comparison rather than a lossy
    # date/timestamp truncation.
    cutoff_ts = cursor_key[0] if cursor_key is not None else None

    # We need ``limit + 1`` qualifying candidates (strictly older than the
    # cursor) to fill a page AND detect ``has_more``. The SQL bound is
    # *inclusive* of the cursor instant/day so same-boundary rows survive
    # for the strict Python tiebreak, which means a few already-emitted
    # rows (the cursor row itself + any sharing its boundary) can occupy
    # over-fetch slots and then be dropped by the strict filter. ``slack``
    # absorbs those so the qualifying candidate set never underfills below
    # ``limit + 1`` while older rows still exist. ``_SLACK`` is a small
    # constant: at most one cursor row plus a per-source same-boundary
    # dedup pair (e.g. eight_sleep + whoop on one date).
    over = limit + 1
    fetch_n = over + _SLACK

    # ── Activities ──────────────────────────────────────────────────
    # ``list_activity_feed`` is shared with ``/api/activities``. We pass a
    # tz-aware UTC ``before`` upper bound at the cursor instant and a floor
    # ``cutoff`` of the epoch, over-fetch ``fetch_n``, then post-filter in
    # Python on the exact composite key (which sorts on
    # ``start_date_local``).
    activity_cutoff = datetime(1970, 1, 1, tzinfo=timezone.utc)
    activity_before: datetime | None = None
    if cutoff_ts is not None:
        activity_before = cutoff_ts.replace(tzinfo=timezone.utc)
    activity_rows = await list_activity_feed(
        db,
        cutoff=activity_cutoff,
        before=activity_before,
        limit=fetch_n,
        include_superseded=include_superseded,
    )

    # ── Sleep ───────────────────────────────────────────────────────
    sleep_q = select(SleepSession).order_by(SleepSession.date.desc())
    if cutoff_ts is not None:
        # ``date`` is a calendar date; an inclusive ``<=`` on the cursor
        # day keeps same-day rows for the strict Python tiebreak while
        # excluding everything strictly newer.
        sleep_q = sleep_q.where(SleepSession.date <= cutoff_ts.date())
    sleep_q = sleep_q.limit(fetch_n)
    sleep_rows = [_sleep_dict(s) for s in (await db.execute(sleep_q)).scalars().all()]

    # ── Strength ────────────────────────────────────────────────────
    strength_before = cutoff_ts.date() if cutoff_ts is not None else None
    strength_rows = await list_sessions(db, limit=fetch_n, before_date=strength_before)

    # ── Build candidates with composite keys ────────────────────────
    candidates: list[tuple[TimelineKey, str, dict[str, Any]]] = []
    for row in activity_rows:
        candidates.append((_activity_key(row), "activities", row))
    for row in sleep_rows:
        candidates.append((_sleep_key(row), "sleep", row))
    for row in strength_rows:
        candidates.append((_strength_key(row), "strength", row))

    # Strict composite less-than the cursor (newest-first). Drops the
    # cursor row itself and anything ordered after it.
    if cursor_key is not None:
        candidates = [c for c in candidates if c[0] < cursor_key]

    # Sort-merge newest-first on the composite key.
    candidates.sort(key=lambda c: c[0], reverse=True)

    has_more = len(candidates) > limit
    page = candidates[:limit]

    next_cursor: str | None = None
    if has_more and page:
        next_cursor = encode_cursor(page[-1][0])

    activities_out = [row for key, bucket, row in page if bucket == "activities"]
    sleep_out = [row for key, bucket, row in page if bucket == "sleep"]
    strength_out = [row for key, bucket, row in page if bucket == "strength"]

    return {
        "activities": activities_out,
        "sleep": sleep_out,
        "strength": strength_out,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }
