"""FastAPI entry point for the Orchestrator service."""

from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.adapters.agent_mgmt_adapter import AgentMgmtAdapter
from app.adapters.llm_adapter import LLMAdapter
from app.adapters.memory_adapter import MemoryAdapter
from app.adapters.meta_adapter import MetaAdapter
from app.adapters.neo4j_adapter import Neo4jAdapter
from app.adapters.rag_adapter import RAGAdapter
from app.adapters.redis_adapter import RedisAdapter
from app.adapters.scoring_adapter import ScoringAdapter
from app.config import settings
from app.routes import catalog as catalog_router
from app.routes import conversations as conv_router
from app.routes import governance as gov_router
from app.routes import health as health_router
from app.routes import ml_insights as ml_router
from app.routes import orchestrator as orch_router
from app.routes import sandbox as sandbox_router
from app.services.pipeline import PipelineService
from app.utils.logger import logger
from app.utils.telemetry import REQUEST_DURATION, REQUEST_TOTAL


# ---------------------------------------------------------------------------
# Application lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start backing connections and background consumers on startup."""
    logger.info("Orchestrator service starting", layer="main", port=settings.orchestrator_port)

    # Adapters
    neo4j = Neo4jAdapter()
    redis = RedisAdapter()
    await neo4j.connect()
    await redis.connect()

    llm = LLMAdapter()
    memory = MemoryAdapter()
    scoring = ScoringAdapter()
    rag = RAGAdapter()
    meta = MetaAdapter()

    pipeline = PipelineService(
        neo4j=neo4j,
        redis=redis,
        llm=llm,
        memory=memory,
        scoring=scoring,
        rag=rag,
        meta=meta,
    )

    agent_mgmt = AgentMgmtAdapter()

    # Attach to app state
    app.state.neo4j = neo4j
    app.state.redis = redis
    app.state.pipeline = pipeline
    app.state.agent_mgmt = agent_mgmt
    app.state.memory = memory

    # Background consumer: scoring:feedback
    consumer_task = asyncio.create_task(
        redis.consume_scoring_feedback(
            group="orchestrator-group",
            consumer=f"orchestrator-{uuid.uuid4().hex[:8]}",
            handler=pipeline.handle_scoring_feedback,
        )
    )

    # Recovery: check for interrupted pipelines
    await _recover_stale_pipelines(neo4j, pipeline)

    logger.info("Orchestrator service ready", layer="main")

    yield

    # Shutdown
    logger.info("Orchestrator service shutting down", layer="main")
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass
    await neo4j.close()
    await redis.close()


# ---------------------------------------------------------------------------
# Pipeline recovery on startup
# ---------------------------------------------------------------------------


async def _recover_stale_pipelines(neo4j: "Neo4jAdapter", pipeline: "PipelineService") -> None:
    """On startup, find and handle interrupted pipeline executions."""
    try:
        stale_graphs = await neo4j.run_query(
            """
            MATCH (g:TaskGraph)
            WHERE g.status = 'EXECUTING'
            RETURN g.graph_id as graph_id, g.conversation_id as conversation_id,
                   g.session_id as session_id, g.user_request as user_request
            """,
            {},
        )
    except Exception as exc:
        logger.warning(
            "Stale pipeline recovery query failed (non-fatal)",
            layer="main",
            error=str(exc),
        )
        return

    if not stale_graphs:
        logger.info("No stale pipelines found during recovery", layer="main")
        return

    logger.warning(
        f"Found {len(stale_graphs)} stale pipeline(s) to recover",
        layer="main",
        stale_count=len(stale_graphs),
    )

    for graph in stale_graphs:
        graph_id = graph["graph_id"]

        try:
            # Mark RUNNING nodes as FAILED (they were mid-execution when crash happened)
            await neo4j.run_query(
                """
                MATCH (n:TaskNode {graph_id: $graph_id})
                WHERE n.status = 'RUNNING'
                SET n.status = 'FAILED', n.updated_at = datetime()
                """,
                {"graph_id": graph_id},
            )

            # Check if there are PENDING nodes that can still be executed
            pending = await neo4j.run_query(
                """
                MATCH (n:TaskNode {graph_id: $graph_id})
                WHERE n.status = 'PENDING'
                RETURN count(n) as cnt
                """,
                {"graph_id": graph_id},
            )

            pending_count = pending[0]["cnt"] if pending else 0

            if pending_count == 0:
                # All nodes were either completed or failed
                await neo4j.run_query(
                    """
                    MATCH (g:TaskGraph {graph_id: $graph_id})
                    SET g.status = 'COMPLETED_PARTIAL', g.updated_at = datetime(),
                        g.recovery_note = 'Recovered after crash - some tasks may have failed'
                    """,
                    {"graph_id": graph_id},
                )
                logger.info(
                    f"Marked stale graph {graph_id} as COMPLETED_PARTIAL",
                    layer="main",
                    graph_id=graph_id,
                )
            else:
                # Has pending work — mark graph as INTERRUPTED
                await neo4j.run_query(
                    """
                    MATCH (g:TaskGraph {graph_id: $graph_id})
                    SET g.status = 'INTERRUPTED', g.updated_at = datetime(),
                        g.recovery_note = 'Interrupted by crash - pending tasks remain'
                    """,
                    {"graph_id": graph_id},
                )
                logger.warning(
                    f"Marked stale graph {graph_id} as INTERRUPTED ({pending_count} pending nodes)",
                    layer="main",
                    graph_id=graph_id,
                    pending_count=pending_count,
                )
        except Exception as exc:
            logger.error(
                f"Failed to recover stale graph {graph_id}",
                layer="main",
                graph_id=graph_id,
                error=str(exc),
            )


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

app = FastAPI(
    title="PMOS Orchestrator Service",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Request logging middleware
# ---------------------------------------------------------------------------

@app.middleware("http")
async def request_logging_middleware(request: Request, call_next) -> Response:
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    span_id = str(uuid.uuid4())
    start = time.monotonic()

    logger.info(
        "Incoming request",
        layer="router",
        method=request.method,
        path=request.url.path,
        trace_id=trace_id,
        span_id=span_id,
    )

    response: Response = await call_next(request)

    elapsed = time.monotonic() - start
    REQUEST_DURATION.labels(method=request.method, path=request.url.path).observe(elapsed)
    REQUEST_TOTAL.labels(
        method=request.method, path=request.url.path, status=str(response.status_code)
    ).inc()

    logger.info(
        "Request completed",
        layer="router",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=int(elapsed * 1000),
        trace_id=trace_id,
        span_id=span_id,
    )
    return response


# ---------------------------------------------------------------------------
# Register routers
# ---------------------------------------------------------------------------

app.include_router(health_router.router)
app.include_router(orch_router.router)
app.include_router(conv_router.router)
app.include_router(sandbox_router.router)
app.include_router(gov_router.router)
app.include_router(ml_router.router)
app.include_router(catalog_router.router)
