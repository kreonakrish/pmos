"""Memory CRUD and prompt-assembly routes."""
from __future__ import annotations

import time
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from app.models.memory import (
    MemoryRetrieveResponse,
    MemoryTier,
    MemoryWriteRequest,
    MemoryWriteResponse,
    PromptAssembleRequest,
    PromptAssembleResponse,
    PromptSourceCounts,
)
from app.services.episodic import EpisodicMemoryService
from app.services.long_term import LongTermMemoryService
from app.services.prompt_assembler import PromptAssembler
from app.services.reasoning import ReasoningMemoryService
from app.services.short_term import ShortTermMemoryService
from app.adapters.mysql_adapter import get_mysql_adapter
from app.utils.logger import get_logger, new_span_id
from prometheus_client import Counter, Histogram

logger = get_logger()
router = APIRouter(prefix="/v1/memory", tags=["memory"])

# Prometheus counters
MEMORY_HITS = Counter("memory_hits", "Memory tier hit count", ["tier"])

# Service instances (singleton pattern via module-level)
_short_term = ShortTermMemoryService()
_long_term = LongTermMemoryService()
_reasoning = ReasoningMemoryService()
_episodic = EpisodicMemoryService()
_assembler = PromptAssembler(
    short_term=_short_term,
    long_term=_long_term,
    reasoning=_reasoning,
    episodic=_episodic,
)


@router.post("/write", response_model=MemoryWriteResponse)
async def write_memory(body: MemoryWriteRequest, request: Request) -> MemoryWriteResponse:
    span_id = new_span_id()
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    start = time.time()

    logger.info(
        "Memory write request",
        layer="router",
        agent_id=body.agent_id,
        tier=body.tier.value,
        trace_id=trace_id,
        span_id=span_id,
    )

    try:
        memory_id: str
        if body.tier == MemoryTier.SHORT_TERM:
            memory_id = await _short_term.write(body.agent_id, body.content, body.metadata)
        elif body.tier == MemoryTier.LONG_TERM:
            memory_id = await _long_term.store(body.agent_id, body.content, body.metadata)
        elif body.tier == MemoryTier.REASONING:
            memory_id = await _reasoning.store(body.agent_id, body.content, body.metadata)
        elif body.tier == MemoryTier.EPISODIC:
            episode_data = {"content": body.content, **body.metadata}
            memory_id = await _episodic.store_episode(body.agent_id, episode_data)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown tier: {body.tier}")

        MEMORY_HITS.labels(tier=body.tier.value).inc()

        logger.info(
            "Memory write success",
            layer="router",
            agent_id=body.agent_id,
            tier=body.tier.value,
            memory_id=memory_id,
            duration_ms=round((time.time() - start) * 1000),
            trace_id=trace_id,
            span_id=span_id,
        )

        return MemoryWriteResponse(memory_id=memory_id, tier=body.tier, trace_id=trace_id)

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "Memory write failed",
            layer="router",
            agent_id=body.agent_id,
            tier=body.tier.value,
            error=str(exc),
            trace_id=trace_id,
            span_id=span_id,
        )
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/entries")
async def list_entries(
    request: Request,
    agent_id: int = Query(..., description="Agent ID"),
    tier: MemoryTier = Query(..., description="Memory tier"),
    limit: int = Query(50, ge=1, le=500, description="Max rows"),
) -> dict:
    """Browse recent memory entries for an agent/tier without semantic search.

    Reads straight from the backing store (Redis for SHORT_TERM, MySQL for the
    other tiers) ordered by most recent. Use /retrieve for semantic search.
    """
    span_id = new_span_id()
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    start = time.time()

    try:
        results: list = []
        if tier == MemoryTier.SHORT_TERM:
            results = await _short_term.read_all(agent_id)
            results = results[-limit:] if len(results) > limit else results
        elif tier == MemoryTier.EPISODIC:
            mysql = get_mysql_adapter()
            rows = await mysql.select(
                table="execution_episodes",
                where="agent_id = %s",
                params=(agent_id,),
                order_by="created_at DESC",
                limit=limit,
            )
            results = rows or []
        else:
            # LONG_TERM / REASONING → agent_memory_extended
            mysql = get_mysql_adapter()
            rows = await mysql.select(
                table="agent_memory_extended",
                where="agent_id = %s AND memory_tier = %s",
                params=(agent_id, tier.value),
                order_by="created_at DESC",
                limit=limit,
            )
            results = rows or []

        MEMORY_HITS.labels(tier=tier.value).inc()
        logger.info(
            "Memory entries list",
            layer="router",
            agent_id=agent_id,
            tier=tier.value,
            count=len(results),
            duration_ms=round((time.time() - start) * 1000),
            trace_id=trace_id,
            span_id=span_id,
        )
        return {"results": results, "tier": tier.value, "count": len(results), "trace_id": trace_id}
    except Exception as exc:
        logger.error(
            "Memory entries list failed",
            layer="router",
            agent_id=agent_id,
            tier=tier.value,
            error=str(exc),
            trace_id=trace_id,
            span_id=span_id,
        )
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/retrieve", response_model=MemoryRetrieveResponse)
async def retrieve_memory(
    request: Request,
    agent_id: int = Query(..., description="Agent ID"),
    tier: MemoryTier = Query(..., description="Memory tier"),
    query: Optional[str] = Query(None, description="Semantic search query (for long_term/reasoning/episodic)"),
    k: int = Query(5, ge=1, le=50, description="Number of results"),
) -> MemoryRetrieveResponse:
    span_id = new_span_id()
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    start = time.time()

    logger.info(
        "Memory retrieve request",
        layer="router",
        agent_id=agent_id,
        tier=tier.value,
        query=query,
        trace_id=trace_id,
        span_id=span_id,
    )

    try:
        results: list = []

        if tier == MemoryTier.SHORT_TERM:
            results = await _short_term.read_all(agent_id)
        elif tier == MemoryTier.LONG_TERM:
            if not query:
                raise HTTPException(status_code=400, detail="query param required for long_term semantic search")
            results = await _long_term.semantic_search(agent_id, query, k=k)
        elif tier == MemoryTier.REASONING:
            if not query:
                raise HTTPException(status_code=400, detail="query param required for reasoning search")
            results = await _reasoning.search(agent_id, query, k=k)
        elif tier == MemoryTier.EPISODIC:
            if not query:
                raise HTTPException(status_code=400, detail="query param required for episodic search")
            results = await _episodic.retrieve_similar(agent_id, query, k=k)

        MEMORY_HITS.labels(tier=tier.value).inc()

        logger.info(
            "Memory retrieve success",
            layer="router",
            agent_id=agent_id,
            tier=tier.value,
            count=len(results),
            duration_ms=round((time.time() - start) * 1000),
            trace_id=trace_id,
            span_id=span_id,
        )

        return MemoryRetrieveResponse(results=results, tier=tier, count=len(results), trace_id=trace_id)

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "Memory retrieve failed",
            layer="router",
            agent_id=agent_id,
            tier=tier.value,
            error=str(exc),
            trace_id=trace_id,
            span_id=span_id,
        )
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/assemble-prompt", response_model=PromptAssembleResponse)
async def assemble_prompt(body: PromptAssembleRequest, request: Request) -> PromptAssembleResponse:
    span_id = new_span_id()
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    start = time.time()

    logger.info(
        "Prompt assemble request",
        layer="router",
        agent_id=body.agent_id,
        tiers=[t.value for t in body.tiers],
        trace_id=trace_id,
        span_id=span_id,
    )

    try:
        tiers_str = [t.value for t in body.tiers]
        result = await _assembler.assemble_prompt(
            agent_id=body.agent_id,
            context=body.context,
            tiers=tiers_str,
            trace_id=trace_id,
        )

        # Increment memory_hits for each tier that contributed
        sources = result.get("sources", {})
        if sources.get("short_term_hits", 0) > 0:
            MEMORY_HITS.labels(tier="short_term").inc(sources["short_term_hits"])
        if sources.get("long_term_hits", 0) > 0:
            MEMORY_HITS.labels(tier="long_term").inc(sources["long_term_hits"])
        if sources.get("reasoning_hits", 0) > 0:
            MEMORY_HITS.labels(tier="reasoning").inc(sources["reasoning_hits"])
        if sources.get("episodic_hits", 0) > 0:
            MEMORY_HITS.labels(tier="episodic").inc(sources["episodic_hits"])

        logger.info(
            "Prompt assembled",
            layer="router",
            agent_id=body.agent_id,
            duration_ms=round((time.time() - start) * 1000),
            trace_id=trace_id,
            span_id=span_id,
        )

        return PromptAssembleResponse(
            system_prompt=result["system_prompt"],
            sources=PromptSourceCounts(**result["sources"]),
            trace_id=result["trace_id"],
        )

    except Exception as exc:
        logger.error(
            "Prompt assembly failed",
            layer="router",
            agent_id=body.agent_id,
            error=str(exc),
            trace_id=trace_id,
            span_id=span_id,
        )
        raise HTTPException(status_code=500, detail=str(exc))
