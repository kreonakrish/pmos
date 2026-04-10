"""
Health check endpoint.

GET /health   — lightweight liveness check (always fast)
GET /metrics  — Prometheus metrics exposition (handled by middleware in main.py)
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Request

from app.utils.logger import StructuredLogger

router = APIRouter(tags=["ops"])
logger = StructuredLogger(layer="router")


@router.get("/health", status_code=200)
async def health(request: Request) -> dict:
    """
    Returns liveness status plus connectivity checks for MySQL and Redis.
    Does not fail fast — reports each dependency's status individually so
    the orchestrator health aggregator can surface partial degradation.
    """
    start = time.perf_counter()

    # MySQL probe
    mysql_ok = False
    try:
        # Lightweight: fetch_recent_scores with impossible agent_id just to
        # test connectivity; we catch any exception.
        mysql = request.app.state.mysql
        await mysql.fetch_recent_scores(-1, "_health", 1)
        mysql_ok = True
    except Exception as exc:
        logger.warning("MySQL health probe failed", error=str(exc))

    # Redis probe
    redis_ok = False
    try:
        redis = request.app.state.redis
        redis_ok = await redis.ping()
    except Exception as exc:
        logger.warning("Redis health probe failed", error=str(exc))

    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)

    return {
        "service": "scoring",
        "status": "ok" if (mysql_ok and redis_ok) else "degraded",
        "dependencies": {
            "mysql": "ok" if mysql_ok else "unavailable",
            "redis": "ok" if redis_ok else "unavailable",
        },
        "duration_ms": elapsed_ms,
    }
