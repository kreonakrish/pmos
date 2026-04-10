"""Unit tests for ShortTermMemoryService."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, call

import pytest

from app.services.short_term import ShortTermMemoryService, _agent_key


@pytest.fixture
def redis_adapter():
    adapter = AsyncMock()
    adapter.hgetall = AsyncMock(return_value={})
    adapter.hset = AsyncMock()
    adapter.hget = AsyncMock(return_value=None)
    adapter.hdel = AsyncMock(return_value=1)
    adapter.expire = AsyncMock()
    return adapter


@pytest.fixture
def service(redis_adapter):
    svc = ShortTermMemoryService(redis=redis_adapter)
    svc._ttl = 3600
    return svc


class TestWrite:
    @pytest.mark.asyncio
    async def test_write_calls_hset_with_entry(self, service, redis_adapter):
        memory_key = await service.write(agent_id=1, content="hello world", metadata={"session_id": "s1"})

        assert memory_key is not None
        assert len(memory_key) == 36  # UUID format

        redis_adapter.hset.assert_called_once()
        call_args = redis_adapter.hset.call_args
        key = call_args[0][0]
        field = call_args[0][1]
        value = call_args[0][2]

        assert key == _agent_key(1)
        assert field == memory_key
        assert value["content"] == "hello world"
        assert value["metadata"]["session_id"] == "s1"
        assert value["access_count"] == 0

    @pytest.mark.asyncio
    async def test_write_sets_ttl(self, service, redis_adapter):
        await service.write(agent_id=1, content="test", metadata={})
        redis_adapter.expire.assert_called_once_with(_agent_key(1), 3600)

    @pytest.mark.asyncio
    async def test_write_returns_unique_keys(self, service, redis_adapter):
        k1 = await service.write(agent_id=1, content="a", metadata={})
        k2 = await service.write(agent_id=1, content="b", metadata={})
        assert k1 != k2


class TestReadAll:
    @pytest.mark.asyncio
    async def test_read_all_returns_entries(self, service, redis_adapter):
        stored_entry = {
            "memory_key": "k1",
            "content": "context data",
            "metadata": {"session_id": "s1"},
            "access_count": 0,
            "created_at": "2026-01-01T00:00:00Z",
        }
        redis_adapter.hgetall = AsyncMock(return_value={"k1": stored_entry})

        results = await service.read_all(agent_id=1)

        assert len(results) == 1
        assert results[0]["content"] == "context data"

    @pytest.mark.asyncio
    async def test_read_all_increments_access_count(self, service, redis_adapter):
        stored_entry = {
            "memory_key": "k1",
            "content": "data",
            "metadata": {},
            "access_count": 2,
            "created_at": "2026-01-01T00:00:00Z",
        }
        redis_adapter.hgetall = AsyncMock(return_value={"k1": stored_entry})

        results = await service.read_all(agent_id=1)

        assert results[0]["access_count"] == 3  # incremented
        redis_adapter.hset.assert_called()  # updated back to Redis

    @pytest.mark.asyncio
    async def test_read_all_empty_returns_empty_list(self, service, redis_adapter):
        redis_adapter.hgetall = AsyncMock(return_value={})
        results = await service.read_all(agent_id=42)
        assert results == []


class TestGetSessionContext:
    @pytest.mark.asyncio
    async def test_filters_by_session_id(self, service, redis_adapter):
        entries = {
            "k1": {"content": "msg1", "metadata": {"session_id": "sess-A"}, "access_count": 0, "created_at": ""},
            "k2": {"content": "msg2", "metadata": {"session_id": "sess-B"}, "access_count": 0, "created_at": ""},
        }
        redis_adapter.hgetall = AsyncMock(return_value=entries)

        results = await service.get_session_context(agent_id=1, session_id="sess-A")

        assert len(results) == 1
        assert results[0]["content"] == "msg1"


class TestTTLBehavior:
    @pytest.mark.asyncio
    async def test_expired_entry_not_returned(self, service, redis_adapter):
        """Simulate TTL expiry: after TTL Redis returns empty hgetall."""
        # Write
        await service.write(agent_id=1, content="ephemeral", metadata={})

        # Simulate TTL expiry: Redis returns empty
        redis_adapter.hgetall = AsyncMock(return_value={})

        results = await service.read_all(agent_id=1)
        assert results == []


class TestDelete:
    @pytest.mark.asyncio
    async def test_delete_calls_hdel(self, service, redis_adapter):
        await service.delete(agent_id=1, memory_key="k1")
        redis_adapter.hdel.assert_called_once_with(_agent_key(1), "k1")
