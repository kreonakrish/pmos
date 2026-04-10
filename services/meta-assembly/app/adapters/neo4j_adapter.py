"""Neo4j adapter — AgentCapabilityNode writes for meta-assembly."""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

from neo4j import AsyncGraphDatabase, AsyncDriver

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(layer="adapter")

_driver: AsyncDriver | None = None


def get_driver() -> AsyncDriver:
    global _driver
    if _driver is None:
        _driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
    return _driver


async def close_driver() -> None:
    global _driver
    if _driver is not None:
        await _driver.close()
        _driver = None


class Neo4jAdapter:
    """Thin wrapper around the async Neo4j driver."""

    def __init__(self) -> None:
        self._driver = get_driver()

    async def create_capability_node(
        self,
        capability_id: str,
        tool_ids: list[str],
        domains: list[str],
        score_band_json: dict[str, Any],
        trace_id: str = "",
    ) -> None:
        """Create an AgentCapabilityNode in Neo4j."""
        t0 = time.monotonic()
        trace_id = trace_id or str(uuid.uuid4())
        cypher = """
            MERGE (n:AgentCapabilityNode {agent_id: $capability_id})
            SET n.tool_ids        = $tool_ids,
                n.domains         = $domains,
                n.score_band_json = $score_band_json,
                n.updated_at      = datetime()
        """
        try:
            async with self._driver.session() as session:
                await session.run(
                    cypher,
                    capability_id=capability_id,
                    tool_ids=tool_ids,
                    domains=domains,
                    score_band_json=json.dumps(score_band_json),
                )
            duration_ms = int((time.monotonic() - t0) * 1000)
            logger.info(
                "neo4j_node_created",
                trace_id=trace_id,
                node_label="AgentCapabilityNode",
                capability_id=capability_id,
                duration_ms=duration_ms,
                layer="adapter",
            )
        except Exception as exc:
            duration_ms = int((time.monotonic() - t0) * 1000)
            logger.error(
                "neo4j_node_failed",
                trace_id=trace_id,
                duration_ms=duration_ms,
                error=str(exc),
                layer="adapter",
            )
            raise
