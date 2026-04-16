from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Activity, ActivityStream, Recovery, SleepSession, WeatherSnapshot
from backend.services.llm_providers import LLMResponse, get_provider

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
    """Model-agnostic analysis engine that assembles context and queries LLMs."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def query(
        self, question: str, model: str | None = None
    ) -> AnalysisResult:
        """Answer a free-form question about the user's health data."""
        context = await self._build_context(question)
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

    async def daily_briefing(self, model: str | None = None) -> AnalysisResult:
        """Generate today's training/recovery briefing."""
        context = await self._build_daily_context()
        prompt = (
            f"{context}\n\n"
            "## Request\n"
            "Provide today's training briefing:\n"
            "1. Readiness assessment (1-10 with explanation)\n"
            "2. Recommended workout type and intensity\n"
            "3. Any concerns or things to watch\n"
            "4. One specific, actionable tip"
        )

        provider = get_provider(model)
        try:
            response = await provider.query(
                system_prompt=SYSTEM_PROMPT,
                user_message=prompt,
            )
        finally:
            await provider.close()

        return AnalysisResult(
            answer=response.text,
            model=response.model,
            tokens_used=response.tokens_used,
            context_summary="Daily briefing",
        )

    async def workout_analysis(
        self, activity_id: int, model: str | None = None
    ) -> AnalysisResult:
        """Deep analysis of a specific workout."""
        context = await self._build_workout_context(activity_id)
        prompt = (
            f"{context}\n\n"
            "## Request\n"
            "Analyze this workout in detail:\n"
            "1. Performance assessment vs. recent history\n"
            "2. What factors helped or hurt performance\n"
            "3. Recovery recommendations post-workout\n"
            "4. What this means for the training plan going forward"
        )

        provider = get_provider(model)
        try:
            response = await provider.query(
                system_prompt=SYSTEM_PROMPT,
                user_message=prompt,
            )
        finally:
            await provider.close()

        return AnalysisResult(
            answer=response.text,
            model=response.model,
            tokens_used=response.tokens_used,
            context_summary=f"Workout analysis for activity {activity_id}",
        )

    # ── Context builders ────��───────────────────────────────────────

    async def _build_context(self, question: str) -> str:
        """Build general context based on the question."""
        sections = []

        # Recent activities (last 14 days)
        activities = await self._get_recent_activities(days=14)
        if activities:
            sections.append(self._format_activities(activities))

        # Recent sleep (last 7 days)
        sleep = await self._get_recent_sleep(days=7)
        if sleep:
            sections.append(self._format_sleep(sleep))

        # Recovery data
        recovery = await self._get_recent_recovery(days=7)
        if recovery:
            sections.append(self._format_recovery(recovery))

        return "\n\n".join(sections) if sections else "No data available yet."

    async def _build_daily_context(self) -> str:
        """Build context for daily briefing."""
        sections = []

        # Last night's sleep
        sleep = await self._get_recent_sleep(days=1)
        if sleep:
            sections.append("## Last Night's Sleep\n" + self._format_sleep(sleep))

        # Recent recovery
        recovery = await self._get_recent_recovery(days=3)
        if recovery:
            sections.append("## Recovery\n" + self._format_recovery(recovery))

        # Last 7 days of training
        activities = await self._get_recent_activities(days=7)
        if activities:
            sections.append("## Recent Training (7 days)\n" + self._format_activities(activities))

        return "\n\n".join(sections) if sections else "No data available yet."

    async def _build_workout_context(self, activity_id: int) -> str:
        """Build context for a specific workout analysis."""
        sections = []

        # The workout itself
        result = await self.db.execute(
            select(Activity).where(Activity.id == activity_id)
        )
        activity = result.scalar_one_or_none()
        if not activity:
            return "Activity not found."

        sections.append("## Workout Data\n" + self._format_single_activity(activity))

        # Streams summary
        streams_result = await self.db.execute(
            select(ActivityStream).where(ActivityStream.activity_id == activity_id)
        )
        streams = streams_result.scalars().all()
        if streams:
            sections.append("## Stream Data\n" + self._format_streams(streams))

        # Weather
        weather_result = await self.db.execute(
            select(WeatherSnapshot).where(WeatherSnapshot.activity_id == activity_id)
        )
        weather = weather_result.scalar_one_or_none()
        if weather:
            sections.append(
                f"## Weather Conditions\n"
                f"- Temp: {weather.temp_c}°C (feels like {weather.feels_like_c}°C)\n"
                f"- Conditions: {weather.conditions} ({weather.description})\n"
                f"- Humidity: {weather.humidity}%\n"
                f"- Wind: {weather.wind_speed} m/s"
            )

        # Pre-workout sleep
        sleep = await self._get_recent_sleep(days=1)
        if sleep:
            sections.append("## Pre-Workout Sleep\n" + self._format_sleep(sleep))

        # Recent training context
        activities = await self._get_recent_activities(days=7)
        if activities:
            sections.append("## Recent Training\n" + self._format_activities(activities))

        return "\n\n".join(sections)

    # ── Data fetchers ───────────────────────────────────────────────

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

    # ── Formatters ───────────────────────────────────��──────────────

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

    def _format_single_activity(self, a: Activity) -> str:
        lines = [
            f"- **Name**: {a.name}",
            f"- **Type**: {a.sport_type}",
            f"- **Date**: {a.start_date.strftime('%Y-%m-%d %H:%M')}",
        ]
        if a.distance:
            lines.append(f"- **Distance**: {a.distance / 1000:.2f} km")
        if a.moving_time:
            mins, secs = divmod(a.moving_time, 60)
            lines.append(f"- **Moving Time**: {mins}m {secs}s")
        if a.elapsed_time:
            mins, secs = divmod(a.elapsed_time, 60)
            lines.append(f"- **Elapsed Time**: {mins}m {secs}s")
        if a.average_hr:
            lines.append(f"- **Avg HR**: {a.average_hr:.0f} bpm")
        if a.max_hr:
            lines.append(f"- **Max HR**: {a.max_hr:.0f} bpm")
        if a.average_speed:
            pace_min_km = (1000 / a.average_speed) / 60 if a.average_speed > 0 else 0
            lines.append(f"- **Avg Pace**: {pace_min_km:.2f} min/km")
        if a.average_power:
            lines.append(f"- **Avg Power**: {a.average_power:.0f}W")
        if a.total_elevation:
            lines.append(f"- **Elevation Gain**: {a.total_elevation:.0f}m")
        if a.calories:
            lines.append(f"- **Calories**: {a.calories:.0f}")
        if a.suffer_score:
            lines.append(f"- **Relative Effort**: {a.suffer_score}")
        return "\n".join(lines)

    def _format_streams(self, streams: list[ActivityStream]) -> str:
        lines = []
        for s in streams:
            data = s.data
            if not data or not isinstance(data, list):
                continue
            nums = [x for x in data if isinstance(x, (int, float))]
            if not nums:
                continue
            lines.append(
                f"- **{s.stream_type}**: min={min(nums):.1f}, "
                f"max={max(nums):.1f}, avg={sum(nums) / len(nums):.1f}, "
                f"points={len(nums)}"
            )
        return "\n".join(lines) if lines else "No stream data."

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
