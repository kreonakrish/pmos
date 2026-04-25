"""Translation endpoints.

POST /v1/translate                — translate NL question via the pipeline stub
POST /v1/translator/examples      — promote a translation example into Qdrant
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from app.models.translation import (
    PromoteExampleRequest,
    PromoteExampleResponse,
    TranslationRequest,
    TranslationResponse,
)
from app.utils.logger import logger

router = APIRouter(tags=["translator"])


@router.post("/v1/translate", response_model=TranslationResponse)
async def translate(req: TranslationRequest, request: Request) -> TranslationResponse:
    trace_id = req.trace_id or str(uuid.uuid4())
    pipeline = request.app.state.pipeline

    logger.info(
        "Translate request received",
        layer="router",
        trace_id=trace_id,
        team_id=req.team_id,
        conversation_id=req.conversation_id,
    )

    result = await pipeline.translate(
        question=req.question,
        team_id=req.team_id or "",
        conversation_id=req.conversation_id or "",
        trace_id=trace_id,
        prior_turns=req.prior_turns or [],
    )
    # ``result`` is a TranslationResult TypedDict — pydantic validates on return.
    return TranslationResponse(**result)


@router.post("/v1/translator/examples", response_model=PromoteExampleResponse)
async def promote_example(
    req: PromoteExampleRequest, request: Request
) -> PromoteExampleResponse:
    trace_id = req.trace_id or str(uuid.uuid4())
    qdrant = request.app.state.qdrant
    embedder = request.app.state.embedder

    logger.info(
        "Promote example received",
        layer="router",
        trace_id=trace_id,
        promoted_by=req.promoted_by,
        question_len=len(req.question),
    )

    payload = {
        "question": req.question,
        "canonical_entities": req.canonical_entities,
        "relationships": [],
        "dataset_bindings": req.dataset_bindings,
        "intent": req.intent,
        "domain": req.domain,
        "decomposition": req.decomposition,
        "score": req.score,
        "promoted_by": req.promoted_by,
        "promoted_at": datetime.now(timezone.utc).isoformat(),
        "trace_id": trace_id,
    }

    point_id = str(uuid.uuid4())
    embedded = False

    if not embedder.available():
        logger.warning(
            "Embedder unavailable — skipping translation example upsert",
            layer="router",
            trace_id=trace_id,
        )
        return PromoteExampleResponse(
            status="skipped_no_embedder",
            point_id=None,
            embedded=False,
            trace_id=trace_id,
        )

    try:
        vector = await embedder.embed(req.question)
        await qdrant.upsert_example(
            point_id=point_id,
            vector=vector,
            payload=payload,
            trace_id=trace_id,
        )
        embedded = True
    except Exception as exc:
        logger.error(
            "Failed to upsert translation example",
            layer="router",
            trace_id=trace_id,
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail=f"upsert failed: {exc}")

    return PromoteExampleResponse(
        status="ok",
        point_id=point_id,
        embedded=embedded,
        trace_id=trace_id,
    )
