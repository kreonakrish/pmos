"""HTTP client to the RAG service."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings
from app.utils.logger import logger


class RAGAdapter:
    """Calls the RAG service via HTTP."""

    @retry(
        stop=stop_after_attempt(settings.retry_max_attempts),
        wait=wait_exponential(
            multiplier=settings.retry_wait_multiplier,
            max=settings.retry_wait_max_sec,
        ),
        reraise=True,
    )
    async def query(
        self,
        query: str,
        agent_id: int,
        task_id: str,
        domain: str = "",
        top_k: int = 5,
        sources: Optional[List[str]] = None,
        trace_id: str = "",
    ) -> Dict[str, Any]:
        url = f"{settings.rag_service_url}/v1/rag/query"
        payload: Dict[str, Any] = {
            "query": query,
            "agent_id": agent_id,
            "top_k": top_k,
            "context": {"task_id": task_id, "domain": domain},
        }
        if sources:
            payload["sources"] = sources
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload, headers={"x-request-id": trace_id})
            resp.raise_for_status()
            data = resp.json()
        logger.debug(
            "RAG query completed",
            layer="adapter",
            results=len(data.get("results", [])),
            latency_ms=data.get("latency_ms"),
            trace_id=trace_id,
        )
        return data

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{settings.rag_service_url}/health")
                return resp.status_code == 200
        except Exception:
            return False
