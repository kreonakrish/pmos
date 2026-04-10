"""SHORT_TERM memory service — Redis hash with TTL per agent."""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

from app.adapters.redis_adapter import RedisAdapter, get_redis_adapter
from app.config import settings
from app.utils.logger import get_logger, new_span_id

logger = get_logger()

SHORT_TERM_KEY_PREFIX = "memory:agent"


def _agent_key(agent_id: int) -> str:
    return f"{SHORT_TERM_KEY_PREFIX}:{agent_id}:short_term"


class ShortTermMemoryService:
    def __init__(self, redis: RedisAdapter | None = None) -> None:
        self._redis = redis or get_redis_adapter()
        self._ttl = settings.short_term_ttl_sec

    async def write(self, agent_id: int, content: str, metadata: dict[str, Any]) -> str:
        """Store content in Redis hash with TTL. Returns the memory_key (field name)."""
        span_id = new_span_id()
        memory_key = str(uuid.uuid4())
        key = _agent_key(agent_id)

        entry = {
            "memory_key": memory_key,
            "content": content,
            "metadata": metadata,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "access_count": 0,
        }

        await self._redis.hset(key, memory_key, entry)
        await self._redis.expire(key, self._ttl)

        logger.info(
            "SHORT_TERM write",
            layer="service",
            agent_id=agent_id,
            memory_key=memory_key,
            span_id=span_id,
        )
        return memory_key

    async def read_all(self, agent_id: int) -> list[dict[str, Any]]:
        """Return all short-term memory entries for the agent."""
        key = _agent_key(agent_id)
        raw = await self._redis.hgetall(key)
        results: list[dict[str, Any]] = []
        for field, value in raw.items():
            entry = value if isinstance(value, dict) else {}
            entry["_field"] = field
            results.append(entry)

        # Increment access_count for returned entries
        for entry in results:
            field = entry.pop("_field", None)
            if field:
                entry["access_count"] = entry.get("access_count", 0) + 1
                await self._redis.hset(key, field, entry)

        return results

    async def get_session_context(self, agent_id: int, session_id: str) -> list[dict[str, Any]]:
        """Return entries whose metadata.session_id matches session_id."""
        all_entries = await self.read_all(agent_id)
        return [
            e for e in all_entries
            if e.get("metadata", {}).get("session_id") == session_id
        ]

    async def delete(self, agent_id: int, memory_key: str) -> None:
        """Delete a specific field from the agent's hash."""
        key = _agent_key(agent_id)
        await self._redis.hdel(key, memory_key)

    async def get_access_counts(self, agent_id: int) -> dict[str, int]:
        """Return {memory_key: access_count} for distillation checks."""
        key = _agent_key(agent_id)
        raw = await self._redis.hgetall(key)
        return {
            field: (v.get("access_count", 0) if isinstance(v, dict) else 0)
            for field, v in raw.items()
        }

    async def get_entry(self, agent_id: int, memory_key: str) -> dict[str, Any] | None:
        """Fetch a single entry by memory_key."""
        key = _agent_key(agent_id)
        value = await self._redis.hget(key, memory_key)
        if value is None:
            return None
        return value if isinstance(value, dict) else {}
