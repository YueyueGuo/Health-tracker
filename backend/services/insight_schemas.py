"""Structured LLM response schemas and provider-compatible JSON Schema prep."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


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
            "Categorical label -- literally 'high', 'medium', or 'low' -- based on data "
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
        ..., description="2-3 sentences: what happened and what it means."
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


def _pydantic_schema(model: type[BaseModel]) -> dict:
    """Produce a JSON Schema usable by all provider structured-output modes."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", None) or schema.pop("definitions", None) or {}

    def _inline(node):
        if isinstance(node, dict):
            if "$ref" in node and isinstance(node["$ref"], str):
                name = node["$ref"].split("/")[-1]
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

    def _tighten(node):
        if not isinstance(node, dict):
            return node
        if node.get("type") == "object" and "properties" in node:
            node["additionalProperties"] = False
            node["required"] = list(node["properties"].keys())
            for prop in node["properties"].values():
                _tighten(prop)
        if node.get("type") == "array" and "items" in node:
            _tighten(node["items"])
        return node

    _tighten(schema)
    return schema
