"""First-time full data pull from all configured sources."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.clients import get_weather_client
from backend.clients.eight_sleep import EightSleepClient
from backend.clients.strava import StravaClient
from backend.clients.whoop import WhoopClient
from backend.database import async_session, init_db
from backend.services.sync import SyncEngine


async def main():
    print("Initializing database...")
    await init_db()

    async with async_session() as db:
        strava = StravaClient()
        eight_sleep = EightSleepClient()
        whoop = WhoopClient()
        weather = get_weather_client()
        engine = SyncEngine(db, strava, eight_sleep, whoop, weather)

        try:
            print("\nSyncing Strava activities...")
            strava_count = await engine.sync_strava()
            print(f"  -> {strava_count} activities synced")

            print("\nSyncing Eight Sleep data...")
            sleep_count = await engine.sync_eight_sleep(days=90)
            print(f"  -> {sleep_count} sleep sessions synced")

            print("\nSyncing Whoop data...")
            whoop_count = await engine.sync_whoop(days=90)
            print(f"  -> {whoop_count} recovery records synced")

            print("\nEnriching activities with weather data...")
            weather_count = await engine.sync_weather()
            print(f"  -> {weather_count} weather snapshots added")

            print("\nSync complete!")
            print(f"  Activities: {strava_count}")
            print(f"  Sleep sessions: {sleep_count}")
            print(f"  Recovery records: {whoop_count}")
            print(f"  Weather snapshots: {weather_count}")

        except Exception as e:
            print(f"\nError during sync: {e}")
            raise
        finally:
            await strava.close()
            await eight_sleep.close()
            await whoop.close()
            await weather.close()


if __name__ == "__main__":
    asyncio.run(main())
