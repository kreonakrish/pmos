"""Redis adapter — wraps redis-py async client behind a clean interface."""
from __future__ import annotations

import json
from typing import Any, Optional

import redis.asyncio as aioredis

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger()


class RedisAdapter:
    """Async Redis adapter. All methods are async."""

    def __init__(self, redis_url: str | None = None) -> None:
        self._url = redis_url or settings.redis_url
        self._client: Optional[aioredis.Redis] = None

    async def _get_client(self) -> aioredis.Redis:
        if self._client is None:
            self._client = await aioredis.from_url(
                self._url, encoding="utf-8", decode_responses=True
            )
        return self._client

    async def hset(self, key: str, field: str, value: Any) -> None:
        client = await self._get_client()
        serialised = json.dumps(value) if not isinstance(value, str) else value
        await client.hset(key, field, serialised)

    async def hget(self, key: str, field: str) -> Optional[Any]:
        client = await self._get_client()
        raw = await client.hget(key, field)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    async def hgetall(self, key: str) -> dict[str, Any]:
        client = await self._get_client()
        raw = await client.hgetall(key)
        result: dict[str, Any] = {}
        for k, v in raw.items():
            try:
                result[k] = json.loads(v)
            except (json.JSONDecodeError, TypeError):
                result[k] = v
        return result

    async def hdel(self, key: str, *fields: str) -> int:
        client = await self._get_client()
        return await client.hdel(key, *fields)

    async def expire(self, key: str, seconds: int) -> None:
        client = await self._get_client()
        await client.expire(key, seconds)

    async def ttl(self, key: str) -> int:
        client = await self._get_client()
        return await client.ttl(key)

    async def delete(self, key: str) -> int:
        client = await self._get_client()
        return await client.delete(key)

    async def exists(self, key: str) -> bool:
        client = await self._get_client()
        return bool(await client.exists(key))

    # ---------- Redis Streams ----------

    async def xadd(self, stream: str, fields: dict[str, str]) -> str:
        client = await self._get_client()
        return await client.xadd(stream, fields)

    async def xreadgroup(
        self,
        group: str,
        consumer: str,
        streams: dict[str, str],
        count: int = 10,
        block: int = 1000,
    ) -> list:
        client = await self._get_client()
        try:
            return await client.xreadgroup(
                group, consumer, streams, count=count, block=block
            )
        except Exception as exc:
            logger.error(
                "xreadgroup error",
                layer="adapter",
                error=str(exc),
            )
            return []

    async def xack(self, stream: str, group: str, *message_ids: str) -> int:
        client = await self._get_client()
        return await client.xack(stream, group, *message_ids)

    async def xgroup_create(
        self, stream: str, group: str, mkstream: bool = True
    ) -> None:
        client = await self._get_client()
        try:
            await client.xgroup_create(stream, group, "$", mkstream=mkstream)
        except aioredis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


# Module-level singleton
_redis_adapter: Optional[RedisAdapter] = None


def get_redis_adapter() -> RedisAdapter:
    global _redis_adapter
    if _redis_adapter is None:
        _redis_adapter = RedisAdapter()
    return _redis_adapter
