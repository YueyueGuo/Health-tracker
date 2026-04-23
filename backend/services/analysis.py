from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Activity, Recovery, SleepSession
from backend.services.llm_providers import get_provider

SYSTEM_PROMPT = """You are a personal health and fitness analyst with deep expertise in \
exercise physiology, sleep science, and recovery optimization.

You are analyzing data for a single individual who does both endurance training (running, \
cycling) and strength training. Be specific, reference actual numbers from the data, and \
provide actionable recommendations. Avoid generic advice.

Key principles:
- Training load should follow periodization (hard/easy day cycling)
- HRV trends matter more than single readings
- Sleep quality (deep + REM %) matters as much as duration
- Weather affects performance (heat, humidity, altitude)
- Recovery dictates what training is appropriate today
- Strength training creates different recovery demands than endurance work

When analyzing, always consider:
1. The immediate data (the specific workout or metric asked about)
2. The trend context (how does this compare to recent history?)
3. Cross-domain correlations (how did sleep affect the workout? weather?)
4. Actionable next steps (what should the user do differently?)

Format your responses in clear markdown with headers and bullet points."""


class AnalysisEngine:
    """Model-agnostic analysis engine that assembles context and queries LLMs.

    Free-form Q&A only. Structured daily recommendations and per-workout
    insights live in ``backend/services/insights.py`` and are served under
    ``/api/insights/*``.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def query(
        self, question: str, model: str | None = None
    ) -> AnalysisResult:
        """Answer a free-form question about the user's health data."""
        context = await self._build_context()
        user_message = f"{context}\n\n## Question\n{question}"

        provider = get_provider(model)
        try:
            response = await provider.query(
                system_prompt=SYSTEM_PROMPT,
                user_message=user_message,
            )
        finally:
            await provider.close()

        return AnalysisResult(
            answer=response.text,
            model=response.model,
            tokens_used=response.tokens_used,
            context_summary=context[:500],
        )

    async def _build_context(self) -> str:
        sections = []

        activities = await self._get_recent_activities(days=14)
        if activities:
            sections.append(self._format_activities(activities))

        sleep = await self._get_recent_sleep(days=7)
        if sleep:
            sections.append(self._format_sleep(sleep))

        recovery = await self._get_recent_recovery(days=7)
        if recovery:
            sections.append(self._format_recovery(recovery))

        return "\n\n".join(sections) if sections else "No data available yet."

    async def _get_recent_activities(self, days: int = 14) -> list[Activity]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        result = await self.db.execute(
            select(Activity)
            .where(Activity.start_date >= cutoff)
            .order_by(Activity.start_date.desc())
        )
        return list(result.scalars().all())

    async def _get_recent_sleep(self, days: int = 7) -> list[SleepSession]:
        cutoff = date.today() - timedelta(days=days)
        result = await self.db.execute(
            select(SleepSession)
            .where(SleepSession.date >= cutoff)
            .order_by(SleepSession.date.desc())
        )
        return list(result.scalars().all())

    async def _get_recent_recovery(self, days: int = 7) -> list[Recovery]:
        cutoff = date.today() - timedelta(days=days)
        result = await self.db.execute(
            select(Recovery)
            .where(Recovery.date >= cutoff)
            .order_by(Recovery.date.desc())
        )
        return list(result.scalars().all())

    def _format_activities(self, activities: list[Activity]) -> str:
        lines = ["## Recent Activities"]
        for a in activities:
            dur = f"{a.moving_time // 60}min" if a.moving_time else "?"
            dist = f"{a.distance / 1000:.1f}km" if a.distance else ""
            hr = f"avg HR {a.average_hr:.0f}" if a.average_hr else ""
            parts = [f"- **{a.name}** ({a.sport_type}) — {a.start_date.strftime('%b %d')}"]
            if dist:
                parts.append(dist)
            parts.append(dur)
            if hr:
                parts.append(hr)
            if a.calories:
                parts.append(f"{a.calories:.0f}cal")
            lines.append(", ".join(parts))
        return "\n".join(lines)

    def _format_sleep(self, sessions: list[SleepSession]) -> str:
        lines = []
        for s in sessions:
            parts = [f"- **{s.date}** ({s.source})"]
            if s.sleep_score is not None:
                parts.append(f"score: {s.sleep_score:.0f}")
            if s.total_duration:
                hrs, mins = divmod(s.total_duration, 60)
                parts.append(f"{hrs}h{mins}m")
            if s.deep_sleep:
                parts.append(f"deep: {s.deep_sleep}min")
            if s.rem_sleep:
                parts.append(f"REM: {s.rem_sleep}min")
            if s.hrv:
                parts.append(f"HRV: {s.hrv:.0f}ms")
            if s.avg_hr:
                parts.append(f"avg HR: {s.avg_hr:.0f}")
            lines.append(", ".join(parts))
        return "\n".join(lines) if lines else "No sleep data."

    def _format_recovery(self, records: list[Recovery]) -> str:
        lines = []
        for r in records:
            parts = [f"- **{r.date}**"]
            if r.recovery_score is not None:
                parts.append(f"recovery: {r.recovery_score:.0f}%")
            if r.hrv:
                parts.append(f"HRV: {r.hrv:.0f}ms")
            if r.resting_hr:
                parts.append(f"resting HR: {r.resting_hr:.0f}")
            if r.strain_score:
                parts.append(f"strain: {r.strain_score:.1f}")
            lines.append(", ".join(parts))
        return "\n".join(lines) if lines else "No recovery data."


class AnalysisResult:
    def __init__(
        self,
        answer: str,
        model: str,
        tokens_used: int | None = None,
        context_summary: str = "",
    ):
        self.answer = answer
        self.model = model
        self.tokens_used = tokens_used
        self.context_summary = context_summary

    def to_dict(self) -> dict:
        return {
            "answer": self.answer,
            "model": self.model,
            "tokens_used": self.tokens_used,
        }
