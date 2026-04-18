"""Tests for backend.services.sync.SyncEngine's Strava pipeline.

Covers the two-phase sync orchestration, Phase A listing + upsert
rules, Phase B enrichment (quota stop, 429 break, per-activity failure
continues, detail + zones + laps applied, classifier called), the
``_apply_detail_to_activity`` field mapper (including the elev_low
seeding of base_elevation_m), and ``_lap_from_raw``.

The Strava HTTP client is stubbed — no network.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.clients.strava import StravaRateLimitError
from backend.database import Base
from backend.models import Activity, ActivityLap, SyncLog
from backend.services import sync as sync_mod
from backend.services.sync import SyncEngine, _lap_from_raw


# ── Fixtures ───────────────────────────────────────────────────────


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest.fixture(autouse=True)
def _configure_strava(monkeypatch):
    """Every test uses the Strava pipeline — pre-set a fake access token
    so `sync_strava` passes its "not configured" guard."""
    from backend.config import settings
    monkeypatch.setattr(settings.strava, "access_token", "fake", raising=False)
    monkeypatch.setattr(settings.strava, "refresh_token", "fake-refresh", raising=False)
    yield


class StubStravaClient:
    """In-memory Strava client.

    Pass canned list/detail/zones payloads; optionally seed `raises` to
    inject exceptions keyed on strava_id. `quota_after_n` simulates the
    quota flipping to exhausted after N enrichment calls.
    """

    def __init__(
        self,
        *,
        list_payload: list[dict] | None = None,
        details: dict[int, dict] | None = None,
        zones: dict[int, list[dict]] | None = None,
        raises: dict[int, Exception] | None = None,
        quota_after_n: int | None = None,
    ):
        self._list = list_payload or []
        self._details = details or {}
        self._zones = zones or {}
        self._raises = raises or {}
        self._quota_after_n = quota_after_n
        self.calls: dict[str, list[Any]] = {
            "get_all_activities": [],
            "detail": [],
            "zones": [],
        }
        self._quota_fraction_ignored: float | None = None

    async def get_all_activities(self, after=None):
        self.calls["get_all_activities"].append(after)
        return list(self._list)

    async def get_activity_detail(self, activity_id: int) -> dict:
        self.calls["detail"].append(activity_id)
        if activity_id in self._raises:
            raise self._raises[activity_id]
        return self._details.get(activity_id, {})

    async def get_activity_zones(self, activity_id: int) -> list[dict]:
        self.calls["zones"].append(activity_id)
        return self._zones.get(activity_id, [])

    def quota_exhausted(self, fraction: float = 0.95) -> bool:
        self._quota_fraction_ignored = fraction
        if self._quota_after_n is None:
            return False
        return len(self.calls["detail"]) >= self._quota_after_n

    def quota_usage(self) -> dict:
        return {"short_used": 0, "long_used": 0}

    async def close(self) -> None:
        pass


def _engine(db, strava) -> SyncEngine:
    # Eight Sleep / Whoop / Weather not exercised here.
    return SyncEngine(db, strava, None, None, None)  # type: ignore[arg-type]


def _list_activity(
    *,
    strava_id: int,
    name: str = "Run",
    start: str = "2026-04-15T08:00:00Z",
    sport_type: str = "Run",
    **extra: Any,
) -> dict:
    out = {
        "id": strava_id,
        "name": name,
        "sport_type": sport_type,
        "type": sport_type,
        "start_date": start,
        "start_date_local": start,
        "timezone": "(GMT+00:00) UTC",
        "elapsed_time": 1800,
        "moving_time": 1750,
        "distance": 5000.0,
        "total_elevation_gain": 30.0,
        "average_heartrate": 145.0,
        "max_heartrate": 170.0,
        "average_speed": 2.85,
        "max_speed": 4.5,
        "start_latlng": [40.71, -74.01],
        "map": {"summary_polyline": "abc"},
    }
    out.update(extra)
    return out


def _detail(
    *,
    strava_id: int,
    laps: list[dict] | None = None,
    **extra: Any,
) -> dict:
    out = {
        "id": strava_id,
        "name": "Run (detail)",
        "elapsed_time": 1800,
        "moving_time": 1750,
        "distance": 5000.0,
        "total_elevation_gain": 30.0,
        "average_heartrate": 145.0,
        "max_heartrate": 170.0,
        "average_speed": 2.85,
        "max_speed": 4.5,
        "average_watts": None,
        "max_watts": None,
        "weighted_average_watts": None,
        "average_cadence": 85.0,
        "calories": 400.0,
        "kilojoules": 0.0,
        "suffer_score": 30,
        "device_watts": False,
        "workout_type": 0,
        "available_zones": ["heartrate"],
        "elev_high": 55.0,
        "elev_low": 40.0,
        "laps": laps if laps is not None else [_lap_raw(0)],
    }
    out.update(extra)
    return out


def _lap_raw(idx: int, **extra: Any) -> dict:
    out = {
        "lap_index": idx,
        "name": f"Lap {idx + 1}",
        "elapsed_time": 300,
        "moving_time": 300,
        "distance": 900.0,
        "start_date": "2026-04-15T08:00:00Z",
        "average_speed": 3.0,
        "max_speed": 3.6,
        "average_heartrate": 150.0,
        "max_heartrate": 160.0,
        "average_cadence": 85.0,
        "average_watts": None,
        "total_elevation_gain": 5.0,
        "pace_zone": 2,
        "split": idx + 1,
        "start_index": idx * 100,
        "end_index": (idx + 1) * 100 - 1,
    }
    out.update(extra)
    return out


# ── sync_strava orchestration ──────────────────────────────────────


async def test_sync_strava_returns_zero_when_not_configured(db, monkeypatch):
    from backend.config import settings
    monkeypatch.setattr(settings.strava, "access_token", "", raising=False)
    monkeypatch.setattr(settings.strava, "refresh_token", "", raising=False)

    strava = StubStravaClient()
    result = await _engine(db, strava).sync_strava()
    assert result == 0
    assert strava.calls["get_all_activities"] == []


async def test_sync_strava_happy_path_marks_synclog_success(db):
    strava = StubStravaClient(
        list_payload=[_list_activity(strava_id=101)],
        details={101: _detail(strava_id=101)},
        zones={101: [{"type": "heartrate", "distribution_buckets": []}]},
    )
    result = await _engine(db, strava).sync_strava()
    assert result == 1  # one NEW activity listed in Phase A

    # SyncLog row captured success + enrichment count.
    log = (await db.execute(select(SyncLog))).scalar_one()
    assert log.source == "strava"
    assert log.status == "success"
    assert log.records_synced == 1
    assert "enriched=1" in (log.error_message or "")
    assert log.completed_at is not None

    # Activity is fully enriched.
    act = (await db.execute(select(Activity))).scalar_one()
    assert act.enrichment_status == "complete"
    assert act.enriched_at is not None


async def test_sync_strava_exception_marks_synclog_error(db, monkeypatch):
    strava = StubStravaClient()

    async def _boom(**kwargs):
        raise RuntimeError("phase A exploded")

    monkeypatch.setattr(SyncEngine, "_strava_phase_a", lambda self, **kw: _boom(**kw))

    with pytest.raises(RuntimeError, match="phase A exploded"):
        await _engine(db, strava).sync_strava()

    log = (await db.execute(select(SyncLog))).scalar_one()
    assert log.status == "error"
    assert "phase A exploded" in (log.error_message or "")


# ── Phase A: listing + upsert ──────────────────────────────────────


async def test_phase_a_full_history_passes_after_none(db):
    strava = StubStravaClient(list_payload=[])
    await _engine(db, strava)._strava_phase_a(full_history=True)
    assert strava.calls["get_all_activities"] == [None]


async def test_phase_a_incremental_uses_lookback_window(db):
    """Existing activity in DB → incremental `after` is its start_date
    minus the 7-day lookback window."""
    anchor = datetime(2026, 4, 10, 8, 0, 0)
    db.add(
        Activity(
            strava_id=1,
            name="Existing",
            sport_type="Run",
            start_date=anchor,
            enrichment_status="complete",
        )
    )
    await db.commit()

    strava = StubStravaClient(list_payload=[])
    await _engine(db, strava)._strava_phase_a(full_history=False)

    assert len(strava.calls["get_all_activities"]) == 1
    after = strava.calls["get_all_activities"][0]
    assert after == anchor - timedelta(days=sync_mod._LIST_LOOKBACK_DAYS)


async def test_phase_a_inserts_new_activity_as_pending(db):
    strava = StubStravaClient(list_payload=[_list_activity(strava_id=42)])
    count = await _engine(db, strava)._strava_phase_a(full_history=True)
    assert count == 1

    act = (await db.execute(select(Activity))).scalar_one()
    assert act.strava_id == 42
    assert act.enrichment_status == "pending"
    assert act.start_lat == 40.71
    assert act.start_lng == -74.01
    assert act.summary_polyline == "abc"
    # raw_data preserved for later Phase 1 elevation reprocessing.
    assert act.raw_data is not None and act.raw_data["id"] == 42


async def test_phase_a_refreshes_mutable_fields_inside_lookback(db, monkeypatch):
    """Existing activity, started within the lookback window → mutable
    fields (e.g. `name`) are refreshed; non-mutable fields are NOT
    overwritten."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    recent = now - timedelta(days=2)
    db.add(
        Activity(
            strava_id=77,
            name="Old name",
            sport_type="Run",
            start_date=recent,
            distance=999.0,
            enrichment_status="complete",
        )
    )
    await db.commit()

    payload = _list_activity(
        strava_id=77,
        name="New name",
        distance=55555.0,  # ignored: distance isn't in _MUTABLE_SUMMARY_FIELDS
        start=recent.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
    )
    strava = StubStravaClient(list_payload=[payload])
    count = await _engine(db, strava)._strava_phase_a(full_history=False)
    assert count == 0  # not newly inserted

    await db.refresh((await db.execute(select(Activity))).scalar_one())
    act = (await db.execute(select(Activity))).scalar_one()
    assert act.name == "New name"
    assert act.distance == 999.0  # untouched


async def test_phase_a_skips_mutable_refresh_outside_lookback(db):
    """Activity older than the lookback window keeps its original
    name even if the list response says otherwise."""
    old = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=60)
    db.add(
        Activity(
            strava_id=8,
            name="Ancient",
            sport_type="Run",
            start_date=old,
            enrichment_status="complete",
        )
    )
    await db.commit()

    payload = _list_activity(
        strava_id=8,
        name="Rename attempt",
        start=old.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
    )
    strava = StubStravaClient(list_payload=[payload])
    await _engine(db, strava)._strava_phase_a(full_history=False)

    act = (await db.execute(select(Activity))).scalar_one()
    assert act.name == "Ancient"


async def test_phase_a_handles_missing_start_latlng(db):
    payload = _list_activity(strava_id=9, start_latlng=None)
    strava = StubStravaClient(list_payload=[payload])
    await _engine(db, strava)._strava_phase_a(full_history=True)

    act = (await db.execute(select(Activity))).scalar_one()
    assert act.start_lat is None
    assert act.start_lng is None


# ── Phase B: enrichment loop ───────────────────────────────────────


async def _seed_pending(db, *strava_ids: int) -> dict[int, int]:
    """Insert pending activities; returns {strava_id: row_id}."""
    ids = {}
    for sid in strava_ids:
        act = Activity(
            strava_id=sid,
            name=f"Pending {sid}",
            sport_type="Run",
            start_date=datetime(2026, 4, 15, 8, 0, 0) + timedelta(minutes=sid),
            enrichment_status="pending",
        )
        db.add(act)
    await db.commit()
    rows = (await db.execute(select(Activity))).scalars().all()
    for r in rows:
        ids[r.strava_id] = r.id
    return ids


async def test_phase_b_enriches_pending_activity_with_laps_and_zones(db):
    await _seed_pending(db, 1)
    laps = [_lap_raw(0), _lap_raw(1), _lap_raw(2), _lap_raw(3)]
    strava = StubStravaClient(
        details={1: _detail(strava_id=1, laps=laps)},
        zones={1: [{"type": "heartrate", "distribution_buckets": [{"min": 0, "max": 100, "time": 300}]}]},
    )
    count = await _engine(db, strava)._strava_phase_b(limit=None)
    assert count == 1

    act = (await db.execute(select(Activity))).scalar_one()
    assert act.enrichment_status == "complete"
    assert act.enriched_at is not None
    assert act.suffer_score == 30
    assert act.available_zones == ["heartrate"]
    assert act.zones_data is not None
    # Classifier ran — low-variance 4-lap run at pace_zone=2 classifies as easy.
    assert act.classification_type == "easy"

    # Laps persisted in order.
    lap_rows = (
        await db.execute(select(ActivityLap).order_by(ActivityLap.lap_index))
    ).scalars().all()
    assert [l.lap_index for l in lap_rows] == [0, 1, 2, 3]


async def test_phase_b_replaces_existing_lap_rows(db):
    """Re-enriching an activity wipes prior laps so a corrected detail
    response isn't merged into stale rows."""
    ids = await _seed_pending(db, 1)
    # Seed leftover laps from an earlier pass.
    db.add_all(
        [
            ActivityLap(activity_id=ids[1], lap_index=99, distance=1.0),
            ActivityLap(activity_id=ids[1], lap_index=100, distance=2.0),
        ]
    )
    await db.commit()

    strava = StubStravaClient(
        details={1: _detail(strava_id=1, laps=[_lap_raw(0)])},
    )
    await _engine(db, strava)._strava_phase_b(limit=None)

    lap_rows = (await db.execute(select(ActivityLap))).scalars().all()
    assert len(lap_rows) == 1
    assert lap_rows[0].lap_index == 0


async def test_phase_b_stops_early_when_quota_exhausted_upfront(db):
    await _seed_pending(db, 1, 2)

    class _ExhaustedStrava(StubStravaClient):
        def quota_exhausted(self, fraction=0.95):
            return True

    strava = _ExhaustedStrava(
        details={1: _detail(strava_id=1), 2: _detail(strava_id=2)},
    )
    count = await _engine(db, strava)._strava_phase_b(limit=None)
    assert count == 0
    assert strava.calls["detail"] == []


async def test_phase_b_stops_mid_loop_when_quota_flips(db):
    """Quota OK for the first activity, exhausted before the second."""
    await _seed_pending(db, 1, 2)
    strava = StubStravaClient(
        details={1: _detail(strava_id=1), 2: _detail(strava_id=2)},
        quota_after_n=1,  # flips exhausted after 1st detail call
    )
    count = await _engine(db, strava)._strava_phase_b(limit=None)
    assert count == 1
    assert len(strava.calls["detail"]) == 1


async def test_phase_b_rate_limit_error_breaks_loop_cleanly(db):
    """A 429 on the newest pending activity breaks the loop before any
    enrichments land, and the 429'd activity stays pending (not failed)."""
    await _seed_pending(db, 1, 2)
    # strava_id=2 is newest (later start_date in _seed_pending), so it's
    # fetched first. 429 there → loop breaks immediately.
    strava = StubStravaClient(
        details={1: _detail(strava_id=1), 2: _detail(strava_id=2)},
        raises={2: StravaRateLimitError(retry_after=42)},
    )
    count = await _engine(db, strava)._strava_phase_b(limit=None)
    assert count == 0
    assert strava.calls["detail"] == [2]

    act2 = (await db.execute(
        select(Activity).where(Activity.strava_id == 2)
    )).scalar_one()
    assert act2.enrichment_status == "pending"
    assert act2.enrichment_error is None


async def test_phase_b_generic_error_marks_failed_and_continues(db):
    await _seed_pending(db, 1, 2)
    strava = StubStravaClient(
        details={1: _detail(strava_id=1), 2: _detail(strava_id=2)},
        raises={1: RuntimeError("transient")},
    )
    count = await _engine(db, strava)._strava_phase_b(limit=None)
    assert count == 1

    # First activity marked failed with error captured; second succeeded.
    rows = {
        r.strava_id: r
        for r in (await db.execute(select(Activity))).scalars().all()
    }
    assert rows[1].enrichment_status == "failed"
    assert "transient" in (rows[1].enrichment_error or "")
    assert rows[2].enrichment_status == "complete"


async def test_phase_b_respects_limit(db):
    await _seed_pending(db, 1, 2, 3)
    strava = StubStravaClient(
        details={
            1: _detail(strava_id=1),
            2: _detail(strava_id=2),
            3: _detail(strava_id=3),
        },
    )
    count = await _engine(db, strava)._strava_phase_b(limit=2)
    assert count == 2
    assert len(strava.calls["detail"]) == 2


async def test_phase_b_orders_newest_first(db):
    """Pending activities are enriched newest-first so the UI reflects
    the latest workouts quickly."""
    await _seed_pending(db, 1, 2, 3)
    strava = StubStravaClient(
        details={
            1: _detail(strava_id=1),
            2: _detail(strava_id=2),
            3: _detail(strava_id=3),
        },
        quota_after_n=1,
    )
    await _engine(db, strava)._strava_phase_b(limit=None)
    # strava_id=3 has the latest start_date (see _seed_pending), so it
    # should be picked first.
    assert strava.calls["detail"] == [3]


async def test_phase_b_zones_fallback_to_none_when_empty(db):
    await _seed_pending(db, 1)
    strava = StubStravaClient(details={1: _detail(strava_id=1)}, zones={1: []})
    await _engine(db, strava)._strava_phase_b(limit=None)
    act = (await db.execute(select(Activity))).scalar_one()
    assert act.zones_data is None


async def test_phase_b_classifier_failure_does_not_abort_enrichment(
    db, monkeypatch
):
    await _seed_pending(db, 1)

    def _boom(activity, laps):
        raise RuntimeError("classifier crashed")

    monkeypatch.setattr(sync_mod, "classify_and_persist", _boom)

    strava = StubStravaClient(details={1: _detail(strava_id=1)})
    count = await _engine(db, strava)._strava_phase_b(limit=None)
    assert count == 1

    act = (await db.execute(select(Activity))).scalar_one()
    # Enrichment succeeded; classification stays empty.
    assert act.enrichment_status == "complete"
    assert act.classification_type is None


# ── _apply_detail_to_activity ──────────────────────────────────────


def test_apply_detail_maps_all_fields():
    act = Activity(
        strava_id=1,
        name="Old",
        sport_type="Run",
        start_date=datetime(2026, 4, 15),
    )
    SyncEngine._apply_detail_to_activity(
        act, _detail(strava_id=1, name="New", suffer_score=99)
    )
    assert act.name == "New"
    assert act.suffer_score == 99
    assert act.available_zones == ["heartrate"]


def test_apply_detail_seeds_base_elevation_from_elev_low():
    """Strava elev_low_m is the canonical base-altitude seed per the
    elevation pipeline docs. Applying a detail response must set
    ``base_elevation_m`` AND flip ``elevation_enriched``."""
    act = Activity(
        strava_id=1,
        name="X",
        sport_type="Run",
        start_date=datetime(2026, 4, 15),
    )
    SyncEngine._apply_detail_to_activity(
        act, _detail(strava_id=1, elev_high=2100.5, elev_low=1995.0)
    )
    assert act.elev_high_m == 2100.5
    assert act.elev_low_m == 1995.0
    assert act.base_elevation_m == 1995.0
    assert act.elevation_enriched is True


def test_apply_detail_indoor_activity_leaves_elevation_untouched():
    """No elev_high/elev_low in the payload → elevation fields stay
    None and the enriched flag isn't set (so the Open-Meteo /
    default-location path can still handle it later)."""
    act = Activity(
        strava_id=1,
        name="X",
        sport_type="WeightTraining",
        start_date=datetime(2026, 4, 15),
    )
    SyncEngine._apply_detail_to_activity(
        act,
        _detail(strava_id=1, elev_high=None, elev_low=None),
    )
    assert act.elev_low_m is None
    assert act.base_elevation_m is None
    # elevation_enriched is the server-default False on inserted rows;
    # on a detached Activity() it's None, so just assert the mapper
    # didn't flip it to True.
    assert act.elevation_enriched is not True


def test_apply_detail_ignores_malformed_elev_low():
    act = Activity(
        strava_id=1,
        name="X",
        sport_type="Run",
        start_date=datetime(2026, 4, 15),
    )
    detail = _detail(strava_id=1)
    detail["elev_low"] = "not a number"
    SyncEngine._apply_detail_to_activity(act, detail)
    assert act.elev_low_m is None
    assert act.base_elevation_m is None
    assert act.elevation_enriched is not True


# ── _lap_from_raw ──────────────────────────────────────────────────


def test_lap_from_raw_maps_fields():
    lap = _lap_from_raw(activity_id=5, raw=_lap_raw(2, pace_zone=3))
    assert lap.activity_id == 5
    assert lap.lap_index == 2
    assert lap.pace_zone == 3
    assert lap.average_speed == 3.0
    assert lap.start_index == 200
    # start_date parsed from the ISO string.
    assert lap.start_date == datetime(2026, 4, 15, 8, 0, 0, tzinfo=timezone.utc)


def test_lap_from_raw_handles_missing_start_date():
    raw = _lap_raw(0)
    raw.pop("start_date")
    lap = _lap_from_raw(activity_id=1, raw=raw)
    assert lap.start_date is None


def test_lap_from_raw_handles_malformed_start_date():
    raw = _lap_raw(0, start_date="nonsense")
    lap = _lap_from_raw(activity_id=1, raw=raw)
    assert lap.start_date is None
