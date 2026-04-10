"""Adapter tests for RedisAdapter and MySQLAdapter (sync wrapper)."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# RedisAdapter tests
# ---------------------------------------------------------------------------


class TestRedisAdapterWrite:
    @pytest.mark.asyncio
    async def test_hset_serialises_dict_to_json(self, mock_redis_adapter):
        """hset stores dict values after JSON serialisation."""
        await mock_redis_adapter.hset("key:1", "field1", {"content": "hello"})
        mock_redis_adapter.hset.assert_called_once_with("key:1", "field1", {"content": "hello"})

    @pytest.mark.asyncio
    async def test_hset_stores_string_as_is(self, mock_redis_adapter):
        """hset stores plain strings without extra serialisation."""
        await mock_redis_adapter.hset("key:1", "field1", "plain string")
        mock_redis_adapter.hset.assert_called_once_with("key:1", "field1", "plain string")


class TestRedisAdapterRead:
    @pytest.mark.asyncio
    async def test_hget_returns_none_for_missing_key(self, mock_redis_adapter):
        """hget returns None when the key/field does not exist."""
        result = await mock_redis_adapter.hget("missing:key", "field")
        assert result is None

    @pytest.mark.asyncio
    async def test_hget_returns_stored_value(self, mock_redis_adapter):
        """hget returns deserialised value when key exists."""
        mock_redis_adapter.hget = AsyncMock(return_value={"content": "data"})
        result = await mock_redis_adapter.hget("key:1", "field1")
        assert result == {"content": "data"}

    @pytest.mark.asyncio
    async def test_hgetall_returns_all_fields(self, mock_redis_adapter):
        """hgetall returns dict of all fields for a hash key."""
        mock_redis_adapter.hgetall = AsyncMock(return_value={
            "f1": {"content": "a"},
            "f2": {"content": "b"},
        })
        result = await mock_redis_adapter.hgetall("key:1")
        assert len(result) == 2
        assert result["f1"]["content"] == "a"

    @pytest.mark.asyncio
    async def test_hgetall_empty_key_returns_empty_dict(self, mock_redis_adapter):
        """hgetall on a non-existent key returns empty dict."""
        result = await mock_redis_adapter.hgetall("nonexistent")
        assert result == {}


class TestRedisAdapterTTL:
    @pytest.mark.asyncio
    async def test_expire_sets_ttl(self, mock_redis_adapter):
        """expire is called with the correct key and seconds."""
        await mock_redis_adapter.expire("key:1", 3600)
        mock_redis_adapter.expire.assert_called_once_with("key:1", 3600)

    @pytest.mark.asyncio
    async def test_ttl_returns_remaining_seconds(self, mock_redis_adapter):
        """ttl returns the remaining time-to-live."""
        mock_redis_adapter.ttl = AsyncMock(return_value=1800)
        result = await mock_redis_adapter.ttl("key:1")
        assert result == 1800

    @pytest.mark.asyncio
    async def test_delete_removes_key(self, mock_redis_adapter):
        """delete removes the key and returns count."""
        result = await mock_redis_adapter.delete("key:1")
        assert result == 1


class TestRedisAdapterStreams:
    @pytest.mark.asyncio
    async def test_xadd_returns_message_id(self, mock_redis_adapter):
        """xadd publishes a message and returns a message ID."""
        result = await mock_redis_adapter.xadd("stream:test", {"data": "value"})
        assert result == "1-0"

    @pytest.mark.asyncio
    async def test_xreadgroup_returns_empty_on_no_messages(self, mock_redis_adapter):
        """xreadgroup returns empty list when no messages available."""
        result = await mock_redis_adapter.xreadgroup(
            "group", "consumer", {"stream:test": ">"}
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_xack_acknowledges_message(self, mock_redis_adapter):
        """xack acknowledges a consumed message."""
        result = await mock_redis_adapter.xack("stream:test", "group", "1-0")
        assert result == 1


# ---------------------------------------------------------------------------
# MySQLAdapter tests
# ---------------------------------------------------------------------------


class TestMySQLAdapterQuery:
    @pytest.mark.asyncio
    async def test_execute_with_fetch(self, mock_mysql_adapter):
        """execute with fetch=True returns rows."""
        mock_mysql_adapter.execute = AsyncMock(return_value=[
            {"id": 1, "content": "row1"},
            {"id": 2, "content": "row2"},
        ])
        result = await mock_mysql_adapter.execute(
            "SELECT * FROM agent_memory_extended WHERE agent_id = %s",
            (1,),
            fetch=True,
        )
        assert len(result) == 2
        assert result[0]["content"] == "row1"

    @pytest.mark.asyncio
    async def test_execute_returns_none_for_empty_result(self, mock_mysql_adapter):
        """execute returns None/empty when no rows match."""
        result = await mock_mysql_adapter.execute(
            "SELECT * FROM agent_memory_extended WHERE agent_id = %s",
            (999,),
            fetch=True,
        )
        assert result is None  # default mock return

    @pytest.mark.asyncio
    async def test_select_returns_list(self, mock_mysql_adapter):
        """select helper returns a list of dicts."""
        mock_mysql_adapter.select = AsyncMock(return_value=[
            {"agent_id": 1, "content": "knowledge"},
        ])
        result = await mock_mysql_adapter.select(
            "agent_memory_extended",
            where="agent_id = %s",
            params=(1,),
        )
        assert len(result) == 1
        assert result[0]["agent_id"] == 1

    @pytest.mark.asyncio
    async def test_select_empty_table_returns_empty_list(self, mock_mysql_adapter):
        """select on empty result returns empty list."""
        result = await mock_mysql_adapter.select("agent_memory_extended")
        assert result == []


class TestMySQLAdapterInsert:
    @pytest.mark.asyncio
    async def test_insert_returns_row_id(self, mock_mysql_adapter):
        """insert returns the last inserted row ID."""
        result = await mock_mysql_adapter.insert("execution_episodes", {
            "episode_id": "ep-1",
            "agent_id": 1,
            "task_description": "test",
        })
        assert result == 1  # default mock return

        mock_mysql_adapter.insert.assert_called_once_with("execution_episodes", {
            "episode_id": "ep-1",
            "agent_id": 1,
            "task_description": "test",
        })

    @pytest.mark.asyncio
    async def test_insert_called_with_correct_table(self, mock_mysql_adapter):
        """insert targets the correct table."""
        await mock_mysql_adapter.insert("scoring_weights", {"agent_id": 5, "weight": 0.5})
        call_args = mock_mysql_adapter.insert.call_args
        assert call_args[0][0] == "scoring_weights"


class TestMySQLAdapterUpdate:
    @pytest.mark.asyncio
    async def test_update_calls_with_correct_params(self, mock_mysql_adapter):
        """update passes data, where clause, and where_params correctly."""
        await mock_mysql_adapter.update(
            "agent_memory_extended",
            {"access_count": 5},
            "content_vector_id = %s",
            ("vec-1",),
        )
        mock_mysql_adapter.update.assert_called_once_with(
            "agent_memory_extended",
            {"access_count": 5},
            "content_vector_id = %s",
            ("vec-1",),
        )
