from fastapi import APIRouter, Request

from app.models.rag import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """Return service health including upstream adapter statuses."""
    state = request.app.state
    checks: dict[str, bool] = {}

    # Vector store
    try:
        checks["vector_store"] = await state.vector_store.health_check()
    except Exception:
        checks["vector_store"] = False

    # MySQL
    try:
        checks["mysql"] = await state.mysql_adapter.health_check()
    except Exception:
        checks["mysql"] = False

    # Redis
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(state.settings.redis_url)
        await r.ping()
        await r.aclose()
        checks["redis"] = True
    except Exception:
        checks["redis"] = False

    overall = "ok" if all(checks.values()) else "degraded"
    return HealthResponse(status=overall, checks=checks)
