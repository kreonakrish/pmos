"""Redis Streams consumer for memory:writes stream."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from app.adapters.redis_adapter import RedisAdapter, get_redis_adapter
from app.config import settings
from app.models.memory import MemoryTier
from app.services.episodic import EpisodicMemoryService
from app.services.long_term import LongTermMemoryService
from app.services.reasoning import ReasoningMemoryService
from app.services.short_term import ShortTermMemoryService
from app.utils.logger import get_logger, new_span_id

logger = get_logger()


class MemoryWriteConsumer:
    """Consumes the `memory:writes` Redis stream and dispatches writes to the correct tier."""

    def __init__(
        self,
        redis: RedisAdapter | None = None,
        short_term: ShortTermMemoryService | None = None,
        long_term: LongTermMemoryService | None = None,
        reasoning: ReasoningMemoryService | None = None,
        episodic: EpisodicMemoryService | None = None,
    ) -> None:
        self._redis = redis or get_redis_adapter()
        self._short_term = short_term or ShortTermMemoryService()
        self._long_term = long_term or LongTermMemoryService()
        self._reasoning = reasoning or ReasoningMemoryService()
        self._episodic = episodic or EpisodicMemoryService()
        self._group = settings.redis_stream_group
        self._consumer = settings.redis_stream_consumer
        self._stream = settings.redis_memory_stream
        self._running = False

    async def _ensure_group(self) -> None:
        await self._redis.xgroup_create(self._stream, self._group, mkstream=True)

    async def consume_memory_writes(self) -> None:
        """Blocking stream consumer loop. Call as an asyncio background task."""
        self._running = True
        await self._ensure_group()
        logger.info(
            "Memory write consumer started",
            layer="service",
            stream=self._stream,
            group=self._group,
            consumer=self._consumer,
        )

        while self._running:
            try:
                messages = await self._redis.xreadgroup(
                    self._group,
                    self._consumer,
                    {self._stream: ">"},
                    count=10,
                    block=1000,
                )
                if not messages:
                    continue

                for stream_name, msgs in messages:
                    for msg_id, fields in msgs:
                        span_id = new_span_id()
                        try:
                            await self._handle_message(fields, span_id)
                            await self._redis.xack(self._stream, self._group, msg_id)
                        except Exception as exc:
                            logger.error(
                                "Failed to process memory:writes message",
                                layer="service",
                                msg_id=msg_id,
                                error=str(exc),
                                span_id=span_id,
                            )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(
                    "Consumer loop error",
                    layer="service",
                    stream=self._stream,
                    error=str(exc),
                )
                await asyncio.sleep(2)

    async def _handle_message(self, fields: dict[str, str], span_id: str) -> None:
        """Decode and dispatch a single stream message."""
        agent_id_raw = fields.get("agent_id", "")
        tier_raw = fields.get("tier", "")
        content = fields.get("content", "")
        metadata_raw = fields.get("metadata", "{}")

        try:
            agent_id = int(agent_id_raw)
        except (ValueError, TypeError):
            logger.error("Invalid agent_id in stream message", layer="service", span_id=span_id)
            return

        try:
            metadata: dict[str, Any] = json.loads(metadata_raw)
        except (json.JSONDecodeError, TypeError):
            metadata = {}

        tier = tier_raw.lower().strip()

        logger.info(
            "Dispatching memory write from stream",
            layer="service",
            agent_id=agent_id,
            tier=tier,
            span_id=span_id,
        )

        if tier == MemoryTier.SHORT_TERM.value:
            await self._short_term.write(agent_id, content, metadata)
        elif tier == MemoryTier.LONG_TERM.value:
            await self._long_term.store(agent_id, content, metadata)
        elif tier == MemoryTier.REASONING.value:
            await self._reasoning.store(agent_id, content, metadata)
        elif tier == MemoryTier.EPISODIC.value:
            # Build a properly-populated episode so `content` doesn't render as
            # the placeholder "Task: \nOutput: ". `content` from the stream is
            # the agent's final output; `task_description` / `task_id` /
            # `outcome` / `score` come from the metadata payload.
            episode = {
                "task_description": metadata.get("task_description", ""),
                "output": content or "",
                "task_id": metadata.get("task_id", ""),
                "steps": metadata.get("steps", []),
                "score": metadata.get("score", 0.0),
                "outcome": metadata.get("outcome", "SUCCESS"),
                "importance": metadata.get("importance", 0.5),
                "metadata": {k: v for k, v in metadata.items() if k not in {
                    "task_description", "task_id", "steps", "score", "outcome", "importance",
                }},
            }
            await self._episodic.store_episode(agent_id, episode)
        else:
            logger.warning(
                "Unknown memory tier in stream message",
                layer="service",
                tier=tier,
                span_id=span_id,
            )

    def stop(self) -> None:
        self._running = False
