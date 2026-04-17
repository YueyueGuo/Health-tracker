from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import func, select

from backend.config import settings
from backend.database import async_session
from backend.models.activity import Activity

logger = logging.getLogger(__name__)


async def _run_strava_enrichment_drain(*, batch: int = 40):
    """Drain pending Strava activity enrichments.

    Runs periodically. Skips when:
      * there are no pending activities (fast no-op)
      * the daily Strava read quota has been hit
    """
    from backend.clients.strava import StravaClient
    from backend.clients import get_weather_client
    from backend.clients.eight_sleep import EightSleepClient
    from backend.clients.whoop import WhoopClient
    from backend.services.sync import SyncEngine

    async with async_session() as db:
        pending = await db.scalar(
            select(func.count(Activity.id)).where(
                Activity.enrichment_status == "pending"
            )
        )
        if not pending:
            logger.debug("Enrichment drain idle: No pending activities")
            return

        if StravaClient.daily_quota_exhausted():
            which = ",".join(StravaClient.which_quota_exhausted())
            logger.info(
                "Enrichment drain skipped: daily quota exhausted (%s)", which
            )
            return

        strava = StravaClient()
        eight_sleep = EightSleepClient()
        whoop = WhoopClient()
        weather = get_weather_client()
        engine = SyncEngine(db, strava, eight_sleep, whoop, weather)
        try:
            count = await engine._strava_phase_b(limit=batch)
            logger.info(
                "Enrichment drain: enriched=%s pending_before=%s", count, pending
            )
        except Exception as e:
            logger.warning("Enrichment drain error: %s", e)
        finally:
            await strava.close()
            await eight_sleep.close()
            await whoop.close()
            await weather.close()


async def _run_sync(source: str = "all"):
    """Background sync job."""
    from backend.clients import get_weather_client
    from backend.clients.eight_sleep import EightSleepClient
    from backend.clients.strava import StravaClient
    from backend.clients.whoop import WhoopClient
    from backend.services.sync import SyncEngine

    async with async_session() as db:
        strava = StravaClient()
        eight_sleep = EightSleepClient()
        whoop = WhoopClient()
        weather = get_weather_client()
        engine = SyncEngine(db, strava, eight_sleep, whoop, weather)

        try:
            if source == "all":
                results = await engine.sync_all()
                logger.info(f"Scheduled sync complete: {results}")
            else:
                sync_method = getattr(engine, f"sync_{source}")
                count = await sync_method()
                logger.info(f"Scheduled {source} sync: {count} records")
        except Exception as e:
            logger.error(f"Scheduled sync error: {e}")
        finally:
            await strava.close()
            await eight_sleep.close()
            await whoop.close()
            await weather.close()


def create_scheduler() -> AsyncIOScheduler:
    """Create the background sync scheduler."""
    scheduler = AsyncIOScheduler()

    interval_hours = settings.sync_interval_hours

    scheduler.add_job(
        _run_sync,
        "interval",
        hours=interval_hours,
        args=["all"],
        id="sync_all",
        name="Sync all data sources",
    )

    # Drain Strava enrichment queue every 20 minutes (no-op when queue
    # empty or the daily quota has been hit).
    scheduler.add_job(
        _run_strava_enrichment_drain,
        "interval",
        minutes=20,
        id="strava_enrichment_drain",
        name="Drain Strava activity enrichment queue",
        coalesce=True,
        max_instances=1,
    )

    logger.info(
        "Scheduler configured: sync every %s hours, enrichment drain every 20 min",
        interval_hours,
    )
    return scheduler
