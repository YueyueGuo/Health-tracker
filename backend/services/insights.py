"""LLM-driven dashboard insights.

Two structured outputs:
  - `daily_recommendation`: what should I do today, given my training load,
    recent sleep and recovery.
  - `latest_workout_insight`: a short human-readable takeaway for the most
    recent completed workout, plus comparison to historicals.

Both use Anthropic / OpenAI / Google structured-output modes via the
provider's `query_structured` method. Results are cached in the
`analysis_cache` table so the dashboard is cheap to render.

No rules in this module — the LLM decides. We only compute the inputs
(see `training_metrics.py`).
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.models import AnalysisCache
from backend.services import training_metrics
from backend.services.llm_providers import LLMProvider, get_provider

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────
# Pydantic response schemas
# ──────────────────────────────────────────────────────────────────────────


class DailyRecommendation(BaseModel):
    intensity: Literal["rest", "recovery", "easy", "moderate", "quality"] = Field(
        ...,
        description=(
            "rest = full rest day; recovery = active recovery / walk / mobility; "
            "easy = low aerobic; moderate = steady aerobic; quality = "
            "intervals/tempo/threshold."
        ),
    )
    suggestion: str = Field(
        ..., description="One to two sentences: concrete workout suggestion."
    )
    rationale: list[str] = Field(
        ...,
        description=(
            "Array of 2-4 short string bullets explaining WHY this is the right "
            "session. Each bullet should reference a specific number or recent session. "
            "Must be a JSON array of strings, not a single string."
        ),
    )
    concerns: list[str] = Field(
        default_factory=list,
        description="Array of 0-3 concerns/watch-outs as strings; empty array if none.",
    )
    confidence: Literal["high", "medium", "low"] = Field(
        ...,
        description=(
            "Categorical label — literally 'high', 'medium', or 'low' — based on data "
            "availability and signal quality. NOT a numeric probability."
        ),
    )


class NotableSegment(BaseModel):
    label: str = Field(..., description="Short label, e.g. '800m rep #3' or 'Final mile'.")
    detail: str = Field(..., description="One sentence with the number behind the observation.")


class WorkoutInsight(BaseModel):
    headline: str = Field(
        ..., description="One punchy line summarizing this workout (< 80 chars)."
    )
    takeaway: str = Field(
        ..., description="2–3 sentences: what happened and what it means."
    )
    notable_segments: list[NotableSegment] = Field(
        default_factory=list, description="Up to 3 notable laps/sections."
    )
    vs_history: str | None = Field(
        None,
        description=(
            "One sentence contextualizing this workout versus the user's "
            "90-day history for the same classification, if comparable."
        ),
    )
    flags: list[str] = Field(
        default_factory=list,
        description="Short labels, e.g. 'negative splits', 'elevated HR', 'pace progression'.",
    )


# Convert pydantic schemas to JSON Schema for the LLM providers.
def _pydantic_schema(model: type[BaseModel]) -> dict:
    """Produce a JSON Schema usable by all provider structured-output modes.

    - Inlines ``$defs`` / ``$ref`` (Gemini doesn't follow refs).
    - Recursively enforces ``additionalProperties: false`` on every
      object-typed node AND populates ``required`` with every property
      key. OpenAI's ``json_schema`` strict mode requires both at every
      level; other providers are tolerant of these extra constraints.
    """
    schema = model.model_json_schema()
    defs = schema.pop("$defs", None) or schema.pop("definitions", None) or {}

    # Recursively inline $ref pointers so the schema is fully self-contained.
    def _inline(node):
        if isinstance(node, dict):
            if "$ref" in node and isinstance(node["$ref"], str):
                ref = node["$ref"]
                # "#/$defs/Name" -> "Name"
                name = ref.split("/")[-1]
                target = defs.get(name)
                if target is not None:
                    merged = {k: v for k, v in node.items() if k != "$ref"}
                    merged.update(_inline(target))
                    return merged
            return {k: _inline(v) for k, v in node.items()}
        if isinstance(node, list):
            return [_inline(x) for x in node]
        return node

    schema = _inline(schema)

    # Walk every object-typed node and apply OpenAI-strict constraints.
    def _tighten(node):
        if not isinstance(node, dict):
            return node
        if node.get("type") == "object" and "properties" in node:
            node["additionalProperties"] = False
            # OpenAI strict mode requires every property to appear in
            # `required`. Pydantic marks only truly-required fields here,
            # but all our Optional fields already have explicit defaults,
            # so listing everything is safe.
            node["required"] = list(node["properties"].keys())
            for prop in node["properties"].values():
                _tighten(prop)
        if node.get("type") == "array" and "items" in node:
            _tighten(node["items"])
        return node

    _tighten(schema)
    return schema


# ──────────────────────────────────────────────────────────────────────────
# System prompts
# ──────────────────────────────────────────────────────────────────────────


DAILY_REC_SYSTEM_PROMPT = """You are a personal endurance coach with expertise in \
exercise physiology, periodization, and recovery science. You are advising a single \
athlete who mixes running, cycling, and strength training.

Your job: given this athlete's last 7–28 days of training load, their most recent \
sleep, recovery, and their latest workout, recommend what they should do TODAY.

Principles you care about:
- ACWR (acute:chronic workload ratio) sweet spot is 0.8–1.3. Spikes > 1.5 predict injury.
- Hard days should follow easy days. If the last session was quality, today should not be.
- Sleep debt and low HRV predict poor readiness — tune intensity down, not necessarily volume.
- Monotony > 2.0 means too many similar-load days; suggest variety.
- After a hard session the user needs ≥ 48h before the next quality effort.
- Running classifications: easy | tempo | intervals | race.
- Rides: recovery | endurance | tempo | mixed | race.

Be specific. Reference actual numbers. Avoid generic advice like "listen to your body".

Output a single JSON object matching the schema provided."""

WORKOUT_INSIGHT_SYSTEM_PROMPT = """You are an exercise physiologist reviewing a single \
workout for a personal athlete.

You'll see: the workout itself (distance, time, pace, HR, laps, power if present), \
weather, pre-workout sleep, the user's classification for this workout, and a \
comparison against the last 90 days of similar workouts (percentile ranks).

Your job: deliver a concise, data-driven takeaway. Be specific about lap numbers, \
pace changes, and HR drift. Point out if pacing was disciplined or not.

Output a single JSON object matching the schema provided. Keep the \
headline under 80 characters. Do not invent numbers not in the data."""


# ──────────────────────────────────────────────────────────────────────────
# Cache helpers
# ──────────────────────────────────────────────────────────────────────────


def _hash_inputs(payload: dict | str) -> str:
    if isinstance(payload, dict):
        payload = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _utcnow_naive() -> datetime:
    """UTC “now” as a naive datetime.

    The ``AnalysisCache.expires_at`` / ``created_at`` columns are stored
    naive (no tzinfo), so we deliberately strip tzinfo here for a
    consistent comparison. Using ``datetime.utcnow()`` is deprecated in
    3.12+; ``datetime.now(timezone.utc).replace(tzinfo=None)`` is the
    recommended equivalent.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _cache_get(db: AsyncSession, key: str) -> dict | None:
    row = await db.execute(
        select(AnalysisCache).where(AnalysisCache.query_hash == key)
    )
    hit = row.scalar_one_or_none()
    if not hit:
        return None
    if hit.expires_at and hit.expires_at < _utcnow_naive():
        return None
    try:
        return json.loads(hit.response_text)
    except json.JSONDecodeError:
        return None


async def _cache_put(
    db: AsyncSession,
    key: str,
    query_text: str,
    payload: dict,
    model: str,
    ttl: timedelta | None = None,
) -> None:
    # Upsert: delete existing row with this hash, insert fresh.
    existing = await db.execute(
        select(AnalysisCache).where(AnalysisCache.query_hash == key)
    )
    e = existing.scalar_one_or_none()
    now = _utcnow_naive()
    expires = (now + ttl) if ttl else None
    if e:
        e.response_text = json.dumps(payload)
        e.model = model
        e.query_text = query_text
        e.expires_at = expires
        e.created_at = now
    else:
        db.add(
            AnalysisCache(
                query_hash=key,
                query_text=query_text,
                response_text=json.dumps(payload),
                model=model,
                expires_at=expires,
            )
        )
    await db.commit()


# ──────────────────────────────────────────────────────────────────────────
# LLM call with structured schema + fallback chain
# ──────────────────────────────────────────────────────────────────────────


def _maybe_unwrap(raw: dict, expected_keys: set[str]) -> dict:
    """Some models wrap the response in a single top-level key (e.g.
    ``{"recommendation": {...}}``). If the top-level dict is a single
    non-expected key whose value is a dict, unwrap it. If multiple
    top-level keys exist but most of them are expected and one is a
    foreign wrapper-dict, we also collapse that wrapper into the root.
    """
    if not isinstance(raw, dict):
        return raw

    if (
        len(raw) == 1
        and next(iter(raw.keys())) not in expected_keys
        and isinstance(next(iter(raw.values())), dict)
    ):
        return next(iter(raw.values()))

    # Mixed shape: {recommendation: {...inner fields...}, confidence: "high"}
    # — merge inner wrapper into root without clobbering existing keys.
    wrappers = [
        k for k, v in raw.items()
        if k not in expected_keys and isinstance(v, dict)
    ]
    if wrappers and any(k in expected_keys for k in raw.keys()):
        merged = {k: v for k, v in raw.items() if k in expected_keys}
        for w in wrappers:
            for k, v in raw[w].items():
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
    """Try each model in `model_chain`, returning (parsed_model, model_used).

    Raises the last exception if all fail.
    """
    schema = _pydantic_schema(response_model)
    expected_keys = set((schema.get("properties") or {}).keys())
    last_exc: Exception | None = None

    for model_key in model_chain:
        provider: LLMProvider | None = None
        try:
            provider = get_provider(model_key)
        except Exception as e:
            logger.warning("LLM provider init failed for %s: %s", model_key, e)
            last_exc = e
            continue

        try:
            raw = await provider.query_structured(
                system_prompt=system_prompt,
                user_message=user_message,
                schema=schema,
                schema_name=schema_name,
            )
            logger.debug("LLM raw response from %s: %s", model_key, json.dumps(raw)[:500])
            raw = _maybe_unwrap(raw, expected_keys)
            try:
                parsed = response_model.model_validate(raw)
                return parsed, model_key
            except ValidationError as ve:
                # One self-correcting retry.
                logger.info("Schema validation failed, retrying with correction: %s", ve)
                correction = (
                    f"{user_message}\n\nYour previous response did not match the schema. "
                    f"Errors: {ve.errors()}\n"
                    "Do NOT wrap the response in any outer key. The top-level JSON object "
                    f"MUST have exactly these keys: {sorted(expected_keys)}. "
                    "Return ONLY valid JSON matching the schema."
                )
                raw2 = await provider.query_structured(
                    system_prompt=system_prompt,
                    user_message=correction,
                    schema=schema,
                    schema_name=schema_name,
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


# ──────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class DailyRecommendationResult:
    recommendation: DailyRecommendation
    inputs: dict
    model: str
    generated_at: str
    cached: bool

    def to_dict(self) -> dict:
        return {
            "recommendation": self.recommendation.model_dump(),
            "inputs": self.inputs,
            "model": self.model,
            "generated_at": self.generated_at,
            "cached": self.cached,
        }


@dataclass
class WorkoutInsightResult:
    activity_id: int
    workout: dict
    insight: WorkoutInsight
    model: str
    generated_at: str
    cached: bool

    def to_dict(self) -> dict:
        return {
            "activity_id": self.activity_id,
            "workout": self.workout,
            "insight": self.insight.model_dump(),
            "model": self.model,
            "generated_at": self.generated_at,
            "cached": self.cached,
        }


async def get_daily_recommendation(
    db: AsyncSession,
    model: str | None = None,
    refresh: bool = False,
) -> DailyRecommendationResult:
    snapshot = await training_metrics.get_full_snapshot(db)

    # Cache key: YYYY-MM-DD + requested-model + hash of the inputs that matter.
    # We deliberately exclude the minute-by-minute activity list so the cache
    # remains valid across a day; but include the 7d load numbers so a new
    # workout today invalidates cache. The *requested* model (primary, before
    # fallback) is part of the key so explicit model overrides don't return
    # output generated by a different model.
    signal = {
        "date": snapshot["today"],
        "training_load": snapshot["training_load"],
        "sleep": snapshot["sleep"],
        "recovery": snapshot["recovery"],
        "latest_id": (snapshot.get("latest_workout") or {}).get("id"),
    }
    inputs_hash = _hash_inputs(signal)
    requested_model = model or settings.llm.dashboard_model
    cache_key = f"daily_rec:{snapshot['today']}:{requested_model}:{inputs_hash}"

    if not refresh:
        hit = await _cache_get(db, cache_key)
        if hit:
            return DailyRecommendationResult(
                recommendation=DailyRecommendation.model_validate(hit["recommendation"]),
                inputs=hit["inputs"],
                model=hit["model"],
                generated_at=hit["generated_at"],
                cached=True,
            )

    user_message = (
        "Here is the athlete's current state as JSON.\n\n```json\n"
        + json.dumps(snapshot, indent=2, default=str)
        + "\n```\n\n"
        "Based on this, recommend what they should do today."
    )

    parsed, model_used = await _call_llm_structured(
        system_prompt=DAILY_REC_SYSTEM_PROMPT,
        user_message=user_message,
        response_model=DailyRecommendation,
        model_chain=_build_model_chain(model),
        schema_name="daily_recommendation",
    )

    generated_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "recommendation": parsed.model_dump(),
        "inputs": snapshot,
        "model": model_used,
        "generated_at": generated_at,
    }
    await _cache_put(
        db,
        cache_key,
        query_text=f"daily_rec for {snapshot['today']}",
        payload=payload,
        model=model_used,
        ttl=timedelta(hours=24),
    )

    return DailyRecommendationResult(
        recommendation=parsed,
        inputs=snapshot,
        model=model_used,
        generated_at=generated_at,
        cached=False,
    )


async def get_latest_workout_insight(
    db: AsyncSession,
    activity_id: int | None = None,
    model: str | None = None,
    refresh: bool = False,
) -> WorkoutInsightResult | None:
    snapshot = await training_metrics.get_latest_workout_snapshot(db, activity_id)
    if not snapshot:
        return None

    requested_model = model or settings.llm.dashboard_model
    cache_key = f"workout_insight:{snapshot['id']}:{requested_model}"

    if not refresh:
        hit = await _cache_get(db, cache_key)
        if hit:
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

    parsed, model_used = await _call_llm_structured(
        system_prompt=WORKOUT_INSIGHT_SYSTEM_PROMPT,
        user_message=user_message,
        response_model=WorkoutInsight,
        model_chain=_build_model_chain(model),
        schema_name="workout_insight",
    )

    generated_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "workout": snapshot,
        "insight": parsed.model_dump(),
        "model": model_used,
        "generated_at": generated_at,
    }
    await _cache_put(
        db,
        cache_key,
        query_text=f"workout_insight for activity {snapshot['id']}",
        payload=payload,
        model=model_used,
        ttl=None,  # activity-level, stable until refresh
    )

    return WorkoutInsightResult(
        activity_id=snapshot["id"],
        workout=snapshot,
        insight=parsed,
        model=model_used,
        generated_at=generated_at,
        cached=False,
    )
