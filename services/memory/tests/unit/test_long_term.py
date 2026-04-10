"""Unit tests for LongTermMemoryService."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from app.services.long_term import LongTermMemoryService


@pytest.fixture
def mysql(mock_mysql_adapter):
    return mock_mysql_adapter


@pytest.fixture
def faiss(mock_faiss_adapter):
    return mock_faiss_adapter


@pytest.fixture
def embedding(mock_embedding_service):
    return mock_embedding_service


@pytest.fixture
def service(mysql, faiss, embedding):
    return LongTermMemoryService(mysql=mysql, faiss=faiss, embedding=embedding)


class TestStore:
    @pytest.mark.asyncio
    async def test_store_embeds_text(self, service, embedding, faiss, mysql):
        await service.store(agent_id=1, content="pattern A", metadata={"importance": 0.8})
        embedding.embed.assert_called_once_with("pattern A")

    @pytest.mark.asyncio
    async def test_store_adds_to_faiss(self, service, embedding, faiss, mysql):
        vec = np.ones(768, dtype=np.float32)
        embedding.embed = AsyncMock(return_value=vec)

        await service.store(agent_id=1, content="pattern A", metadata={})

        faiss.add.assert_called_once()
        call_args = faiss.add.call_args
        assert call_args[0][0] == 1  # agent_id
        np.testing.assert_array_equal(call_args[0][1], vec)

    @pytest.mark.asyncio
    async def test_store_inserts_mysql_row(self, service, embedding, faiss, mysql):
        await service.store(agent_id=2, content="stored content", metadata={"task_id": "t1"})

        mysql.insert.assert_called_once()
        call_args = mysql.insert.call_args
        table = call_args[0][0]
        row = call_args[0][1]

        assert table == "agent_memory_extended"
        assert row["agent_id"] == 2
        assert row["memory_tier"] == "LONG_TERM"
        assert row["content"] == "stored content"
        assert "content_vector_id" in row

    @pytest.mark.asyncio
    async def test_store_returns_uuid(self, service):
        memory_id = await service.store(agent_id=1, content="test", metadata={})
        assert len(memory_id) == 36  # UUID


class TestSemanticSearch:
    @pytest.mark.asyncio
    async def test_returns_empty_for_empty_query(self, service, embedding, faiss):
        results = await service.semantic_search(agent_id=1, query="", k=5)
        assert results == []
        embedding.embed.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_faiss_hits(self, service, embedding, faiss, mysql):
        faiss.search = AsyncMock(return_value=[])
        results = await service.semantic_search(agent_id=1, query="test query", k=5)
        assert results == []

    @pytest.mark.asyncio
    async def test_retrieves_mysql_rows_by_faiss_ids(self, service, embedding, faiss, mysql):
        faiss.search = AsyncMock(return_value=[("mem-id-1", 0.95)])
        mysql.execute = AsyncMock(return_value=[
            {
                "content_vector_id": "mem-id-1",
                "content": "relevant content",
                "memory_tier": "LONG_TERM",
                "metadata": '{"task_id": "t1"}',
                "agent_id": 1,
            }
        ])

        results = await service.semantic_search(agent_id=1, query="query", k=5)

        assert len(results) == 1
        assert results[0]["content"] == "relevant content"
        assert results[0]["similarity_score"] == 0.95

    @pytest.mark.asyncio
    async def test_metadata_parsed_from_json(self, service, faiss, mysql):
        faiss.search = AsyncMock(return_value=[("mem-id-1", 0.9)])
        mysql.execute = AsyncMock(return_value=[
            {
                "content_vector_id": "mem-id-1",
                "content": "text",
                "memory_tier": "LONG_TERM",
                "metadata": '{"key": "value"}',
                "agent_id": 1,
            }
        ])

        results = await service.semantic_search(agent_id=1, query="q", k=5)

        assert results[0]["metadata"] == {"key": "value"}

    @pytest.mark.asyncio
    async def test_results_sorted_by_score_desc(self, service, faiss, mysql):
        faiss.search = AsyncMock(return_value=[
            ("id-1", 0.5),
            ("id-2", 0.9),
        ])
        mysql.execute = AsyncMock(return_value=[
            {"content_vector_id": "id-1", "content": "low", "memory_tier": "LONG_TERM", "metadata": "{}", "agent_id": 1},
            {"content_vector_id": "id-2", "content": "high", "memory_tier": "LONG_TERM", "metadata": "{}", "agent_id": 1},
        ])

        results = await service.semantic_search(agent_id=1, query="q", k=5)

        assert results[0]["similarity_score"] > results[1]["similarity_score"]
