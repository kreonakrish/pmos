"""Redis async streams adapter for the orchestrator service."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

import redis.asyncio as aioredis

from app.config import settings
from app.utils.logger import logger

SCHEMA_VERSION = "1"


class RedisAdapter:
    """Wraps redis-py async client for stream operations."""

    def __init__(self) -> None:
        self._client: Optional[aioredis.Redis] = None

    async def connect(self) -> None:
        self._client = aioredis.from_url(
            settings.redis_url, encoding="utf-8", decode_responses=True
        )
        logger.info("Redis client connected", layer="adapter", url=settings.redis_url)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            logger.info("Redis client closed", layer="adapter")

    async def health_check(self) -> bool:
        try:
            await self._client.ping()
            return True
        except Exception as exc:
            logger.error("Redis health check failed", layer="adapter", error=str(exc))
            return False

    # ------------------------------------------------------------------
    # Stream producer
    # ------------------------------------------------------------------

    async def publish_to_stream(
        self,
        stream: str,
        message: Dict[str, Any],
        trace_id: str = "",
        maxlen: int = 10000,
    ) -> str:
        """XADD stream MAXLEN ~ maxlen * flat_message_dict. Returns message id."""
        enriched = {
            **message,
            "trace_id": trace_id or str(uuid.uuid4()),
            "source_service": settings.service_name,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "schema_version": SCHEMA_VERSION,
        }
        # Redis stream requires flat string values
        flat = {k: json.dumps(v) if not isinstance(v, str) else v for k, v in enriched.items()}
        msg_id = await self._client.xadd(stream, flat, maxlen=maxlen, approximate=True)
        logger.debug(
            "Published to Redis stream",
            layer="adapter",
            stream=stream,
            msg_id=msg_id,
            trace_id=trace_id,
        )
        return msg_id

    async def publish_memory_write(
        self,
        agent_id: int,
        tier: str,
        content: str,
        task_id: str,
        importance: float = 0.5,
        trace_id: str = "",
        task_description: str = "",
        score: Optional[float] = None,
        outcome: str = "SUCCESS",
    ) -> str:
        metadata: Dict[str, Any] = {
            "task_id": task_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "importance": importance,
            "outcome": outcome,
        }
        if task_description:
            metadata["task_description"] = task_description[:2000]
        if score is not None:
            metadata["score"] = score
        return await self.publish_to_stream(
            "memory:writes",
            {
                "agent_id": str(agent_id),
                "tier": tier,
                "content": content,
                "metadata": json.dumps(metadata),
            },
            trace_id=trace_id,
        )

    async def publish_telemetry(self, event: Dict[str, Any], trace_id: str = "") -> str:
        return await self.publish_to_stream("events:telemetry", event, trace_id=trace_id)

    async def publish_task(self, task: Dict[str, Any], trace_id: str = "") -> str:
        return await self.publish_to_stream("orchestrator:tasks", task, trace_id=trace_id)

    # ------------------------------------------------------------------
    # Stream consumer (scoring:feedback)
    # ------------------------------------------------------------------

    async def consume_scoring_feedback(
        self,
        group: str,
        consumer: str,
        handler: Callable[[Dict[str, Any]], None],
        batch_size: int = 10,
        block_ms: int = 5000,
    ) -> None:
        """
        Blocking XREADGROUP loop. Calls handler for each message.
        Caller is responsible for running this in a background task.
        """
        stream = "scoring:feedback"
        try:
            await self._client.xgroup_create(stream, group, id="$", mkstream=True)
        except Exception:
            pass  # group already exists

        while True:
            try:
                results = await self._client.xreadgroup(
                    group,
                    consumer,
                    {stream: ">"},
                    count=batch_size,
                    block=block_ms,
                )
                if not results:
                    continue
                for _, messages in results:
                    for msg_id, data in messages:
                        try:
                            parsed = {k: self._try_json(v) for k, v in data.items()}
                            await handler(parsed)
                            await self._client.xack(stream, group, msg_id)
                        except Exception as exc:
                            logger.error(
                                "Error processing scoring feedback message",
                                layer="adapter",
                                msg_id=msg_id,
                                error=str(exc),
                            )
            except Exception as exc:
                logger.error(
                    "Redis XREADGROUP error",
                    layer="adapter",
                    stream=stream,
                    error=str(exc),
                )
                # brief pause before retry
                import asyncio
                await asyncio.sleep(1)

    @staticmethod
    def _try_json(value: str) -> Any:
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
