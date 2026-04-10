"""Tests for PineconeAdapter — all Pinecone client calls are mocked."""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from app.adapters.base import SearchResult


class _FakeSettings:
    pinecone_api_key: str = "fake-key"
    pinecone_index: str = "test-index"


@pytest.fixture
def mock_index():
    return MagicMock()


@pytest.fixture
def adapter(mock_index):
    mock_pc_instance = MagicMock()
    mock_pc_instance.Index.return_value = mock_index

    with patch("app.adapters.pinecone_adapter.Pinecone", return_value=mock_pc_instance):
        from app.adapters.pinecone_adapter import PineconeAdapter

        adp = PineconeAdapter(_FakeSettings())

    adp._index = mock_index
    adp._index_name = "test-index"
    return adp


# ---------------------------------------------------------------------------
# Test: upsert calls client correctly
# ---------------------------------------------------------------------------


def test_upsert_calls_index(adapter, mock_index):
    vector = [0.1] * 8
    metadata = {"content": "hello", "tag": "test"}

    asyncio.run(adapter.upsert("doc_1", vector, metadata))

    mock_index.upsert.assert_called_once_with(
        vectors=[("doc_1", vector, metadata)]
    )


# ---------------------------------------------------------------------------
# Test: search returns SearchResult list
# ---------------------------------------------------------------------------


def test_search_returns_search_results(adapter, mock_index):
    mock_index.query.return_value = {
        "matches": [
            {"id": "id_1", "score": 0.92, "metadata": {"content": "result one"}},
            {"id": "id_2", "score": 0.78, "metadata": {"content": "result two"}},
        ]
    }

    query_vec = [0.2] * 8
    results = asyncio.run(adapter.search(query_vec, k=5))

    assert len(results) == 2
    assert isinstance(results[0], SearchResult)
    assert results[0].id == "id_1"
    assert results[0].content == "result one"
    assert results[0].score == 0.92
    assert results[0].source == "pinecone"

    assert results[1].id == "id_2"
    assert results[1].score == 0.78

    mock_index.query.assert_called_once_with(
        vector=query_vec, top_k=5, include_metadata=True
    )


def test_search_with_filters(adapter, mock_index):
    mock_index.query.return_value = {"matches": []}

    filters = {"domain": "finance"}
    results = asyncio.run(adapter.search([0.1] * 8, k=3, filters=filters))

    assert results == []
    call_kwargs = mock_index.query.call_args.kwargs
    assert call_kwargs["filter"] == filters


def test_search_empty_matches(adapter, mock_index):
    mock_index.query.return_value = {"matches": []}

    results = asyncio.run(adapter.search([0.1] * 8, k=3))
    assert results == []


# ---------------------------------------------------------------------------
# Test: health_check
# ---------------------------------------------------------------------------


def test_health_check_success(adapter, mock_index):
    mock_index.describe_index_stats.return_value = {"total_vector_count": 100}

    ok = asyncio.run(adapter.health_check())
    assert ok is True
    mock_index.describe_index_stats.assert_called_once()


def test_health_check_failure(adapter, mock_index):
    mock_index.describe_index_stats.side_effect = ConnectionError("unreachable")

    ok = asyncio.run(adapter.health_check())
    assert ok is False
