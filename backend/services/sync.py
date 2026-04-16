from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.clients.eight_sleep import EightSleepClient
from backend.clients.strava import StravaClient
from backend.clients.weather import WeatherClient
from backend.clients.whoop import WhoopClient
from backend.models import Activity, ActivityStream, Recovery, SleepSession, SyncLog, WeatherSnapshot


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

    async def sync_all(self) -> dict[str, int | str]:
        results: dict[str, int | str] = {}
        for source in ["strava", "eight_sleep", "whoop", "weather"]:
            try:
                count = await getattr(self, f"sync_{source}")()
                results[source] = count
            except Exception as e:
                results[source] = f"error: {e}"
        return results

    # ── Strava ──────────────────────────────────────────────────────

    async def sync_strava(self) -> int:
        from backend.config import settings
        if not settings.strava.access_token and not settings.strava.refresh_token:
            return 0

        log = SyncLog(source="strava", sync_type="incremental", status="running")
        self.db.add(log)
        await self.db.flush()

        try:
            # Find last synced activity
            last_sync = await self.db.execute(
                select(Activity.start_date)
                .order_by(Activity.start_date.desc())
                .limit(1)
            )
            last_date = last_sync.scalar_one_or_none()
            after = last_date if last_date else None

            activities = await self.strava.get_all_activities(after=after)
            count = 0

            for raw in activities:
                strava_id = raw["id"]
                existing = await self.db.execute(
                    select(Activity).where(Activity.strava_id == strava_id)
                )
                if existing.scalar_one_or_none():
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
                    weighted_avg_power=raw.get("weighted_average_watts"),
                    average_cadence=raw.get("average_cadence"),
                    calories=raw.get("calories"),
                    suffer_score=raw.get("suffer_score"),
                    start_lat=(raw.get("start_latlng") or [None, None])[0],
                    start_lng=(raw.get("start_latlng") or [None, None])[1],
                    summary_polyline=(raw.get("map") or {}).get("summary_polyline"),
                    raw_data=raw,
                )
                self.db.add(activity)
                await self.db.flush()

                # Fetch streams for this activity
                try:
                    streams = await self.strava.get_activity_streams(strava_id)
                    for stream_type, data in streams.items():
                        if data:
                            self.db.add(ActivityStream(
                                activity_id=activity.id,
                                stream_type=stream_type,
                                data=data,
                            ))
                    activity.has_streams = bool(streams)
                except Exception:
                    pass  # Streams are optional, don't fail the sync

                count += 1

            await self.db.commit()
            log.status = "success"
            log.records_synced = count
            log.completed_at = datetime.now(timezone.utc)
            await self.db.commit()
            return count

        except Exception as e:
            log.status = "error"
            log.error_message = str(e)
            log.completed_at = datetime.now(timezone.utc)
            await self.db.commit()
            raise

    # ── Eight Sleep ───────��─────────────────────────────────────────

    async def sync_eight_sleep(self, days: int = 30) -> int:
        if not settings_eight_sleep_configured():
            return 0

        log = SyncLog(source="eight_sleep", sync_type="incremental", status="running")
        self.db.add(log)
        await self.db.flush()

        try:
            sleep_data = await self.eight_sleep.get_recent_sleep(days=days)
            count = 0

            for day in sleep_data:
                sleep_date = date.fromisoformat(day.get("date", day.get("day", "")))

                existing = await self.db.execute(
                    select(SleepSession).where(
                        SleepSession.source == "eight_sleep",
                        SleepSession.date == sleep_date,
                    )
                )
                if existing.scalar_one_or_none():
                    continue

                # Extract sleep metrics from Eight Sleep data format
                sleep_info = day.get("sleepQualityScore", {})
                intervals = day.get("intervals", [])

                session = SleepSession(
                    source="eight_sleep",
                    date=sleep_date,
                    bed_time=_parse_dt(day.get("bedTime")),
                    wake_time=_parse_dt(day.get("wakeTime")),
                    total_duration=day.get("totalDuration"),
                    deep_sleep=day.get("deepSleepDuration"),
                    rem_sleep=day.get("remSleepDuration"),
                    light_sleep=day.get("lightSleepDuration"),
                    awake_time=day.get("awakeDuration"),
                    sleep_score=sleep_info if isinstance(sleep_info, (int, float))
                    else sleep_info.get("total"),
                    avg_hr=day.get("avgHeartRate"),
                    hrv=day.get("avgHrv"),
                    respiratory_rate=day.get("avgRespiratoryRate"),
                    bed_temp=day.get("avgBedTemp"),
                    raw_data=day,
                )
                self.db.add(session)
                count += 1

            await self.db.commit()
            log.status = "success"
            log.records_synced = count
            log.completed_at = datetime.now(timezone.utc)
            await self.db.commit()
            return count

        except Exception as e:
            log.status = "error"
            log.error_message = str(e)
            log.completed_at = datetime.now(timezone.utc)
            await self.db.commit()
            raise

    # ── Whoop ───────��───────────────────────────────────────────────

    async def sync_whoop(self, days: int = 30) -> int:
        if not self.whoop.is_enabled:
            return 0

        log = SyncLog(source="whoop", sync_type="incremental", status="running")
        self.db.add(log)
        await self.db.flush()

        try:
            end = date.today()
            start = end - timedelta(days=days)

            records = await self.whoop.get_recovery(start, end)
            count = 0

            for rec in records:
                rec_date = date.fromisoformat(rec.get("date", "")[:10])

                existing = await self.db.execute(
                    select(Recovery).where(Recovery.date == rec_date)
                )
                if existing.scalar_one_or_none():
                    continue

                recovery = Recovery(
                    source="whoop",
                    date=rec_date,
                    recovery_score=rec.get("score", {}).get("recovery_score"),
                    resting_hr=rec.get("score", {}).get("resting_heart_rate"),
                    hrv=rec.get("score", {}).get("hrv_rmssd_milli"),
                    spo2=rec.get("score", {}).get("spo2_percentage"),
                    skin_temp=rec.get("score", {}).get("skin_temp_celsius"),
                    strain_score=rec.get("strain"),
                    calories=rec.get("kilojoules"),
                    raw_data=rec,
                )
                self.db.add(recovery)
                count += 1

            await self.db.commit()
            log.status = "success"
            log.records_synced = count
            log.completed_at = datetime.now(timezone.utc)
            await self.db.commit()
            return count

        except Exception as e:
            log.status = "error"
            log.error_message = str(e)
            log.completed_at = datetime.now(timezone.utc)
            await self.db.commit()
            raise

    # ── Weather enrichment ──────────────────────────────────────────

    async def sync_weather(self) -> int:
        if not self.weather.is_configured:
            return 0

        # Find outdoor activities without weather data
        result = await self.db.execute(
            select(Activity).where(
                Activity.weather_enriched == False,  # noqa: E712
                Activity.start_lat.isnot(None),
                Activity.start_lng.isnot(None),
            )
        )
        activities = result.scalars().all()
        count = 0

        for activity in activities:
            try:
                weather_data = await self.weather.get_historical_weather(
                    lat=activity.start_lat,
                    lng=activity.start_lng,
                    dt=activity.start_date,
                )
                if weather_data:
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
                    count += 1
            except Exception:
                continue  # Don't fail the whole batch for one activity

        await self.db.commit()
        return count


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
