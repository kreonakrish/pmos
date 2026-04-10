"""HTTP client to the meta-assembly service."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings
from app.utils.logger import logger


class MetaAdapter:
    """Calls the meta-assembly service via HTTP."""

    @retry(
        stop=stop_after_attempt(settings.retry_max_attempts),
        wait=wait_exponential(
            multiplier=settings.retry_wait_multiplier,
            max=settings.retry_wait_max_sec,
        ),
        reraise=True,
    )
    async def detect_gap(
        self,
        task_id: str,
        task_type: str,
        required_tools: List[str],
        failed_agents: List[int],
        failure_reasons: List[str],
        trace_id: str = "",
    ) -> Dict[str, Any]:
        url = f"{settings.meta_assembly_url}/v1/meta/detect-gap"
        payload = {
            "task_context": {
                "task_id": task_id,
                "task_type": task_type,
                "required_tools": required_tools,
            },
            "failed_agents": failed_agents,
            "failure_reasons": failure_reasons,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload, headers={"x-request-id": trace_id})
            resp.raise_for_status()
            data = resp.json()
        logger.info(
            "Capability gap detected",
            layer="adapter",
            gap_description=data.get("gap_description", "")[:100],
            suggested_type=data.get("suggested_capability_type"),
            trace_id=trace_id,
        )
        return data

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{settings.meta_assembly_url}/health")
                return resp.status_code == 200
        except Exception:
            return False
