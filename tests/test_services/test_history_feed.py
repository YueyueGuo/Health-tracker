"""Pagination-correctness tests for the unified history feed.

``list_history_feed`` (``backend/services/history_feed.py``) merges three
independently ordered sources — activities, sleep, strength — behind ONE
opaque cursor. The properties that must hold:

* **page-boundary integrity**: paging the full feed in chunks of N yields
  exactly the same set AND order as one big fetch (no dropped, no
  duplicated rows),
* **tie handling**: rows from different sources with an identical
  timestamp resolve deterministically by ``source_rank`` then ``id`` and
  survive a page boundary placed exactly between them,
* **end of feed**: the final page sets ``has_more=False`` and
  ``next_cursor=None``,
* **cursor round-trip**: encode/decode is stable and a bad/empty cursor
  falls back to the first page (never raises),
* **tz correctness**: naive sleep/strength stamps order correctly
  relative to tz-aware activity timestamps.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.database import Base
from backend.models import Activity, SleepSession, StrengthSet
from backend.services.history_feed import (
    decode_cursor,
    encode_cursor,
    list_history_feed,
)


# ── Seed helpers ────────────────────────────────────────────────────


async def _seed_activity(
    db,
    *,
    strava_id: int,
    start: datetime,
    name: str | None = None,
) -> Activity:
    a = Activity(
        strava_id=strava_id,
        name=name or f"act-{strava_id}",
        sport_type="Run",
        start_date=start,
        start_date_local=start,
        enrichment_status="complete",
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return a


async def _seed_sleep(
    db,
    *,
    day: date,
    wake: datetime | None = None,
    source: str = "eight_sleep",
) -> SleepSession:
    s = SleepSession(
        source=source,
        external_id=f"sleep-{source}-{day.isoformat()}",
        date=day,
        wake_time=wake if wake is not None else datetime.combine(day, datetime.min.time()).replace(hour=7),
        total_duration=420,
        sleep_score=80.0,
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def _seed_strength(db, *, day: date) -> None:
    db.add(
        StrengthSet(
            date=day,
            exercise_name="Bench Press",
            set_number=1,
            reps=5,
            weight_kg=100.0,
        )
    )
    await db.commit()


# ── A small event-identity helper ───────────────────────────────────


def _event_ids(payload: dict) -> list[str]:
    """Flatten a page payload into source-namespaced ids in feed order.

    The service returns three typed arrays, not a merged event list, but
    each array already carries only the rows for this page's window. To
    assert ordering across sources we reconstruct the composite-key order
    the same way the service merged them (newest-first by timestamp, then
    source_rank, then id) and emit a stable namespaced id per row.
    """
    from backend.services.history_feed import (
        _activity_key,
        _sleep_key,
        _strength_key,
    )

    rows: list[tuple] = []
    for r in payload["activities"]:
        rows.append((_activity_key(r), f"activity-{r['id']}"))
    for r in payload["sleep"]:
        rows.append((_sleep_key(r), f"sleep-{r['id']}"))
    for r in payload["strength"]:
        rows.append((_strength_key(r), f"strength-{r['date']}"))
    rows.sort(key=lambda x: x[0], reverse=True)
    return [eid for _, eid in rows]


async def _page_all(db, *, chunk: int, include_superseded: bool = False) -> list[str]:
    """Walk the entire feed in chunks of ``chunk`` and return ordered ids."""
    ids: list[str] = []
    cursor: str | None = None
    guard = 0
    while True:
        guard += 1
        assert guard < 1000, "pagination did not terminate"
        page = await list_history_feed(
            db, cursor=cursor, limit=chunk, include_superseded=include_superseded
        )
        ids.extend(_event_ids(page))
        if not page["has_more"]:
            assert page["next_cursor"] is None
            break
        assert page["next_cursor"] is not None
        cursor = page["next_cursor"]
    return ids


# ── Tests ───────────────────────────────────────────────────────────


async def _seed_mixed_feed(db) -> None:
    """A mixed feed of activities + sleep + strength across overlapping days."""
    base = datetime(2026, 5, 1, 8, 0, 0, tzinfo=timezone.utc)
    # 6 activities, every ~2 days.
    for i in range(6):
        await _seed_activity(db, strava_id=100 + i, start=base + timedelta(days=2 * i, hours=i))
    # 5 sleep nights, overlapping the activity days.
    for i in range(5):
        d = date(2026, 5, 1) + timedelta(days=2 * i + 1)
        await _seed_sleep(
            db,
            day=d,
            wake=datetime.combine(d, datetime.min.time()).replace(hour=7, minute=15),
        )
    # 4 strength sessions.
    for i in range(4):
        await _seed_strength(db, day=date(2026, 5, 2) + timedelta(days=3 * i))


class TestPageBoundaryIntegrity:
    async def test_chunked_paging_matches_one_big_fetch(self, db):
        await _seed_mixed_feed(db)

        big = await list_history_feed(db, cursor=None, limit=100, include_superseded=False)
        one_shot_ids = _event_ids(big)
        assert big["has_more"] is False

        # Same total count regardless of chunk size, and identical order.
        for chunk in (1, 2, 3, 5, 7):
            paged_ids = await _page_all(db, chunk=chunk)
            assert paged_ids == one_shot_ids, f"chunk={chunk} drifted from one-shot order"
            # No dropped rows.
            assert len(paged_ids) == len(one_shot_ids)
            # No duplicated rows.
            assert len(set(paged_ids)) == len(paged_ids)

    async def test_total_row_count_is_all_seeded_rows(self, db):
        await _seed_mixed_feed(db)
        ids = await _page_all(db, chunk=3)
        # 6 activities + 5 sleep + 4 strength = 15 rows.
        assert len(ids) == 15

    async def test_single_dominant_source_deep_scroll_drops_nothing(self, db):
        """Regression: a single source with far more rows than the page
        size (and the over-fetch slack) must still page all the way back.

        The earlier implementation bounded each source's over-fetch at the
        head of the window, so the strict-cursor filter starved the
        candidate set on deep pages and ``has_more`` flipped false early,
        silently dropping older rows. This walks 25 same-source rows at
        ``limit=1`` (a page boundary between every row) and asserts the
        full set survives.
        """
        base = datetime(2026, 5, 1, 8, 0, 0, tzinfo=timezone.utc)
        for i in range(25):
            await _seed_activity(db, strava_id=500 + i, start=base + timedelta(days=i))

        big = await list_history_feed(db, cursor=None, limit=100, include_superseded=False)
        one_shot = _event_ids(big)
        assert len(one_shot) == 25

        for chunk in (1, 2, 4):
            paged = await _page_all(db, chunk=chunk)
            assert paged == one_shot, f"chunk={chunk} dropped or reordered rows"

    async def test_mixed_feed_larger_than_slack_pages_completely(self, db):
        """A mixed feed materially larger than the over-fetch slack still
        pages with no dropped/duplicated rows at every chunk size."""
        base = datetime(2026, 1, 1, 6, 0, 0, tzinfo=timezone.utc)
        for i in range(20):
            await _seed_activity(db, strava_id=600 + i, start=base + timedelta(days=i, hours=i % 5))
        for i in range(20):
            d = date(2026, 1, 1) + timedelta(days=i)
            await _seed_sleep(
                db,
                day=d,
                wake=datetime.combine(d, datetime.min.time()).replace(hour=7),
            )
        for i in range(15):
            await _seed_strength(db, day=date(2026, 1, 2) + timedelta(days=2 * i))

        big = await list_history_feed(db, cursor=None, limit=200, include_superseded=False)
        one_shot = _event_ids(big)
        assert len(one_shot) == 55  # 20 + 20 + 15

        for chunk in (1, 3, 6, 11):
            paged = await _page_all(db, chunk=chunk)
            assert paged == one_shot, f"chunk={chunk} drifted from one-shot order"
            assert len(set(paged)) == len(paged)


class TestTieHandling:
    async def test_same_timestamp_resolves_by_source_rank_then_id(self, db):
        # An activity and a sleep night whose timeline instants collide.
        # Activity sort instant = start_date (naive UTC). Sleep instant =
        # wake_time. Give them the SAME naive-UTC wall instant so only
        # source_rank breaks the tie. A higher composite key sorts first
        # newest-first; sleep (rank 1) > activity (rank 0), so sleep wins.
        instant_naive = datetime(2026, 5, 10, 7, 0, 0)
        act = await _seed_activity(
            db,
            strava_id=200,
            start=instant_naive.replace(tzinfo=timezone.utc),
        )
        sleep = await _seed_sleep(
            db,
            day=date(2026, 5, 10),
            wake=instant_naive,  # naive local, same wall instant
        )

        page = await list_history_feed(db, cursor=None, limit=10, include_superseded=False)
        ids = _event_ids(page)
        # Equal timestamp -> higher source_rank (sleep=1) sorts first newest-first.
        assert ids.index(f"sleep-{sleep.id}") < ids.index(f"activity-{act.id}")

    async def test_tie_survives_page_boundary_between_the_two_rows(self, db):
        instant_naive = datetime(2026, 5, 10, 7, 0, 0)
        act = await _seed_activity(
            db, strava_id=200, start=instant_naive.replace(tzinfo=timezone.utc)
        )
        sleep = await _seed_sleep(db, day=date(2026, 5, 10), wake=instant_naive)

        # limit=1 places the page boundary exactly between the two tied rows.
        page1 = await list_history_feed(db, cursor=None, limit=1, include_superseded=False)
        assert _event_ids(page1) == [f"sleep-{sleep.id}"]
        assert page1["has_more"] is True

        page2 = await list_history_feed(
            db, cursor=page1["next_cursor"], limit=1, include_superseded=False
        )
        assert _event_ids(page2) == [f"activity-{act.id}"]
        assert page2["has_more"] is False
        assert page2["next_cursor"] is None


class TestEndOfFeed:
    async def test_final_page_flags_end(self, db):
        await _seed_mixed_feed(db)
        # Walk to the last page and assert the end markers.
        cursor: str | None = None
        last = None
        for _ in range(100):
            last = await list_history_feed(
                db, cursor=cursor, limit=4, include_superseded=False
            )
            if not last["has_more"]:
                break
            cursor = last["next_cursor"]
        assert last is not None
        assert last["has_more"] is False
        assert last["next_cursor"] is None

    async def test_empty_db_is_immediately_end(self, db):
        page = await list_history_feed(db, cursor=None, limit=50, include_superseded=False)
        assert page["activities"] == []
        assert page["sleep"] == []
        assert page["strength"] == []
        assert page["has_more"] is False
        assert page["next_cursor"] is None


class TestCursorRoundTrip:
    def test_encode_decode_is_stable(self):
        key = (datetime(2026, 5, 10, 7, 30, 0), 1, "5")
        token = encode_cursor(key)
        assert decode_cursor(token) == key

    def test_encode_decode_strength_string_id(self):
        key = (datetime(2026, 5, 10, 12, 0, 0), 2, "2026-05-10")
        assert decode_cursor(encode_cursor(key)) == key

    def test_empty_cursor_is_first_page(self):
        assert decode_cursor(None) is None
        assert decode_cursor("") is None

    def test_garbage_cursor_is_first_page_no_raise(self):
        assert decode_cursor("not-base64!!!") is None
        # Valid base64 but not the expected pipe-delimited triple.
        import base64 as _b64

        bad = _b64.urlsafe_b64encode(b"only-one-field").decode("ascii")
        assert decode_cursor(bad) is None

    async def test_garbage_cursor_returns_first_page_from_service(self, db):
        await _seed_mixed_feed(db)
        first = await list_history_feed(db, cursor=None, limit=100, include_superseded=False)
        garbled = await list_history_feed(
            db, cursor="@@@not-a-cursor@@@", limit=100, include_superseded=False
        )
        assert _event_ids(garbled) == _event_ids(first)


class TestTzCorrectness:
    async def test_naive_stamps_order_against_tz_aware_activity(self, db):
        # Activity at 18:00 UTC (tz-aware). Sleep wake at 07:00 naive local
        # earlier the same day. Strength at 12:00 naive local same day.
        # Newest-first order must be: activity (18:00) > strength (12:00) >
        # sleep (07:00), all on 2026-05-10.
        act = await _seed_activity(
            db,
            strava_id=300,
            start=datetime(2026, 5, 10, 18, 0, 0, tzinfo=timezone.utc),
        )
        await _seed_strength(db, day=date(2026, 5, 10))
        sleep = await _seed_sleep(
            db,
            day=date(2026, 5, 10),
            wake=datetime(2026, 5, 10, 7, 0, 0),
        )

        page = await list_history_feed(db, cursor=None, limit=10, include_superseded=False)
        ids = _event_ids(page)
        assert ids == [
            f"activity-{act.id}",
            "strength-2026-05-10",
            f"sleep-{sleep.id}",
        ]

    async def test_tz_aware_activity_converted_to_utc_for_compare(self, db):
        # An activity stored tz-aware: its naive-UTC instant must be the UTC
        # wall time, so a sleep wake at 09:00 naive (= 09:00 UTC compare)
        # sorts AFTER an activity at 08:00 UTC.
        act = await _seed_activity(
            db,
            strava_id=400,
            start=datetime(2026, 5, 11, 8, 0, 0, tzinfo=timezone.utc),
        )
        sleep = await _seed_sleep(
            db,
            day=date(2026, 5, 11),
            wake=datetime(2026, 5, 11, 9, 0, 0),
        )
        page = await list_history_feed(db, cursor=None, limit=10, include_superseded=False)
        ids = _event_ids(page)
        assert ids.index(f"sleep-{sleep.id}") < ids.index(f"activity-{act.id}")


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()
