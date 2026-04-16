from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.services.analysis import AnalysisEngine
from backend.services.llm_providers import list_available_models

router = APIRouter()


class ChatRequest(BaseModel):
    question: str
    model: str | None = None


@router.post("/ask")
async def ask_question(req: ChatRequest, db: AsyncSession = Depends(get_db)):
    """Ask a free-form question about your health data."""
    engine = AnalysisEngine(db)
    result = await engine.query(question=req.question, model=req.model)
    return result.to_dict()


@router.get("/daily-briefing")
async def daily_briefing(
    model: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Get today's training/recovery briefing."""
    engine = AnalysisEngine(db)
    result = await engine.daily_briefing(model=model)
    return result.to_dict()


@router.get("/workout/{activity_id}")
async def workout_analysis(
    activity_id: int,
    model: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Get deep analysis of a specific workout."""
    engine = AnalysisEngine(db)
    result = await engine.workout_analysis(activity_id=activity_id, model=model)
    return result.to_dict()


@router.get("/models")
async def available_models():
    """List available LLM models."""
    return {"models": list_available_models()}
