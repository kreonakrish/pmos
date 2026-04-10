"""FastAPI application entry point for the memory service."""
from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Histogram,
    generate_latest,
)

from app.config import settings
from app.routes.health import router as health_router
from app.routes.memory import router as memory_router
from app.services.distillation import DistillationService
from app.services.stream_consumer import MemoryWriteConsumer
from app.utils.logger import get_logger
from app.utils.telemetry import setup_telemetry

logger = get_logger()

# Prometheus metrics
REQUEST_TOTAL = Counter(
    "request_total", "Total HTTP requests", ["method", "path", "status"]
)
REQUEST_DURATION = Histogram(
    "request_duration_seconds", "HTTP request duration", ["method", "path"]
)

_distillation_service: DistillationService | None = None
_stream_consumer: MemoryWriteConsumer | None = None
_background_tasks: list[asyncio.Task] = []


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _distillation_service, _stream_consumer

    logger.info(
        "Memory service starting",
        layer="main",
        port=settings.memory_port,
        service=settings.service_name,
    )

    setup_telemetry(settings.service_name)

    _distillation_service = DistillationService()
    _stream_consumer = MemoryWriteConsumer()

    # Launch background tasks
    distil_task = asyncio.create_task(_distillation_service.start_loop(), name="distillation-loop")
    consumer_task = asyncio.create_task(_stream_consumer.consume_memory_writes(), name="stream-consumer")
    _background_tasks.extend([distil_task, consumer_task])

    logger.info("Background tasks started", layer="main")

    yield

    # Graceful shutdown
    logger.info("Memory service shutting down", layer="main")
    if _distillation_service:
        _distillation_service.stop()
    if _stream_consumer:
        _stream_consumer.stop()

    for task in _background_tasks:
        task.cancel()
    await asyncio.gather(*_background_tasks, return_exceptions=True)
    logger.info("Memory service stopped", layer="main")


def create_app() -> FastAPI:
    app = FastAPI(
        title="PMOS Memory Service",
        description="4-tier memory architecture: SHORT_TERM, LONG_TERM, REASONING, EPISODIC",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.include_router(health_router)
    app.include_router(memory_router)

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.middleware("http")
    async def observability_middleware(request: Request, call_next):
        start = time.time()
        trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        response: Response = await call_next(request)
        duration = time.time() - start

        REQUEST_TOTAL.labels(
            method=request.method,
            path=request.url.path,
            status=response.status_code,
        ).inc()
        REQUEST_DURATION.labels(
            method=request.method,
            path=request.url.path,
        ).observe(duration)

        logger.info(
            "HTTP request completed",
            layer="middleware",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round(duration * 1000),
            trace_id=trace_id,
        )
        return response

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        logger.error(
            "Unhandled exception",
            layer="main",
            error=str(exc),
            path=request.url.path,
            trace_id=trace_id,
        )
        return JSONResponse(
            status_code=500,
            content={"error": str(exc), "code": "INTERNAL_ERROR", "trace_id": trace_id},
        )

    return app


app = create_app()
