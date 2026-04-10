"""HTTP client to the agent-mgmt service."""

from __future__ import annotations

from typing import Any, Dict, List

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings
from app.utils.logger import logger


class AgentMgmtAdapter:
    """Calls the agent-mgmt service via HTTP. All service-to-service calls use retry."""

    @retry(
        stop=stop_after_attempt(settings.retry_max_attempts),
        wait=wait_exponential(
            multiplier=settings.retry_wait_multiplier,
            max=settings.retry_wait_max_sec,
        ),
        reraise=True,
    )
    async def get_team(self, team_id: str, trace_id: str = "") -> Dict[str, Any]:
        """Fetch team details including agents from agent-mgmt."""
        url = f"{settings.agent_mgmt_url}/v1/teams/{team_id}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers={"x-request-id": trace_id})
            resp.raise_for_status()
            data = resp.json()
        logger.debug(
            "Team fetched from agent-mgmt",
            layer="adapter",
            team_id=team_id,
            trace_id=trace_id,
        )
        return data.get("team", data)

    @retry(
        stop=stop_after_attempt(settings.retry_max_attempts),
        wait=wait_exponential(
            multiplier=settings.retry_wait_multiplier,
            max=settings.retry_wait_max_sec,
        ),
        reraise=True,
    )
    async def get_agent_tools(self, agent_id: str, trace_id: str = "") -> List[Dict[str, Any]]:
        """Fetch tools assigned to an agent."""
        url = f"{settings.agent_mgmt_url}/v1/agents/{agent_id}/tools"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers={"x-request-id": trace_id})
            resp.raise_for_status()
            data = resp.json()
        logger.debug(
            "Agent tools fetched from agent-mgmt",
            layer="adapter",
            agent_id=agent_id,
            trace_id=trace_id,
        )
        return data.get("tools", [])

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
                resp = await client.get(f"{settings.agent_mgmt_url}/health")
                return resp.status_code == 200
        except Exception:
            return False
