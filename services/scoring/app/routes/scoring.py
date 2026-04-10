"""
Scoring service HTTP route handlers.

Endpoints:
    POST /v1/scoring/evaluate
    POST /v1/scoring/band
    POST /v1/scoring/feedback
    GET  /v1/scoring/weights/{agent_id}
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.models.scoring import (
    BandRequest,
    EvaluateRequest,
    EvaluateResponse,
    FeedbackRequest,
    FeedbackResponse,
    WeightsResponse,
)
from app.utils.logger import StructuredLogger
from app.utils.metrics import (
    BAND_WIDTH,
    REQUEST_DURATION,
    REQUEST_TOTAL,
    SCORE_VALUE,
)

router = APIRouter(prefix="/v1/scoring", tags=["scoring"])
logger = StructuredLogger(layer="router")


def _trace_id(request: Request) -> str:
    return request.headers.get("x-request-id", str(uuid.uuid4()))


# ── POST /v1/scoring/evaluate ────────────────────────────────────────────────

@router.post("/evaluate", response_model=EvaluateResponse, status_code=200)
async def evaluate(request: Request, body: EvaluateRequest) -> Dict[str, Any]:
    trace_id = _trace_id(request)
    start = time.perf_counter()

    score_engine = request.app.state.score_engine
    band_engine = request.app.state.band_engine
    mysql = request.app.state.mysql

    try:
        # Build factors
        if body.factors is not None:
            factors = body.factors.model_dump()
        else:
            factors = score_engine.derive_factors_from_request(
                body.response_text,
                body.used_knowledge,
                body.latency_ms,
                body.tool_calls,
            )

        # Compute score
        result = await score_engine.compute_score(
            body.agent_id, body.context_type, factors, trace_id=trace_id
        )
        score: float = result["score"]
        weights_used: Dict[str, float] = result["weights_used"]

        # Persist to score_history
        await mysql.insert_score(
            body.agent_id, body.task_id, body.context_type, score, factors
        )

        # Compute adaptive band
        band = await band_engine.compute_band(
            body.agent_id, body.context_type, trace_id=trace_id
        )

        # Determine recommendation
        recommendation = band_engine.derive_recommendation(score, band)

        # Update Prometheus metrics
        agent_label = str(body.agent_id)
        SCORE_VALUE.labels(
            agent_id=agent_label, context_type=body.context_type
        ).set(score)
        BAND_WIDTH.labels(
            agent_id=agent_label, context_type=body.context_type
        ).set(band["high"] - band["low"])

        elapsed = (time.perf_counter() - start) * 1000
        REQUEST_TOTAL.labels(method="POST", path="/v1/scoring/evaluate", status=200).inc()
        REQUEST_DURATION.labels(method="POST", path="/v1/scoring/evaluate").observe(
            elapsed / 1000
        )

        logger.info(
            "Evaluation complete",
            agent_id=body.agent_id,
            task_id=body.task_id,
            score=score,
            recommendation=recommendation,
            duration_ms=round(elapsed, 2),
            trace_id=trace_id,
            span_id=str(uuid.uuid4()),
        )

        return {
            "score": score,
            "band": band,
            "recommendation": recommendation,
            "factors": factors,
            "weights_used": weights_used,
            "trace_id": trace_id,
        }

    except Exception as exc:
        REQUEST_TOTAL.labels(method="POST", path="/v1/scoring/evaluate", status=500).inc()
        logger.error(
            "Evaluation failed",
            error=str(exc),
            agent_id=body.agent_id,
            trace_id=trace_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": str(exc), "code": "EVALUATE_FAILED", "trace_id": trace_id},
        )


# ── POST /v1/scoring/band ─────────────────────────────────────────────────────

@router.post("/band", status_code=200)
async def get_band(request: Request, body: BandRequest) -> Dict[str, Any]:
    trace_id = _trace_id(request)
    start = time.perf_counter()

    band_engine = request.app.state.band_engine

    try:
        band = await band_engine.compute_band(
            body.agent_id, body.context_type, trace_id=trace_id
        )

        elapsed = (time.perf_counter() - start) * 1000
        REQUEST_TOTAL.labels(method="POST", path="/v1/scoring/band", status=200).inc()
        REQUEST_DURATION.labels(method="POST", path="/v1/scoring/band").observe(
            elapsed / 1000
        )

        return band

    except Exception as exc:
        REQUEST_TOTAL.labels(method="POST", path="/v1/scoring/band", status=500).inc()
        logger.error(
            "Band computation failed",
            error=str(exc),
            agent_id=body.agent_id,
            trace_id=trace_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": str(exc), "code": "BAND_FAILED", "trace_id": trace_id},
        )


# ── POST /v1/scoring/feedback ─────────────────────────────────────────────────

@router.post("/feedback", response_model=FeedbackResponse, status_code=200)
async def submit_feedback(request: Request, body: FeedbackRequest) -> Dict[str, Any]:
    trace_id = _trace_id(request)
    start = time.perf_counter()

    redis = request.app.state.redis

    try:
        payload = body.model_dump()
        # Convert enums to their string values for serialisation
        payload["feedback_source"] = body.feedback_source.value
        payload["feedback_type"] = body.feedback_type.value

        await redis.publish_feedback(payload, trace_id)

        elapsed = (time.perf_counter() - start) * 1000
        REQUEST_TOTAL.labels(method="POST", path="/v1/scoring/feedback", status=200).inc()
        REQUEST_DURATION.labels(method="POST", path="/v1/scoring/feedback").observe(
            elapsed / 1000
        )

        logger.info(
            "Feedback accepted and queued",
            agent_id=body.agent_id,
            task_id=body.task_id,
            feedback_source=body.feedback_source.value,
            duration_ms=round(elapsed, 2),
            trace_id=trace_id,
            span_id=str(uuid.uuid4()),
        )

        return {"accepted": True, "trace_id": trace_id}

    except Exception as exc:
        REQUEST_TOTAL.labels(method="POST", path="/v1/scoring/feedback", status=500).inc()
        logger.error(
            "Feedback submission failed",
            error=str(exc),
            agent_id=body.agent_id,
            trace_id=trace_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": str(exc), "code": "FEEDBACK_FAILED", "trace_id": trace_id},
        )


# ── GET /v1/scoring/history/{agent_id} ───────────────────────────────────────

@router.get("/history/{agent_id}", status_code=200)
async def get_history(request: Request, agent_id: int) -> Dict[str, Any]:
    trace_id = _trace_id(request)
    start = time.perf_counter()

    mysql = request.app.state.mysql
    band_engine = request.app.state.band_engine

    try:
        history = await mysql.get_score_history(agent_id)

        # Enrich each entry with rolling band data
        if history:
            # History is ordered DESC — reverse for chronological rolling computation
            scores_chrono = [e["score"] for e in reversed(history)]
            import numpy as np
            from app.config import settings

            sensitivity = settings.band_sensitivity_factor
            min_width = settings.band_min_width
            window = settings.scoring_history_window

            # Compute rolling band for each point
            for i, entry in enumerate(reversed(history)):
                idx = i + 1  # 1-based index in chronological order
                window_scores = scores_chrono[max(0, idx - window):idx]
                if len(window_scores) >= 2:
                    arr = np.array(window_scores, dtype=float)
                    mean = float(np.mean(arr))
                    std_val = float(np.std(arr))
                    bw = std_val * sensitivity
                    bl = max(0.0, mean - bw)
                    bh = min(1.0, mean + bw)
                    if (bh - bl) < min_width:
                        center = (bh + bl) / 2.0
                        bl = max(0.0, center - min_width / 2.0)
                        bh = min(1.0, center + min_width / 2.0)
                    entry["band_low"] = round(bl, 4)
                    entry["band_high"] = round(bh, 4)
                    entry["within_band"] = entry["score"] >= bl
                else:
                    entry["band_low"] = 0.0
                    entry["band_high"] = 1.0
                    entry["within_band"] = True

        elapsed = (time.perf_counter() - start) * 1000
        REQUEST_TOTAL.labels(
            method="GET", path="/v1/scoring/history/{agent_id}", status=200
        ).inc()
        REQUEST_DURATION.labels(
            method="GET", path="/v1/scoring/history/{agent_id}"
        ).observe(elapsed / 1000)

        return {
            "agent_id": agent_id,
            "history": history,
        }

    except Exception as exc:
        REQUEST_TOTAL.labels(
            method="GET", path="/v1/scoring/history/{agent_id}", status=500
        ).inc()
        logger.error(
            "History fetch failed",
            error=str(exc),
            agent_id=agent_id,
            trace_id=trace_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": str(exc), "code": "HISTORY_FAILED", "trace_id": trace_id},
        )


# ── GET /v1/scoring/weights/{agent_id} ───────────────────────────────────────

@router.get("/weights/{agent_id}", response_model=WeightsResponse, status_code=200)
async def get_weights(request: Request, agent_id: int) -> Dict[str, Any]:
    trace_id = _trace_id(request)
    start = time.perf_counter()

    weight_store = request.app.state.weight_store

    try:
        weights = await weight_store.get_all_weights(agent_id)
        context_types = await weight_store.get_all_context_types(agent_id)

        elapsed = (time.perf_counter() - start) * 1000
        REQUEST_TOTAL.labels(
            method="GET", path="/v1/scoring/weights/{agent_id}", status=200
        ).inc()
        REQUEST_DURATION.labels(
            method="GET", path="/v1/scoring/weights/{agent_id}"
        ).observe(elapsed / 1000)

        return {
            "agent_id": agent_id,
            "weights": weights,
            "context_types": context_types,
        }

    except Exception as exc:
        REQUEST_TOTAL.labels(
            method="GET", path="/v1/scoring/weights/{agent_id}", status=500
        ).inc()
        logger.error(
            "Weight fetch failed",
            error=str(exc),
            agent_id=agent_id,
            trace_id=trace_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": str(exc), "code": "WEIGHTS_FAILED", "trace_id": trace_id},
        )
