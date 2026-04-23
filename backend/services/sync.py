from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.clients.eight_sleep import EightSleepClient
from backend.clients.strava import StravaClient, StravaRateLimitError
from backend.clients.weather import WeatherClient, WeatherRateLimitError
from backend.clients.whoop import WhoopClient
from backend.models import (
    Activity,
    ActivityLap,
    Recovery,
    SleepSession,
    SyncLog,
    WeatherSnapshot,
)
from backend.services.classifier import classify_and_persist
logger = logging.getLogger(__name__)

# When running Phase A incrementally, re-scan this many days back from the
# most recently seen activity to catch late watch uploads.
_LIST_LOOKBACK_DAYS = 7

# Summary fields that can change after upload (renames, description edits,
# privacy changes). For activities within the lookback window, refresh these
# on each list pass.
_MUTABLE_SUMMARY_FIELDS = ("name",)


class SyncEngine:
    """Orchestrates data syncing from all sources into the database."""

    def __init__(
        self,
        db: AsyncSession,
        strava: StravaClient,
        eight_sleep: EightSleepClient,
        whoop: WhoopClient,
        weather: WeatherClient,
    ):
        self.db = db
        self.strava = strava
        self.eight_sleep = eight_sleep
        self.whoop = whoop
        self.weather = weather

    async def sync_all(self) -> dict[str, int | dict | str]:
        results: dict[str, int | dict | str] = {}
        for source in ["strava", "eight_sleep", "whoop", "weather", "elevation"]:
            try:
                count = await getattr(self, f"sync_{source}")()
                results[source] = count
            except Exception as e:
                results[source] = f"error: {e}"
        return results

    # ── Strava ──────────────────────────────────────────────────────

    async def sync_strava(
        self,
        *,
        full_history: bool = False,
        enrich_limit: int | None = None,
    ) -> int:
        """Two-phase Strava sync.

        Phase A (always): list activities from Strava, upsert summary rows
        with `enrichment_status='pending'`.

        Phase B (always, but bounded): for activities still pending, fetch
        full detail (incl. embedded laps) + zones, populate all summary
        fields, insert lap rows, mark `complete`. Stops cleanly on rate
        limit exhaustion or after `enrich_limit` activities.

        Args:
            full_history: if True, list from the beginning of time (used by
                backfill script). Otherwise incremental from
                max(start_date) - lookback window.
            enrich_limit: cap on number of activities enriched this pass.
                None = as many as rate limits allow.

        Returns the number of NEWLY-listed activities in Phase A (not the
        enrichment count).
        """
        from backend.config import settings
        if not settings.strava.access_token and not settings.strava.refresh_token:
            return 0

        log = SyncLog(
            source="strava",
            sync_type="full" if full_history else "incremental",
            status="running",
        )
        self.db.add(log)
        await self.db.flush()

        try:
            new_count = await self._strava_phase_a(full_history=full_history)
            enriched_count = await self._strava_phase_b(limit=enrich_limit)

            log.status = "success"
            log.records_synced = new_count
            log.error_message = f"enriched={enriched_count}"
            log.completed_at = datetime.now(timezone.utc)
            await self.db.commit()
            return new_count

        except Exception as e:
            log.status = "error"
            log.error_message = str(e)
            log.completed_at = datetime.now(timezone.utc)
            await self.db.commit()
            raise

    async def _strava_phase_a(self, *, full_history: bool) -> int:
        """List activities from Strava, upsert summary rows.

        Returns the count of newly inserted activities.
        """
        if full_history:
            after = None
        else:
            last_date = (await self.db.execute(
                select(func.max(Activity.start_date))
            )).scalar_one_or_none()
            after = (
                last_date - timedelta(days=_LIST_LOOKBACK_DAYS)
                if last_date else None
            )

        activities = await self.strava.get_all_activities(after=after)
        new_count = 0

        for raw in activities:
            strava_id = raw["id"]
            existing = (await self.db.execute(
                select(Activity).where(Activity.strava_id == strava_id)
            )).scalar_one_or_none()

            if existing:
                # Refresh only mutable metadata on activities within the
                # lookback window (avoids rewriting ancient rows every pass).
                if (
                    datetime.now(timezone.utc).replace(tzinfo=None)
                    - existing.start_date.replace(tzinfo=None)
                    < timedelta(days=_LIST_LOOKBACK_DAYS)
                ):
                    for field in _MUTABLE_SUMMARY_FIELDS:
                        new_value = raw.get(field)
                        if new_value is not None and getattr(existing, field) != new_value:
                            setattr(existing, field, new_value)
                continue

            activity = Activity(
                strava_id=strava_id,
                name=raw.get("name", ""),
                sport_type=raw.get("sport_type", raw.get("type", "Unknown")),
                start_date=datetime.fromisoformat(
                    raw["start_date"].replace("Z", "+00:00")
                ),
                start_date_local=datetime.fromisoformat(
                    raw.get("start_date_local", raw["start_date"]).replace("Z", "+00:00")
                ),
                timezone=raw.get("timezone"),
                elapsed_time=raw.get("elapsed_time"),
                moving_time=raw.get("moving_time"),
                distance=raw.get("distance"),
                total_elevation=raw.get("total_elevation_gain"),
                average_hr=raw.get("average_heartrate"),
                max_hr=raw.get("max_heartrate"),
                average_speed=raw.get("average_speed"),
                max_speed=raw.get("max_speed"),
                average_power=raw.get("average_watts"),
                average_cadence=raw.get("average_cadence"),
                device_watts=raw.get("device_watts"),
                start_lat=(raw.get("start_latlng") or [None, None])[0],
                start_lng=(raw.get("start_latlng") or [None, None])[1],
                summary_polyline=(raw.get("map") or {}).get("summary_polyline"),
                raw_data=raw,
                enrichment_status="pending",
            )
            self.db.add(activity)
            new_count += 1

        await self.db.commit()
        return new_count

    async def drain_strava_enrichment(self, *, limit: int | None = None) -> int:
        """Public entry point for the enrichment scheduler.

        Runs Phase B only — does NOT re-list via Phase A. Returns the count
        of activities enriched in this call. Stops early on quota exhaustion
        or after ``limit`` activities.

        This is a stable wrapper around ``_strava_phase_b`` so background
        jobs don't depend on private method names.
        """
        return await self._strava_phase_b(limit=limit)

    async def _strava_phase_b(self, *, limit: int | None) -> int:
        """Enrich pending activities with detail + zones.

        Stops early when Strava quota nears exhaustion, when a 429 is
        returned, or after `limit` successful enrichments.
        """
        q = (
            select(Activity)
            .where(Activity.enrichment_status == "pending")
            .order_by(Activity.start_date.desc())
        )
        if limit is not None:
            q = q.limit(limit)
        pending = (await self.db.execute(q)).scalars().all()

        enriched = 0
        for activity in pending:
            if self.strava.quota_exhausted():
                logger.info(
                    f"Strava quota near limit, stopping enrichment: "
                    f"{self.strava.quota_usage()}"
                )
                break

            try:
                detail = await self.strava.get_activity_detail(activity.strava_id)
                zones = await self.strava.get_activity_zones(activity.strava_id)
            except StravaRateLimitError:
                logger.warning("Strava 429 during enrichment; stopping loop.")
                await self.db.commit()
                break
            except Exception as e:
                activity.enrichment_status = "failed"
                activity.enrichment_error = str(e)[:1000]
                await self.db.commit()
                continue

            self._apply_detail_to_activity(activity, detail)
            activity.zones_data = zones if zones else None

            # Replace lap rows (wholesale) from the embedded laps array.
            # Bulk delete avoids async lazy-load of the .laps relationship.
            await self.db.execute(
                delete(ActivityLap).where(ActivityLap.activity_id == activity.id)
            )
            for lap_raw in detail.get("laps") or []:
                self.db.add(_lap_from_raw(activity_id=activity.id, raw=lap_raw))

            activity.enrichment_status = "complete"
            activity.enrichment_error = None
            activity.enriched_at = datetime.now(timezone.utc)

            # Classify. Failures here shouldn't abort enrichment — the raw
            # data is more important than the derived label.
            try:
                fresh_laps = (await self.db.execute(
                    select(ActivityLap)
                    .where(ActivityLap.activity_id == activity.id)
                    .order_by(ActivityLap.lap_index)
                )).scalars().all()
                classify_and_persist(activity, list(fresh_laps))
            except Exception as e:
                logger.warning(
                    f"Classifier failed for activity {activity.strava_id}: {e}"
                )

            await self.db.commit()
            enriched += 1

        return enriched

    @staticmethod
    def _apply_detail_to_activity(activity: Activity, detail: dict) -> None:
        """Populate Activity fields from the detail response."""
        activity.name = detail.get("name", activity.name)
        activity.elapsed_time = detail.get("elapsed_time", activity.elapsed_time)
        activity.moving_time = detail.get("moving_time", activity.moving_time)
        activity.distance = detail.get("distance", activity.distance)
        activity.total_elevation = detail.get(
            "total_elevation_gain", activity.total_elevation
        )
        activity.average_hr = detail.get("average_heartrate", activity.average_hr)
        activity.max_hr = detail.get("max_heartrate", activity.max_hr)
        activity.average_speed = detail.get("average_speed", activity.average_speed)
        activity.max_speed = detail.get("max_speed", activity.max_speed)
        activity.average_power = detail.get("average_watts", activity.average_power)
        activity.max_power = detail.get("max_watts", activity.max_power)
        activity.weighted_avg_power = detail.get(
            "weighted_average_watts", activity.weighted_avg_power
        )
        activity.average_cadence = detail.get(
            "average_cadence", activity.average_cadence
        )
        activity.calories = detail.get("calories", activity.calories)
        activity.kilojoules = detail.get("kilojoules", activity.kilojoules)
        activity.suffer_score = detail.get("suffer_score", activity.suffer_score)
        activity.device_watts = detail.get("device_watts", activity.device_watts)
        activity.workout_type = detail.get("workout_type", activity.workout_type)
        activity.available_zones = detail.get("available_zones")
        # Base-elevation context (from Strava GPS, watch-recorded).
        # ``elev_high`` / ``elev_low`` are absent on indoor activities.
        if detail.get("elev_high") is not None:
            try:
                activity.elev_high_m = float(detail["elev_high"])
            except (TypeError, ValueError):
                pass
        if detail.get("elev_low") is not None:
            try:
                activity.elev_low_m = float(detail["elev_low"])
            except (TypeError, ValueError):
                pass
        # Only seed base_elevation_m from elev_low_m here — the full
        # derivation (user location, Open-Meteo fallback) lives in
        # ``backend.services.elevation_sync`` so the logic stays in one
        # place and this method stays focused on field mapping.
        if activity.elev_low_m is not None:
            activity.base_elevation_m = activity.elev_low_m
            activity.elevation_enriched = True

    # ── Eight Sleep ─────────────────────────────────────────────────

    async def sync_eight_sleep(self, days: int = 30, *, full_history: bool = False) -> int:
        """Thin delegation to the isolated Eight Sleep sync module.

        Kept as a method on SyncEngine so the scheduler / API routers /
        initial_sync script call into Eight Sleep the same way they call
        into Strava.
        """
        from backend.services.eight_sleep_sync import sync_eight_sleep as _es_sync
        return await _es_sync(
            self.db, self.eight_sleep, days=days, full_history=full_history
        )

    # ── Whoop ───────────────────────────────────────────────────────

    async def sync_whoop(self, days: int = 30) -> dict[str, int]:
        """Delegator to ``backend.services.whoop_sync``.

        Kept as a thin method so strand-branch work on the Whoop pipeline
        doesn't collide with Strava edits here. Logs a single SyncLog row
        capturing total records synced across recovery + sleep + workouts.
        """
        if not self.whoop.is_enabled:
            return {"recovery_new": 0, "sleep_new": 0, "workouts_new": 0}

        from backend.services.whoop_sync import sync_whoop as _whoop_sync

        log = SyncLog(source="whoop", sync_type="incremental", status="running")
        self.db.add(log)
        await self.db.flush()
        try:
            stats = await _whoop_sync(self.db, self.whoop, days=days)
            total_new = (
                stats.get("recovery_new", 0)
                + stats.get("sleep_new", 0)
                + stats.get("workouts_new", 0)
            )
            log.status = "success"
            log.records_synced = total_new
            log.completed_at = datetime.now(timezone.utc)
            await self.db.commit()
            return stats
        except Exception as e:
            log.status = "error"
            log.error_message = str(e)
            log.completed_at = datetime.now(timezone.utc)
            await self.db.commit()
            raise

    # ── Weather enrichment ──────────────────────────────────────────

    async def sync_weather(
        self,
        *,
        limit: int | None = None,
        dry_run: bool = False,
    ) -> dict[str, int]:
        """Enrich activities with historical weather data.

        Iterates activities with start_lat/start_lng and
        ``weather_enriched == False``, fetches the One Call 3.0 timemachine
        response, and inserts a ``WeatherSnapshot`` row. Stops cleanly on
        ``WeatherRateLimitError`` (429 / invalid-key 401).

        Args:
            limit: cap on number of activities processed this pass. ``None``
                means "all pending".
            dry_run: when ``True``, only counts candidates and makes no API
                calls / DB writes.

        Returns:
            ``{"enriched": n, "skipped": n, "failed": n, "remaining": n}``.
            ``remaining`` is the count of still-un-enriched activities after
            this pass (useful for driving a backfill loop).
        """
        pending_q = select(Activity).where(
            Activity.weather_enriched == False,  # noqa: E712
            Activity.start_lat.isnot(None),
            Activity.start_lng.isnot(None),
        ).order_by(Activity.start_date.desc())

        if limit is not None:
            pending_q = pending_q.limit(limit)

        result = await self.db.execute(pending_q)
        activities = result.scalars().all()

        enriched = 0
        skipped = 0
        failed = 0

        if dry_run:
            skipped = len(activities)
            remaining = await self._weather_remaining_count()
            return {
                "enriched": 0,
                "skipped": skipped,
                "failed": 0,
                "remaining": remaining,
            }

        if not self.weather.is_configured:
            # Still return a structured response so callers can treat this
            # consistently rather than hitting a silent 0.
            remaining = await self._weather_remaining_count()
            return {
                "enriched": 0,
                "skipped": len(activities),
                "failed": 0,
                "remaining": remaining,
            }

        for activity in activities:
            try:
                weather_data = await self.weather.get_historical_weather(
                    lat=activity.start_lat,
                    lng=activity.start_lng,
                    dt=activity.start_date,
                )
            except WeatherRateLimitError:
                logger.warning(
                    "Weather rate limit / auth failure; stopping sync loop."
                )
                # Commit what we have so progress isn't lost.
                await self.db.commit()
                break
            except Exception as e:
                logger.warning(
                    f"Weather fetch failed for activity {activity.id}: {e}"
                )
                failed += 1
                continue

            if not weather_data:
                skipped += 1
                continue

            snapshot = WeatherSnapshot(
                activity_id=activity.id,
                temp_c=weather_data["temp_c"],
                feels_like_c=weather_data["feels_like_c"],
                humidity=weather_data["humidity"],
                wind_speed=weather_data["wind_speed"],
                wind_gust=weather_data.get("wind_gust"),
                wind_deg=weather_data.get("wind_deg"),
                conditions=weather_data.get("conditions"),
                description=weather_data.get("description"),
                pressure=weather_data.get("pressure"),
                uv_index=weather_data.get("uv_index"),
                raw_data=weather_data.get("raw_data"),
            )
            self.db.add(snapshot)
            activity.weather_enriched = True
            enriched += 1

        await self.db.commit()
        remaining = await self._weather_remaining_count()
        return {
            "enriched": enriched,
            "skipped": skipped,
            "failed": failed,
            "remaining": remaining,
        }

    async def _weather_remaining_count(self) -> int:
        """Count activities still awaiting weather enrichment."""
        return (await self.db.execute(
            select(func.count()).select_from(Activity).where(
                Activity.weather_enriched == False,  # noqa: E712
                Activity.start_lat.isnot(None),
                Activity.start_lng.isnot(None),
            )
        )).scalar_one()

    # ── Elevation enrichment ────────────────────────────────────────

    async def sync_elevation(
        self,
        *,
        limit: int | None = None,
        dry_run: bool = False,
    ) -> dict[str, int]:
        """Delegator to ``backend.services.elevation_sync``.

        Kept as a thin method on ``SyncEngine`` so the scheduler /
        backfill script call into elevation enrichment the same way
        they call into weather. The real logic lives in the isolated
        module so parallel work on ``services/sync.py`` (e.g. Strava
        tweaks) doesn't collide.
        """
        from backend.clients.elevation import ElevationClient
        from backend.services.elevation_sync import sync_elevation as _elev_sync

        client = ElevationClient()
        try:
            return await _elev_sync(
                self.db, client, limit=limit, dry_run=dry_run
            )
        finally:
            await client.close()


def settings_eight_sleep_configured() -> bool:
    from backend.config import settings
    return bool(settings.eight_sleep.email and settings.eight_sleep.password)


def _parse_dt(val: str | None) -> datetime | None:
    if not val:
        return None
    try:
        return datetime.fromisoformat(val.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _lap_from_raw(*, activity_id: int, raw: dict) -> ActivityLap:
    """Build an ActivityLap row from a Strava lap dict."""
    return ActivityLap(
        activity_id=activity_id,
        lap_index=raw.get("lap_index"),
        name=raw.get("name"),
        elapsed_time=raw.get("elapsed_time"),
        moving_time=raw.get("moving_time"),
        distance=raw.get("distance"),
        start_date=_parse_dt(raw.get("start_date")),
        average_speed=raw.get("average_speed"),
        max_speed=raw.get("max_speed"),
        average_heartrate=raw.get("average_heartrate"),
        max_heartrate=raw.get("max_heartrate"),
        average_cadence=raw.get("average_cadence"),
        average_watts=raw.get("average_watts"),
        total_elevation_gain=raw.get("total_elevation_gain"),
        pace_zone=raw.get("pace_zone"),
        split=raw.get("split"),
        start_index=raw.get("start_index"),
        end_index=raw.get("end_index"),
    )
