"""Distillation background job — promotes frequent SHORT_TERM entries to LONG_TERM."""
from __future__ import annotations

import asyncio
from typing import Any

from app.adapters.mysql_adapter import AsyncMySQLAdapter, get_mysql_adapter
from app.adapters.redis_adapter import RedisAdapter, get_redis_adapter
from app.config import settings
from app.services.long_term import LongTermMemoryService
from app.services.short_term import ShortTermMemoryService
from app.utils.logger import get_logger, new_span_id

logger = get_logger()

MEMORY_TABLE = "agent_memory_extended"


async def _get_active_agent_ids(mysql: AsyncMySQLAdapter) -> list[int]:
    """Fetch distinct agent_ids from agent_memory_extended to know which agents have SHORT_TERM data in MySQL."""
    # We rely on Redis for SHORT_TERM, so we query what agent IDs are registered
    try:
        rows = await mysql.execute(
            "SELECT DISTINCT agent_id FROM agent_memory_extended LIMIT 1000",
            fetch=True,
        )
        return [row["agent_id"] for row in (rows or [])]
    except Exception:
        # agents table may not exist in test env; return empty list
        return []


class DistillationService:
    """
    Background service that runs every `distillation_interval_min` minutes.
    For each agent, it checks SHORT_TERM memories:
    - access_count >= threshold → promote to LONG_TERM
    - entry deleted from SHORT_TERM after promotion
    """

    def __init__(
        self,
        short_term: ShortTermMemoryService | None = None,
        long_term: LongTermMemoryService | None = None,
        mysql: AsyncMySQLAdapter | None = None,
        redis: RedisAdapter | None = None,
    ) -> None:
        self._short_term = short_term or ShortTermMemoryService()
        self._long_term = long_term or LongTermMemoryService()
        self._mysql = mysql or get_mysql_adapter()
        self._redis = redis or get_redis_adapter()
        self._threshold = settings.distillation_frequency_threshold
        self._interval_sec = settings.distillation_interval_min * 60
        self._running = False

    async def run_once(self, agent_ids: list[int] | None = None) -> dict[str, int]:
        """
        Execute one distillation pass across all (or specified) agents.
        Returns summary: {promoted, skipped, errors}.
        """
        span_id = new_span_id()
        logger.info("Distillation pass starting", layer="service", span_id=span_id)

        if agent_ids is None:
            agent_ids = await _get_active_agent_ids(self._mysql)

        promoted = 0
        skipped = 0
        errors = 0

        for agent_id in agent_ids:
            try:
                p, s = await self._distill_agent(agent_id, span_id)
                promoted += p
                skipped += s
            except Exception as exc:
                errors += 1
                logger.error(
                    "Distillation error for agent",
                    layer="service",
                    agent_id=agent_id,
                    error=str(exc),
                    span_id=span_id,
                )

        logger.info(
            "Distillation pass complete",
            layer="service",
            promoted=promoted,
            skipped=skipped,
            errors=errors,
            span_id=span_id,
        )
        return {"promoted": promoted, "skipped": skipped, "errors": errors}

    async def _distill_agent(self, agent_id: int, span_id: str) -> tuple[int, int]:
        """Process one agent. Returns (promoted_count, skipped_count)."""
        access_counts = await self._short_term.get_access_counts(agent_id)
        promoted = 0
        skipped = 0

        for memory_key, count in access_counts.items():
            if count >= self._threshold:
                # Retrieve the full entry
                entry = await self._short_term.get_entry(agent_id, memory_key)
                if entry is None:
                    continue

                content = entry.get("content", "")
                metadata = entry.get("metadata", {})
                metadata["distilled_from"] = "short_term"
                metadata["original_access_count"] = count

                try:
                    await self._long_term.store(agent_id, content, metadata)
                    await self._short_term.delete(agent_id, memory_key)
                    promoted += 1
                    logger.info(
                        "SHORT_TERM → LONG_TERM promoted",
                        layer="service",
                        agent_id=agent_id,
                        memory_key=memory_key,
                        access_count=count,
                        span_id=span_id,
                    )
                except Exception as exc:
                    logger.error(
                        "Promotion failed",
                        layer="service",
                        agent_id=agent_id,
                        memory_key=memory_key,
                        error=str(exc),
                        span_id=span_id,
                    )
            else:
                skipped += 1

        return promoted, skipped

    async def start_loop(self) -> None:
        """Infinite loop — called as a background task."""
        self._running = True
        logger.info(
            "Distillation loop started",
            layer="service",
            interval_sec=self._interval_sec,
        )
        while self._running:
            await asyncio.sleep(self._interval_sec)
            try:
                await self.run_once()
            except Exception as exc:
                logger.error("Distillation loop error", layer="service", error=str(exc))

    def stop(self) -> None:
        self._running = False
