"""Health endpoint for the Translator service."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.models.translation import HealthResponse

router = APIRouter(tags=["ops"])


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    neo4j_ok = await request.app.state.neo4j.health_check()
    qdrant_ok = await request.app.state.qdrant.health_check()
    llm_ok = await request.app.state.llm.health_check()
    overall = "UP" if (neo4j_ok and qdrant_ok and llm_ok) else "DEGRADED"
    return HealthResponse(
        status=overall,
        service="translator",
        neo4j=neo4j_ok,
        qdrant=qdrant_ok,
        llm=llm_ok,
    )
