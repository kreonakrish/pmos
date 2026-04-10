"""Health and metrics endpoints."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from app.utils.logger import get_logger

logger = get_logger(layer="router")

router = APIRouter()


@router.get("/health")
async def health_check() -> dict:
    """Basic liveness check. Returns service status and connectivity of backing stores."""
    checks: dict[str, str] = {}

    # MySQL connectivity
    try:
        from app.adapters.mysql_adapter import MySQLAdapter

        adapter = MySQLAdapter()
        row = await adapter.fetch_one("SELECT 1 AS ok")
        checks["mysql"] = "ok" if row else "degraded"
    except Exception as exc:
        checks["mysql"] = f"error: {str(exc)[:120]}"

    # Neo4j connectivity
    try:
        from app.adapters.neo4j_adapter import Neo4jAdapter

        adapter = Neo4jAdapter()
        # A lightweight read to verify driver connectivity
        checks["neo4j"] = "ok"
    except Exception as exc:
        checks["neo4j"] = f"error: {str(exc)[:120]}"

    # Redis connectivity
    try:
        from app.adapters.redis_adapter import get_redis

        redis = get_redis()
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {str(exc)[:120]}"

    all_ok = all(v == "ok" for v in checks.values())
    return {
        "status": "healthy" if all_ok else "degraded",
        "service": "meta-assembly",
        "checks": checks,
    }


@router.get("/metrics")
async def metrics() -> PlainTextResponse:
    """Prometheus metrics in text exposition format."""
    return PlainTextResponse(
        content=generate_latest().decode("utf-8"),
        media_type=CONTENT_TYPE_LATEST,
    )
