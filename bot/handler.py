from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Activity
from backend.services.analysis import AnalysisEngine, AnalysisResult


class ChatHandler:
    """Bot-agnostic conversation handler. Shared logic for Telegram + Discord."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.engine = AnalysisEngine(db)

    async def handle_question(
        self, question: str, model: str | None = None
    ) -> AnalysisResult:
        """Answer a free-form question."""
        return await self.engine.query(question=question, model=model)

    async def daily_briefing(self, model: str | None = None) -> AnalysisResult:
        """Generate today's training briefing."""
        return await self.engine.daily_briefing(model=model)

    async def last_workout_analysis(self, model: str | None = None) -> AnalysisResult:
        """Analyze the most recent workout."""
        result = await self.db.execute(
            select(Activity).order_by(Activity.start_date.desc()).limit(1)
        )
        activity = result.scalar_one_or_none()
        if not activity:
            return AnalysisResult(
                answer="No workouts found in the database. Try syncing your data first with /sync.",
                model="none",
            )
        return await self.engine.workout_analysis(activity_id=activity.id, model=model)

    async def weekly_summary(self, model: str | None = None) -> AnalysisResult:
        """Generate a weekly training summary."""
        return await self.engine.query(
            question="Give me a comprehensive summary of my training this week. "
            "Include total volume, intensity distribution, sleep quality trends, "
            "and recovery status. What went well and what should I adjust?",
            model=model,
        )

    async def trigger_sync(self, source: str = "all") -> dict[str, int]:
        """Trigger a data sync."""
        from backend.clients.eight_sleep import EightSleepClient
        from backend.clients.strava import StravaClient
        from backend.clients.weather import WeatherClient
        from backend.clients.whoop import WhoopClient
        from backend.services.sync import SyncEngine

        strava = StravaClient()
        eight_sleep = EightSleepClient()
        whoop = WhoopClient()
        weather = WeatherClient()
        engine = SyncEngine(self.db, strava, eight_sleep, whoop, weather)

        try:
            if source == "all":
                return await engine.sync_all()
            sync_method = getattr(engine, f"sync_{source}")
            count = await sync_method()
            return {source: count}
        finally:
            await strava.close()
            await eight_sleep.close()
            await whoop.close()
            await weather.close()
