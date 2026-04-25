"""FastAPI entry point for the Translator service."""

from __future__ import annotations

import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

# The translator imports ``shared.translator_contracts`` from the monorepo's
# top-level ``shared/`` directory. Two layouts exist:
#   * Local dev:  /<repo>/services/translator/app/main.py — repo root at parents[3]
#   * Docker:     /app/app/main.py — Dockerfile COPYs shared/ to /app/shared,
#                 so the package is importable directly from /app (parents[1]).
# Add both possible parents that contain a ``shared`` directory.
_here = Path(__file__).resolve()
for _candidate in (_here.parents[1], _here.parents[3] if len(_here.parents) > 3 else None):
    if _candidate and (_candidate / "shared").is_dir() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

from app.adapters.embedder import Embedder  # noqa: E402
from app.adapters.llm_adapter import LLMAdapter  # noqa: E402
from app.adapters.neo4j_adapter import build_ontology_adapter  # noqa: E402
from app.adapters.qdrant_adapter import QdrantAdapter  # noqa: E402
from app.config import settings  # noqa: E402
from app.routes import health as health_router  # noqa: E402
from app.routes import translate as translate_router  # noqa: E402
from app.services.pipeline import TranslatorPipeline  # noqa: E402
from app.utils.logger import logger  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info(
        "Translator service starting",
        layer="main",
        port=settings.translator_port,
    )

    # Adapters
    neo4j = build_ontology_adapter()
    qdrant = QdrantAdapter()
    llm = LLMAdapter()
    embedder = Embedder()

    await neo4j.connect()

    # Match the Qdrant collection's vector size to whatever model the embedder
    # actually loaded. Falls back to the contract default when the model is
    # unavailable. ensure_collection() recreates the collection if the dim
    # changed since the last boot.
    detected_dim = embedder.dimension()
    if detected_dim:
        logger.info(
            "Embedder dimension detected",
            layer="main",
            model=embedder._model_name,
            dimension=detected_dim,
        )
    await qdrant.ensure_collection(dimension=detected_dim)

    pipeline = TranslatorPipeline(
        neo4j=neo4j,
        qdrant=qdrant,
        llm=llm,
        embedder=embedder,
    )

    app.state.neo4j = neo4j
    app.state.qdrant = qdrant
    app.state.llm = llm
    app.state.embedder = embedder
    app.state.pipeline = pipeline

    logger.info("Translator service ready", layer="main")
    yield

    logger.info("Translator service shutting down", layer="main")
    await neo4j.close()


app = FastAPI(
    title="PMOS Translator Service",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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


app.include_router(health_router.router)
app.include_router(translate_router.router)
