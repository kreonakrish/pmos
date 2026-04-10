"""HTTP client to the memory service."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings
from app.utils.logger import logger


class MemoryAdapter:
    """Calls the memory service via HTTP. All service-to-service calls use retry."""

    @retry(
        stop=stop_after_attempt(settings.retry_max_attempts),
        wait=wait_exponential(
            multiplier=settings.retry_wait_multiplier,
            max=settings.retry_wait_max_sec,
        ),
        reraise=True,
    )
    async def assemble_prompt(
        self,
        agent_id: int,
        context: Dict[str, Any],
        tiers: Optional[List[str]] = None,
        trace_id: str = "",
    ) -> Dict[str, Any]:
        url = f"{settings.memory_service_url}/v1/memory/assemble-prompt"
        payload: Dict[str, Any] = {"agent_id": agent_id, "context": context}
        if tiers:
            payload["tiers"] = tiers
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload, headers={"x-request-id": trace_id})
            resp.raise_for_status()
            data = resp.json()
        logger.debug(
            "Memory prompt assembled",
            layer="adapter",
            agent_id=agent_id,
            sources=data.get("sources"),
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
    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{settings.memory_service_url}/health")
                return resp.status_code == 200
        except Exception:
            return False
