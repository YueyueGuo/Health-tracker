"""HTTP ingestion endpoints for Apple Health (Health Auto Export).

Two endpoints, both gated by a shared-secret token (``X-Apple-Health-Token``):

* ``POST /workouts`` — accepts an HAE batch, returns per-workout
  results.
* ``POST /ping``     — no-op auth check for HAE configuration.

The token is compared in constant time via ``hmac.compare_digest``.
A blank env token returns 503 (misconfig signal) rather than 401, so
the operator can tell the difference between "I forgot to set the
secret" and "the iOS app is sending the wrong one".
"""
from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database import get_db
from backend.services.apple_health_ingest import ingest_workouts
from backend.services.apple_health_parser import HAEBatch

logger = logging.getLogger(__name__)
router = APIRouter()


# Boot-time misconfig signal: if the server-side ingest_token is blank,
# every POST to this router will 503 before the body is parsed. Surface
# that loudly at import so it's a single grep in Railway logs at deploy
# time rather than a per-request mystery.
if not settings.apple_health.ingest_token:
    logger.warning(
        "apple_health.ingest_token is blank — POSTs to "
        "/api/ingest/apple-health/* will return 503 until "
        "APPLE_HEALTH_INGEST_TOKEN is set"
    )


def verify_apple_health_token(
    x_apple_health_token: str | None = Header(default=None),
) -> None:
    """FastAPI dependency: validates the shared-secret header.

    * 503 if the server-side token is blank (misconfig).
    * 401 if the header is missing or doesn't match (constant-time).
    """
    expected = settings.apple_health.ingest_token
    if not expected:
        # Fail loud rather than silently accepting any token, so a
        # broken deploy doesn't accept un-authenticated writes.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Apple Health ingest is not configured on the server",
        )
    if not x_apple_health_token or not hmac.compare_digest(
        x_apple_health_token, expected
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing X-Apple-Health-Token",
        )


@router.post("/workouts")
async def ingest_apple_health_workouts(
    batch: HAEBatch,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_apple_health_token),
):
    """Ingest an HAE batch of workouts. Returns one result per workout."""
    # Batch-receipt log — confirms HAE is actually reaching us and gives
    # a grep-friendly handle on the first workout for log spelunking.
    count = len(batch.data.workouts)
    first = batch.data.workouts[0] if count else None
    first_id = getattr(first, "id", None) if first is not None else None
    first_start = getattr(first, "start", None) if first is not None else None
    logger.info(
        "apple_health.ingest received workouts=%d first_id=%s first_start=%s",
        count,
        first_id,
        first_start,
    )

    results = await ingest_workouts(db, batch)

    # Summary log — tallies by status so a 200-OK-with-all-errors batch
    # is obvious from a single grep instead of a per-workout dive.
    created = sum(1 for r in results if r.get("status") == "created")
    updated = sum(1 for r in results if r.get("status") == "updated")
    errors = sum(1 for r in results if r.get("status") == "error")
    logger.info(
        "apple_health.ingest summary created=%d updated=%d errors=%d",
        created,
        updated,
        errors,
    )

    return {"results": results}


@router.post("/ping")
async def ping(_: None = Depends(verify_apple_health_token)):
    """Lightweight auth check — useful when wiring HAE for the first time."""
    return {"ok": True}
