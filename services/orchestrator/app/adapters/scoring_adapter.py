"""HTTP client to the scoring service."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings
from app.utils.logger import logger


class ScoringAdapter:
    """Calls the scoring service via HTTP."""

    @retry(
        stop=stop_after_attempt(settings.retry_max_attempts),
        wait=wait_exponential(
            multiplier=settings.retry_wait_multiplier,
            max=settings.retry_wait_max_sec,
        ),
        reraise=True,
    )
    async def evaluate(
        self,
        agent_id: int,
        task_id: str,
        context_type: str,
        response_text: str,
        used_knowledge: bool,
        latency_ms: int,
        tool_calls: Optional[List[str]] = None,
        trace_id: str = "",
    ) -> Dict[str, Any]:
        """POST /scoring/evaluate — returns score, band, recommendation, factors."""
        url = f"{settings.scoring_service_url}/v1/scoring/evaluate"
        payload = {
            "agent_id": agent_id,
            "task_id": task_id,
            "context_type": context_type,
            "response_text": response_text,
            "used_knowledge": used_knowledge,
            "latency_ms": latency_ms,
            "tool_calls": tool_calls or [],
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload, headers={"x-request-id": trace_id})
            resp.raise_for_status()
            data = resp.json()
        logger.debug(
            "Score evaluated",
            layer="adapter",
            agent_id=agent_id,
            task_id=task_id,
            score=data.get("score"),
            recommendation=data.get("recommendation"),
            trace_id=trace_id,
        )
        return data

    @retry(
        stop=stop_after_attempt(settings.retry_max_attempts),
        wait=wait_exponential(
            multiplier=settings.retry_wait_multiplier,
            max=settings.retry_wait_max_sec,
        ),
        reraise=True,
    )
    async def submit_feedback(
        self,
        agent_id: int,
        task_id: str,
        feedback_source: str,
        score: float,
        trace_id: str = "",
    ) -> None:
        url = f"{settings.scoring_service_url}/v1/scoring/feedback"
        payload = {
            "agent_id": agent_id,
            "task_id": task_id,
            "feedback_source": feedback_source,
            "score": score,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload, headers={"x-request-id": trace_id})
            resp.raise_for_status()

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{settings.scoring_service_url}/health")
                return resp.status_code == 200
        except Exception:
            return False
