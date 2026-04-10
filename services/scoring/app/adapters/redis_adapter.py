"""
Redis adapter for the scoring service.

Wraps redis-py (async) with PMOS-standard stream message format.
Every stream message includes: trace_id, source_service, timestamp, schema_version.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import redis.asyncio as aioredis

from app.config import settings
from app.utils.logger import StructuredLogger

logger = StructuredLogger(layer="adapter")

STREAM_SCORING_FEEDBACK = "scoring:feedback"
SERVICE_NAME = "scoring"
SCHEMA_VERSION = "1"


class RedisAdapter:
    """Async Redis adapter with stream helpers."""

    def __init__(self) -> None:
        self._client: Optional[aioredis.Redis] = None

    async def client(self) -> aioredis.Redis:
        if self._client is None:
            self._client = aioredis.from_url(
                settings.redis_url, decode_responses=True
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ── Stream producers ──────────────────────────────────────────────────────

    async def publish_feedback(self, payload: Dict[str, Any], trace_id: str) -> str:
        """Publish a feedback event to the scoring:feedback stream."""
        r = await self.client()
        message = {
            "trace_id": trace_id,
            "source_service": SERVICE_NAME,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "schema_version": SCHEMA_VERSION,
            "data": json.dumps(payload),
        }
        msg_id = await r.xadd(STREAM_SCORING_FEEDBACK, message)
        logger.info(
            "Published to scoring:feedback",
            trace_id=trace_id,
            stream=STREAM_SCORING_FEEDBACK,
            msg_id=msg_id,
        )
        return msg_id

    # ── Stream consumers ──────────────────────────────────────────────────────

    async def ensure_consumer_group(
        self, stream: str, group: str, start_id: str = "0"
    ) -> None:
        """Create consumer group if it does not already exist."""
        r = await self.client()
        try:
            await r.xgroup_create(stream, group, id=start_id, mkstream=True)
        except aioredis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def read_group(
        self,
        stream: str,
        group: str,
        consumer: str,
        count: int = 10,
        block_ms: int = 1000,
    ) -> List[Tuple[str, Dict[str, str]]]:
        """Read messages from a consumer group. Returns list of (msg_id, fields)."""
        r = await self.client()
        result = await r.xreadgroup(
            group, consumer, {stream: ">"}, count=count, block=block_ms
        )
        if not result:
            return []
        messages = []
        for _stream, entries in result:
            for msg_id, fields in entries:
                messages.append((msg_id, fields))
        return messages

    async def ack(self, stream: str, group: str, msg_id: str) -> None:
        r = await self.client()
        await r.xack(stream, group, msg_id)

    # ── Health check ─────────────────────────────────────────────────────────

    async def ping(self) -> bool:
        try:
            r = await self.client()
            return await r.ping()
        except Exception:
            return False
