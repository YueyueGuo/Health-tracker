from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from backend.config import settings
from backend.database import async_session

logger = logging.getLogger(__name__)


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

    logger.info(f"Scheduler configured: sync every {interval_hours} hours")
    return scheduler
