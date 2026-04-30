"""LLM-driven dashboard insights.

Public entry points live here; schemas, prompts, and cache helpers are split
into focused modules so the orchestration stays readable.
"""

from __future__ import annotations

import json
import logging
import time
import asyncio
from dataclasses import dataclass
from datetime import date, timedelta

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.models import AnalysisCache
from backend.services import training_metrics
from backend.services.insight_cache import _cache_get, _cache_put, _hash_inputs
from backend.services.insight_prompts import (
    DAILY_REC_SYSTEM_PROMPT,
    WORKOUT_INSIGHT_SYSTEM_PROMPT,
)
from backend.services.insight_schemas import (
    DailyRecommendation,
    NotableSegment,
    WorkoutInsight,
    _pydantic_schema,
)
from backend.services.llm_providers import LLMProvider, get_provider, is_model_configured
from backend.services.snapshot_models import daily_recommendation_cache_signal
from backend.services.time_utils import utc_now

logger = logging.getLogger(__name__)


def _maybe_unwrap(raw: dict, expected_keys: set[str]) -> dict:
    """Handle providers that wrap structured output in an extra object."""
    if not isinstance(raw, dict):
        return raw

    if (
        len(raw) == 1
        and next(iter(raw.keys())) not in expected_keys
        and isinstance(next(iter(raw.values())), dict)
    ):
        return next(iter(raw.values()))

    wrappers = [
        k for k, v in raw.items()
        if k not in expected_keys and isinstance(v, dict)
    ]
    if wrappers and any(k in expected_keys for k in raw.keys()):
        merged = {k: v for k, v in raw.items() if k in expected_keys}
        for wrapper in wrappers:
            for k, v in raw[wrapper].items():
                if k in expected_keys and k not in merged:
                    merged[k] = v
        if merged:
            return merged
    return raw


async def _call_llm_structured(
    system_prompt: str,
    user_message: str,
    response_model: type[BaseModel],
    model_chain: list[str],
    schema_name: str,
) -> tuple[BaseModel, str]:
    """Try each model in `model_chain`, returning (parsed_model, model_used)."""
    schema = _pydantic_schema(response_model)
    expected_keys = set((schema.get("properties") or {}).keys())
    last_exc: Exception | None = None

    for model_key in model_chain:
        if not is_model_configured(model_key):
            logger.info("LLM provider not configured for %s; skipping", model_key)
            continue
        provider: LLMProvider | None = None
        try:
            provider = get_provider(model_key)
        except Exception as e:
            logger.warning("LLM provider init failed for %s: %s", model_key, e)
            last_exc = e
            continue

        try:
            raw = await asyncio.wait_for(
                provider.query_structured(
                    system_prompt=system_prompt,
                    user_message=user_message,
                    schema=schema,
                    schema_name=schema_name,
                ),
                timeout=settings.llm.request_timeout_seconds,
            )
            logger.debug("LLM raw response from %s: %s", model_key, json.dumps(raw)[:500])
            raw = _maybe_unwrap(raw, expected_keys)
            try:
                parsed = response_model.model_validate(raw)
                return parsed, model_key
            except ValidationError as ve:
                logger.info("Schema validation failed, retrying with correction: %s", ve)
                correction = (
                    f"{user_message}\n\nYour previous response did not match the schema. "
                    f"Errors: {ve.errors()}\n"
                    "Do NOT wrap the response in any outer key. The top-level JSON object "
                    f"MUST have exactly these keys: {sorted(expected_keys)}. "
                    "Return ONLY valid JSON matching the schema."
                )
                raw2 = await asyncio.wait_for(
                    provider.query_structured(
                        system_prompt=system_prompt,
                        user_message=correction,
                        schema=schema,
                        schema_name=schema_name,
                    ),
                    timeout=settings.llm.request_timeout_seconds,
                )
                raw2 = _maybe_unwrap(raw2, expected_keys)
                parsed = response_model.model_validate(raw2)
                return parsed, model_key
        except Exception as e:
            logger.warning("LLM call failed on %s: %s", model_key, e)
            last_exc = e
        finally:
            if provider is not None:
                try:
                    await provider.close()
                except Exception:
                    pass

    raise last_exc or RuntimeError("No LLM provider succeeded")


def _build_model_chain(model: str | None) -> list[str]:
    primary = model or settings.llm.dashboard_model
    chain = [primary]
    for fb in settings.llm.dashboard_fallback_models:
        if fb != primary:
            chain.append(fb)
    return chain


@dataclass
class DailyRecommendationResult:
    recommendation: DailyRecommendation
    inputs: dict
    model: str
    generated_at: str
    cached: bool
    cache_key: str
    recommendation_date: str

    def to_dict(self) -> dict:
        return {
            "recommendation": self.recommendation.model_dump(),
            "inputs": self.inputs,
            "model": self.model,
            "generated_at": self.generated_at,
            "cached": self.cached,
            "cache_key": self.cache_key,
            "recommendation_date": self.recommendation_date,
        }


@dataclass
class WorkoutInsightResult:
    activity_id: int
    workout: dict
    insight: WorkoutInsight | None
    model: str
    generated_at: str
    cached: bool

    def to_dict(self) -> dict:
        return {
            "activity_id": self.activity_id,
            "workout": self.workout,
            "insight": self.insight.model_dump() if self.insight else None,
            "model": self.model,
            "generated_at": self.generated_at,
            "cached": self.cached,
        }


async def get_cached_recommendation_for_date(
    db: AsyncSession, target_date: date
) -> DailyRecommendationResult | None:
    """Look up the most recently created cached daily-rec for a past date.

    Cache keys are formed as ``daily_rec:{YYYY-MM-DD}:{model}:{inputs_hash}``.
    For a given date there may be 0..N matching rows (multiple inputs hashes
    or models throughout the day). We return the newest non-expired one, or
    None. Never calls the LLM — this is the read path for the date-navigator.
    """
    prefix = f"daily_rec:{target_date.isoformat()}:"
    rows = await db.execute(
        select(AnalysisCache)
        .where(AnalysisCache.query_hash.like(f"{prefix}%"))
        .order_by(AnalysisCache.created_at.desc())
    )
    for row in rows.scalars().all():
        try:
            payload = json.loads(row.response_text)
        except json.JSONDecodeError:
            continue
        recommendation = payload.get("recommendation")
        if recommendation is None:
            continue
        try:
            parsed = DailyRecommendation.model_validate(recommendation)
        except ValidationError:
            continue
        return DailyRecommendationResult(
            recommendation=parsed,
            inputs=payload.get("inputs") or {},
            model=payload.get("model") or row.model,
            generated_at=payload.get("generated_at") or "",
            cached=True,
            cache_key=row.query_hash,
            recommendation_date=target_date.isoformat(),
        )
    return None


async def get_latest_workout_summary(
    db: AsyncSession,
    activity_id: int | None = None,
    on_date: date | None = None,
) -> WorkoutInsightResult | None:
    """Return the latest-workout snapshot without generating an LLM insight."""
    snapshot = await training_metrics.get_latest_workout_snapshot(
        db, activity_id, on_date=on_date
    )
    if not snapshot:
        return None
    return WorkoutInsightResult(
        activity_id=snapshot["id"],
        workout=snapshot,
        insight=None,
        model="summary-only",
        generated_at="",
        cached=False,
    )


async def get_cached_latest_workout_insight(
    db: AsyncSession,
    activity_id: int | None = None,
    model: str | None = None,
    on_date: date | None = None,
) -> WorkoutInsightResult | None:
    """Return a cached latest-workout insight without generating a new one."""
    activity = await training_metrics._get_latest_completed_activity(
        db, activity_id, on_date
    )
    if activity is None:
        return None

    requested_model = model or settings.llm.dashboard_model
    cache_key = f"workout_insight:{activity.id}:{requested_model}"
    hit = await _cache_get(db, cache_key)
    if not hit:
        return None

    return WorkoutInsightResult(
        activity_id=activity.id,
        workout=hit["workout"],
        insight=WorkoutInsight.model_validate(hit["insight"]),
        model=hit["model"],
        generated_at=hit["generated_at"],
        cached=True,
    )


async def get_daily_recommendation(
    db: AsyncSession,
    model: str | None = None,
    refresh: bool = False,
) -> DailyRecommendationResult:
    started_at = time.perf_counter()
    stage_started = time.perf_counter()
    snapshot = await training_metrics.get_full_snapshot(db)
    snapshot_ms = (time.perf_counter() - stage_started) * 1000

    stage_started = time.perf_counter()
    signal = daily_recommendation_cache_signal(snapshot)
    inputs_hash = _hash_inputs(signal)
    requested_model = model or settings.llm.dashboard_model
    cache_key = f"daily_rec:{snapshot['today']}:{requested_model}:{inputs_hash}"
    cache_key_ms = (time.perf_counter() - stage_started) * 1000

    cache_ms = 0.0
    if not refresh:
        stage_started = time.perf_counter()
        hit = await _cache_get(db, cache_key)
        cache_ms = (time.perf_counter() - stage_started) * 1000
        if hit:
            total_ms = (time.perf_counter() - started_at) * 1000
            logger.info(
                "insights.daily_recommendation total_ms=%.1f snapshot_ms=%.1f "
                "cache_key_ms=%.1f cache_ms=%.1f cache_hit=true refresh=%s model=%s",
                total_ms,
                snapshot_ms,
                cache_key_ms,
                cache_ms,
                refresh,
                requested_model,
            )
            return DailyRecommendationResult(
                recommendation=DailyRecommendation.model_validate(hit["recommendation"]),
                inputs=hit["inputs"],
                model=hit["model"],
                generated_at=hit["generated_at"],
                cached=True,
                cache_key=cache_key,
                recommendation_date=snapshot["today"],
            )

    user_message = (
        "Here is the athlete's current state as JSON.\n\n```json\n"
        + json.dumps(snapshot, indent=2, default=str)
        + "\n```\n\n"
        "Based on this, recommend what they should do today."
    )

    stage_started = time.perf_counter()
    parsed, model_used = await _call_llm_structured(
        system_prompt=DAILY_REC_SYSTEM_PROMPT,
        user_message=user_message,
        response_model=DailyRecommendation,
        model_chain=_build_model_chain(model),
        schema_name="daily_recommendation",
    )
    llm_ms = (time.perf_counter() - stage_started) * 1000

    generated_at = utc_now().isoformat()
    payload = {
        "recommendation": parsed.model_dump(),
        "inputs": snapshot,
        "model": model_used,
        "generated_at": generated_at,
    }
    stage_started = time.perf_counter()
    await _cache_put(
        db,
        cache_key,
        query_text=f"daily_rec for {snapshot['today']}",
        payload=payload,
        model=model_used,
        ttl=timedelta(hours=24),
    )
    cache_put_ms = (time.perf_counter() - stage_started) * 1000

    total_ms = (time.perf_counter() - started_at) * 1000
    logger.info(
        "insights.daily_recommendation total_ms=%.1f snapshot_ms=%.1f "
        "cache_key_ms=%.1f cache_ms=%.1f llm_ms=%.1f cache_put_ms=%.1f "
        "cache_hit=false refresh=%s requested_model=%s model_used=%s",
        total_ms,
        snapshot_ms,
        cache_key_ms,
        cache_ms,
        llm_ms,
        cache_put_ms,
        refresh,
        requested_model,
        model_used,
    )

    return DailyRecommendationResult(
        recommendation=parsed,
        inputs=snapshot,
        model=model_used,
        generated_at=generated_at,
        cached=False,
        cache_key=cache_key,
        recommendation_date=snapshot["today"],
    )


async def get_latest_workout_insight(
    db: AsyncSession,
    activity_id: int | None = None,
    model: str | None = None,
    refresh: bool = False,
    on_date: date | None = None,
) -> WorkoutInsightResult | None:
    started_at = time.perf_counter()
    stage_started = time.perf_counter()
    snapshot = await training_metrics.get_latest_workout_snapshot(
        db, activity_id, on_date=on_date
    )
    snapshot_ms = (time.perf_counter() - stage_started) * 1000
    if not snapshot:
        logger.info(
            "insights.latest_workout total_ms=%.1f snapshot_ms=%.1f "
            "cache_hit=false empty=true refresh=%s activity_id=%s on_date=%s",
            (time.perf_counter() - started_at) * 1000,
            snapshot_ms,
            refresh,
            activity_id,
            on_date.isoformat() if on_date else None,
        )
        return None

    requested_model = model or settings.llm.dashboard_model
    cache_key = f"workout_insight:{snapshot['id']}:{requested_model}"

    cache_ms = 0.0
    if not refresh:
        stage_started = time.perf_counter()
        hit = await _cache_get(db, cache_key)
        cache_ms = (time.perf_counter() - stage_started) * 1000
        if hit:
            logger.info(
                "insights.latest_workout total_ms=%.1f snapshot_ms=%.1f "
                "cache_ms=%.1f cache_hit=true refresh=%s activity_id=%s "
                "workout_id=%s model=%s on_date=%s",
                (time.perf_counter() - started_at) * 1000,
                snapshot_ms,
                cache_ms,
                refresh,
                activity_id,
                snapshot["id"],
                requested_model,
                on_date.isoformat() if on_date else None,
            )
            return WorkoutInsightResult(
                activity_id=snapshot["id"],
                workout=hit["workout"],
                insight=WorkoutInsight.model_validate(hit["insight"]),
                model=hit["model"],
                generated_at=hit["generated_at"],
                cached=True,
            )

    user_message = (
        "Here is the workout data and context as JSON.\n\n```json\n"
        + json.dumps(snapshot, indent=2, default=str)
        + "\n```\n\n"
        "Give a data-driven insight."
    )

    stage_started = time.perf_counter()
    parsed, model_used = await _call_llm_structured(
        system_prompt=WORKOUT_INSIGHT_SYSTEM_PROMPT,
        user_message=user_message,
        response_model=WorkoutInsight,
        model_chain=_build_model_chain(model),
        schema_name="workout_insight",
    )
    llm_ms = (time.perf_counter() - stage_started) * 1000

    generated_at = utc_now().isoformat()
    payload = {
        "workout": snapshot,
        "insight": parsed.model_dump(),
        "model": model_used,
        "generated_at": generated_at,
    }
    stage_started = time.perf_counter()
    await _cache_put(
        db,
        cache_key,
        query_text=f"workout_insight for activity {snapshot['id']}",
        payload=payload,
        model=model_used,
        ttl=None,
    )
    cache_put_ms = (time.perf_counter() - stage_started) * 1000

    logger.info(
        "insights.latest_workout total_ms=%.1f snapshot_ms=%.1f cache_ms=%.1f "
        "llm_ms=%.1f cache_put_ms=%.1f cache_hit=false refresh=%s "
        "activity_id=%s workout_id=%s requested_model=%s model_used=%s on_date=%s",
        (time.perf_counter() - started_at) * 1000,
        snapshot_ms,
        cache_ms,
        llm_ms,
        cache_put_ms,
        refresh,
        activity_id,
        snapshot["id"],
        requested_model,
        model_used,
        on_date.isoformat() if on_date else None,
    )

    return WorkoutInsightResult(
        activity_id=snapshot["id"],
        workout=snapshot,
        insight=parsed,
        model=model_used,
        generated_at=generated_at,
        cached=False,
    )


__all__ = [
    "DAILY_REC_SYSTEM_PROMPT",
    "WORKOUT_INSIGHT_SYSTEM_PROMPT",
    "DailyRecommendation",
    "DailyRecommendationResult",
    "NotableSegment",
    "WorkoutInsight",
    "WorkoutInsightResult",
    "_build_model_chain",
    "_cache_get",
    "_cache_put",
    "_call_llm_structured",
    "_hash_inputs",
    "_maybe_unwrap",
    "_pydantic_schema",
    "get_cached_latest_workout_insight",
    "get_daily_recommendation",
    "get_latest_workout_insight",
    "get_latest_workout_summary",
    "get_provider",
]
