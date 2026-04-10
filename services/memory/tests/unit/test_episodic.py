"""Unit tests for EpisodicMemoryService — store and retrieve execution episodes."""
from __future__ import annotations

from unittest.mock import AsyncMock

import numpy as np
import pytest

from app.services.episodic import EpisodicMemoryService, EPISODES_TABLE, MEMORY_TABLE


@pytest.fixture
def service(mock_mysql_adapter, mock_faiss_adapter, mock_embedding_service):
    return EpisodicMemoryService(
        mysql=mock_mysql_adapter,
        faiss=mock_faiss_adapter,
        embedding=mock_embedding_service,
    )


class TestStoreEpisode:
    @pytest.mark.asyncio
    async def test_store_inserts_mysql_row(self, service, mock_mysql_adapter):
        """store_episode inserts a row into execution_episodes table."""
        episode = {
            "task_id": "task-1",
            "task_description": "Analyze sales data",
            "output": "Sales increased by 10%",
            "steps": [{"step": "fetch data"}, {"step": "analyze"}],
            "score": 0.85,
            "outcome": "success",
            "metadata": {"domain": "finance"},
        }

        episode_id = await service.store_episode(agent_id=1, episode=episode)

        assert episode_id is not None
        assert len(episode_id) == 36  # UUID

        # Should insert into execution_episodes
        calls = mock_mysql_adapter.insert.call_args_list
        assert len(calls) == 2  # episodes table + agent_memory_extended

        ep_call = calls[0]
        assert ep_call[0][0] == EPISODES_TABLE
        ep_data = ep_call[0][1]
        assert ep_data["episode_id"] == episode_id
        assert ep_data["agent_id"] == 1
        assert ep_data["task_description"] == "Analyze sales data"
        assert ep_data["score"] == 0.85

    @pytest.mark.asyncio
    async def test_store_adds_faiss_embedding(self, service, mock_faiss_adapter, mock_embedding_service):
        """store_episode embeds the task+output and adds vector to FAISS."""
        episode = {
            "task_description": "Test task",
            "output": "Test output",
        }

        episode_id = await service.store_episode(agent_id=42, episode=episode)

        mock_embedding_service.embed.assert_called_once()
        embed_text = mock_embedding_service.embed.call_args[0][0]
        assert "Test task" in embed_text
        assert "Test output" in embed_text

        mock_faiss_adapter.add.assert_called_once_with(42, mock_embedding_service.embed.return_value, episode_id)

    @pytest.mark.asyncio
    async def test_store_writes_memory_extended_row(self, service, mock_mysql_adapter):
        """store_episode also inserts a cross-reference into agent_memory_extended."""
        episode = {
            "task_description": "Cross-ref test",
            "output": "Some output",
            "score": 0.5,
        }

        episode_id = await service.store_episode(agent_id=1, episode=episode)

        calls = mock_mysql_adapter.insert.call_args_list
        mem_call = calls[1]
        assert mem_call[0][0] == MEMORY_TABLE
        mem_data = mem_call[0][1]
        assert mem_data["agent_id"] == 1
        assert mem_data["memory_tier"] == "EPISODIC"
        assert mem_data["content_vector_id"] == episode_id

    @pytest.mark.asyncio
    async def test_store_returns_unique_ids(self, service):
        """Each call to store_episode returns a unique episode_id."""
        id1 = await service.store_episode(agent_id=1, episode={"task_description": "a", "output": "b"})
        id2 = await service.store_episode(agent_id=1, episode={"task_description": "c", "output": "d"})
        assert id1 != id2


class TestRetrieveSimilar:
    @pytest.mark.asyncio
    async def test_retrieve_returns_episodes_by_similarity(
        self, service, mock_faiss_adapter, mock_mysql_adapter, mock_embedding_service
    ):
        """retrieve_similar returns episodes ranked by semantic similarity."""
        mock_faiss_adapter.search = AsyncMock(return_value=[
            ("ep-1", 0.95),
            ("ep-2", 0.80),
        ])
        mock_mysql_adapter.execute = AsyncMock(return_value=[
            {
                "episode_id": "ep-1",
                "agent_id": 1,
                "task_description": "First task",
                "steps_taken": "[]",
                "output": "First output",
                "score": 0.9,
                "outcome": "success",
                "input_context": "{}",
            },
            {
                "episode_id": "ep-2",
                "agent_id": 1,
                "task_description": "Second task",
                "steps_taken": "[]",
                "output": "Second output",
                "score": 0.7,
                "outcome": "partial",
                "input_context": "{}",
            },
        ])

        results = await service.retrieve_similar(agent_id=1, query="sales analysis", k=2)

        assert len(results) == 2
        # Sorted by similarity_score descending
        assert results[0]["similarity_score"] == 0.95
        assert results[0]["task_description"] == "First task"
        assert results[1]["similarity_score"] == 0.80

        mock_embedding_service.embed.assert_called_once_with("sales analysis")

    @pytest.mark.asyncio
    async def test_retrieve_empty_query_returns_empty(self, service):
        """An empty/whitespace query returns an empty list immediately."""
        results = await service.retrieve_similar(agent_id=1, query="", k=5)
        assert results == []

        results2 = await service.retrieve_similar(agent_id=1, query="   ", k=5)
        assert results2 == []

    @pytest.mark.asyncio
    async def test_retrieve_no_faiss_hits_returns_empty(
        self, service, mock_faiss_adapter, mock_embedding_service
    ):
        """When FAISS returns no hits, returns empty list."""
        mock_faiss_adapter.search = AsyncMock(return_value=[])

        results = await service.retrieve_similar(agent_id=1, query="something", k=5)
        assert results == []

    @pytest.mark.asyncio
    async def test_retrieve_falls_back_to_memory_table(
        self, service, mock_faiss_adapter, mock_mysql_adapter
    ):
        """When episodes table has no rows for an ID, falls back to agent_memory_extended."""
        mock_faiss_adapter.search = AsyncMock(return_value=[
            ("ep-missing", 0.85),
        ])
        # First query (execution_episodes) returns empty
        # Second query (agent_memory_extended) returns a row
        mock_mysql_adapter.execute = AsyncMock(side_effect=[
            [],  # episodes table
            [    # memory_extended fallback
                {
                    "content_vector_id": "ep-missing",
                    "content": "Task: fallback content\nOutput: fallback output",
                    "memory_tier": "EPISODIC",
                    "metadata": "{}",
                    "agent_id": 1,
                },
            ],
        ])

        results = await service.retrieve_similar(agent_id=1, query="fallback test", k=2)

        assert len(results) == 1
        assert results[0]["similarity_score"] == 0.85

    @pytest.mark.asyncio
    async def test_retrieve_respects_k_limit(
        self, service, mock_faiss_adapter, mock_mysql_adapter
    ):
        """Results are limited to k entries."""
        mock_faiss_adapter.search = AsyncMock(return_value=[
            ("ep-1", 0.9),
            ("ep-2", 0.8),
            ("ep-3", 0.7),
        ])
        mock_mysql_adapter.execute = AsyncMock(return_value=[
            {"episode_id": "ep-1", "task_description": "t1", "steps_taken": "[]", "output": "", "score": 0.9, "outcome": "", "input_context": "{}"},
            {"episode_id": "ep-2", "task_description": "t2", "steps_taken": "[]", "output": "", "score": 0.8, "outcome": "", "input_context": "{}"},
            {"episode_id": "ep-3", "task_description": "t3", "steps_taken": "[]", "output": "", "score": 0.7, "outcome": "", "input_context": "{}"},
        ])

        results = await service.retrieve_similar(agent_id=1, query="test", k=2)

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_retrieve_parses_json_fields(
        self, service, mock_faiss_adapter, mock_mysql_adapter
    ):
        """steps_taken and input_context fields are parsed from JSON strings."""
        mock_faiss_adapter.search = AsyncMock(return_value=[("ep-1", 0.9)])
        mock_mysql_adapter.execute = AsyncMock(return_value=[
            {
                "episode_id": "ep-1",
                "task_description": "json test",
                "steps_taken": '[{"step": "analyze"}]',
                "output": "done",
                "score": 0.9,
                "outcome": "success",
                "input_context": '{"domain": "finance"}',
            },
        ])

        results = await service.retrieve_similar(agent_id=1, query="json", k=5)

        assert results[0]["steps"] == [{"step": "analyze"}]
        assert results[0]["metadata"] == {"domain": "finance"}
