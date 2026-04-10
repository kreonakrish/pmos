"""Health and metrics endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.models.pipeline import HealthResponse
from app.utils.telemetry import get_metrics

router = APIRouter(tags=["ops"])


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    neo4j = request.app.state.neo4j
    redis = request.app.state.redis

    neo4j_ok = await neo4j.health_check()
    redis_ok = await redis.health_check()

    return HealthResponse(
        status="ok" if (neo4j_ok and redis_ok) else "degraded",
        neo4j=neo4j_ok,
        redis=redis_ok,
    )


@router.get("/metrics")
async def metrics() -> Response:
    data, content_type = get_metrics()
    return Response(content=data, media_type=content_type)
