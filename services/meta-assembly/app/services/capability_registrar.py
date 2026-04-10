"""Capability registrar — writes validated specs to MySQL, Neo4j, and publishes to Redis."""
from __future__ import annotations

import json
import uuid
from typing import Any

from app.utils.logger import get_logger

logger = get_logger(layer="service")


class CapabilityRegistrar:
    """Persists a validated capability spec across all backing stores."""

    def __init__(
        self,
        mysql_adapter: Any,
        neo4j_adapter: Any,
        redis_adapter: Any,
    ) -> None:
        self.mysql = mysql_adapter
        self.neo4j = neo4j_adapter
        self.redis = redis_adapter

    async def register(
        self,
        spec: dict[str, Any],
        gap_id: str,
        validation_score: float,
        trace_id: str = "",
    ) -> str:
        """Register a capability spec into MySQL + Neo4j and publish a Redis event.

        Returns the generated capability_id (UUID).
        """
        trace_id = trace_id or str(uuid.uuid4())
        capability_id = str(uuid.uuid4())
        cap_type = str(spec.get("capability_type", "TOOL")).upper()
        name = str(spec.get("name", "unnamed"))
        description = str(spec.get("description", ""))
        spec_json = spec.get("spec_json", {})
        tool_ids = spec_json.get("dependencies", [])
        domains = spec_json.get("domains", [])

        # 1. Insert into MySQL capability_registry
        await self.mysql.insert_capability(
            capability_id=capability_id,
            capability_type=cap_type,
            name=name,
            description=description,
            spec_json=spec,
            gap_id=gap_id,
            validation_score=validation_score,
            trace_id=trace_id,
        )

        # 2. Create Neo4j AgentCapabilityNode
        await self.neo4j.create_capability_node(
            capability_id=capability_id,
            tool_ids=tool_ids,
            domains=domains,
            score_band_json={},
            trace_id=trace_id,
        )

        # 3. Publish to events:capability_added Redis stream
        await self.redis.publish_capability_added(
            capability_id=capability_id,
            capability_type=cap_type,
            capability_name=name,
            gap_id=gap_id,
            validation_score=validation_score,
            trace_id=trace_id,
        )

        logger.info(
            "capability_registered",
            trace_id=trace_id,
            capability_id=capability_id,
            capability_type=cap_type,
            capability_name=name,
            gap_id=gap_id,
            validation_score=validation_score,
            layer="service",
        )

        return capability_id
