"""
Scoring service — FastAPI application entry point.

Startup sequence:
  1. Validate configuration (Pydantic fails fast on bad env)
  2. Create shared adapter instances (MySQL pool, Redis client)
  3. Compose service layer objects
  4. Register routes
  5. Mount Prometheus /metrics endpoint
  6. Start RL engine background consumer task
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from prometheus_client import make_asgi_app

from app.adapters.mysql_adapter import MySQLAdapter
from app.adapters.redis_adapter import RedisAdapter
from app.config import settings
from app.routes.health import router as health_router
from app.routes.scoring import router as scoring_router
from app.services.band_engine import BandEngine
from app.services.rl_engine import RLEngine
from app.services.score_engine import ScoreEngine
from app.services.weight_store import WeightStore
from app.utils.logger import StructuredLogger

logger = StructuredLogger(layer="main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # ── Startup ───────────────────────────────────────────────────────────────
    logger.info(
        "Scoring service starting",
        port=settings.scoring_port,
        service=settings.service_name,
    )

    # Adapters
    mysql = MySQLAdapter()
    redis = RedisAdapter()

    # Service layer
    weight_store = WeightStore(mysql)
    score_engine = ScoreEngine(weight_store)
    band_engine = BandEngine(mysql)
    rl_engine = RLEngine(mysql, redis, weight_store)

    # Attach to app state for route access
    app.state.mysql = mysql
    app.state.redis = redis
    app.state.weight_store = weight_store
    app.state.score_engine = score_engine
    app.state.band_engine = band_engine
    app.state.rl_engine = rl_engine

    # Start RL background consumer
    rl_task = asyncio.create_task(rl_engine.consume_feedback_stream())

    logger.info("Scoring service ready")

    yield  # ← service is running

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("Scoring service shutting down")
    rl_engine.stop()
    rl_task.cancel()
    try:
        await rl_task
    except asyncio.CancelledError:
        pass
    await redis.close()
    logger.info("Scoring service stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="PMOS Scoring Service",
        version="1.0.0",
        description="6-factor weighted scoring with adaptive bands and RL weight updates.",
        lifespan=lifespan,
    )

    # Routers
    app.include_router(health_router)
    app.include_router(scoring_router)

    # Prometheus metrics on /metrics
    metrics_app = make_asgi_app()
    app.mount("/metrics", metrics_app)

    return app


app = create_app()
