"""Health check route."""
from __future__ import annotations

import time

from fastapi import APIRouter

from app.adapters.mysql_adapter import get_mysql_adapter
from app.adapters.redis_adapter import get_redis_adapter
from app.models.memory import HealthResponse
from app.utils.logger import get_logger

logger = get_logger()
router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["health"])
async def health_check() -> HealthResponse:
    start = time.time()
    checks: dict[str, str] = {}

    # Redis ping
    try:
        redis = get_redis_adapter()
        client = await redis._get_client()
        await client.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {exc}"

    # MySQL ping
    try:
        mysql = get_mysql_adapter()
        await mysql.execute("SELECT 1", fetch_one=True)
        checks["mysql"] = "ok"
    except Exception as exc:
        checks["mysql"] = f"error: {exc}"

    overall = "ok" if all(v == "ok" for v in checks.values()) else "degraded"

    logger.info(
        "Health check",
        layer="router",
        status=overall,
        duration_ms=round((time.time() - start) * 1000),
    )

    return HealthResponse(service="memory", status=overall, checks=checks)
