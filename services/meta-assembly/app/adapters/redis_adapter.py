"""Redis adapter — stream producer for events:capability_added."""
from __future__ import annotations

import json
import time
import uuid

import redis.asyncio as aioredis

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(layer="adapter")

_redis_client: aioredis.Redis | None = None  # type: ignore[type-arg]


def get_redis() -> aioredis.Redis:  # type: ignore[type-arg]
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


async def close_redis() -> None:
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None


class RedisAdapter:
    """Thin wrapper for Redis stream operations."""

    def __init__(self) -> None:
        self._redis = get_redis()

    async def publish_capability_added(
        self,
        capability_id: str,
        capability_type: str,
        capability_name: str,
        gap_id: str,
        validation_score: float,
        trace_id: str = "",
    ) -> str:
        """Publish to events:capability_added stream; returns stream entry ID."""
        trace_id = trace_id or str(uuid.uuid4())
        stream_name = "events:capability_added"
        message: dict[str, str] = {
            "schema_version": "1",
            "trace_id": trace_id,
            "source_service": settings.service_name,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "capability_id": capability_id,
            "capability_type": capability_type,
            "capability_name": capability_name,
            "gap_id": gap_id,
            "validation_score": str(validation_score),
        }
        try:
            entry_id = await self._redis.xadd(stream_name, message)  # type: ignore[arg-type]
            logger.info(
                "redis_stream_published",
                trace_id=trace_id,
                stream=stream_name,
                entry_id=entry_id,
                layer="adapter",
            )
            return entry_id
        except Exception as exc:
            logger.error(
                "redis_stream_failed",
                trace_id=trace_id,
                stream=stream_name,
                error=str(exc),
                layer="adapter",
            )
            raise
