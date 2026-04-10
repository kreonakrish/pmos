"""PMOS Meta-Assembly Service — FastAPI entry point."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, Response
import time
import uuid

from app.config import settings
from app.routes import meta, health
from app.utils.logger import get_logger
from app.utils.metrics import REQUEST_TOTAL, REQUEST_DURATION

logger = get_logger(layer="router")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup / shutdown lifecycle for adapter connections."""
    logger.info(
        "service_starting",
        port=settings.meta_assembly_port,
        trace_id="startup",
    )
    yield
    # Shutdown: close adapter connections
    from app.adapters.neo4j_adapter import close_driver
    from app.adapters.redis_adapter import close_redis

    await close_driver()
    await close_redis()
    logger.info("service_stopped", trace_id="shutdown")


app = FastAPI(
    title="PMOS Meta-Assembly Service",
    description="Self-extending capability generation for the PMOS platform.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def observability_middleware(request: Request, call_next) -> Response:
    """Inject trace_id, measure duration, record Prometheus metrics."""
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    request.state.trace_id = trace_id

    start = time.monotonic()
    response: Response = await call_next(request)
    duration = time.monotonic() - start

    REQUEST_TOTAL.labels(
        method=request.method,
        path=request.url.path,
        status=response.status_code,
    ).inc()
    REQUEST_DURATION.labels(
        method=request.method,
        path=request.url.path,
    ).observe(duration)

    response.headers["x-request-id"] = trace_id
    return response


app.include_router(health.router)
app.include_router(meta.router, prefix="/v1/meta")
