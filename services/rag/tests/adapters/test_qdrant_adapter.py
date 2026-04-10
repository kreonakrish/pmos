"""Tests for QdrantAdapter — all Qdrant client calls are mocked."""
import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.adapters.qdrant_adapter as qdrant_mod
from app.adapters.base import SearchResult


class _FakeSettings:
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_api_key: str = ""
    qdrant_prefer_grpc: bool = False
    qdrant_collection_prefix: str = "test"
    embedding_dimension: int = 8


@dataclass
class _FakePointStruct:
    """Stand-in for qdrant_client.models.PointStruct when the package is absent."""
    id: str
    vector: list
    payload: dict


# Patch PointStruct for the entire module so it's available at call time
_orig_point_struct = qdrant_mod.PointStruct
if _orig_point_struct is None:
    qdrant_mod.PointStruct = _FakePointStruct


@pytest.fixture
def mock_qdrant_client():
    client = AsyncMock()
    return client


@pytest.fixture
def adapter(mock_qdrant_client):
    with patch.object(qdrant_mod, "AsyncQdrantClient", return_value=mock_qdrant_client):
        adp = qdrant_mod.QdrantAdapter(_FakeSettings())
    # Ensure the patched client is in place
    adp._client = mock_qdrant_client
    return adp


# ---------------------------------------------------------------------------
# Test: upsert calls client correctly
# ---------------------------------------------------------------------------


def test_upsert_calls_client(adapter, mock_qdrant_client):
    vector = [0.1] * 8
    metadata = {"content": "hello world", "source": "test"}

    asyncio.run(adapter.upsert("doc_1", vector, metadata))

    mock_qdrant_client.upsert.assert_awaited_once()
    call_kwargs = mock_qdrant_client.upsert.call_args
    assert call_kwargs.kwargs["collection_name"] == "test_documents"
    points = call_kwargs.kwargs["points"]
    assert len(points) == 1
    assert points[0].id == "doc_1"
    assert points[0].vector == vector
    assert points[0].payload == metadata


# ---------------------------------------------------------------------------
# Test: search returns SearchResult list
# ---------------------------------------------------------------------------


def test_search_returns_search_results(adapter, mock_qdrant_client):
    # Build mock response objects
    hit1 = MagicMock()
    hit1.id = "id_1"
    hit1.score = 0.95
    hit1.payload = {"content": "result one", "extra": "a"}

    hit2 = MagicMock()
    hit2.id = "id_2"
    hit2.score = 0.80
    hit2.payload = {"content": "result two", "extra": "b"}

    mock_qdrant_client.search.return_value = [hit1, hit2]

    query_vec = [0.1] * 8
    results = asyncio.run(adapter.search(query_vec, k=5))

    assert len(results) == 2
    assert isinstance(results[0], SearchResult)
    assert results[0].id == "id_1"
    assert results[0].content == "result one"
    assert results[0].score == 0.95
    assert results[0].source == "qdrant"
    assert results[0].metadata == {"content": "result one", "extra": "a"}

    assert results[1].id == "id_2"
    assert results[1].score == 0.80

    mock_qdrant_client.search.assert_awaited_once_with(
        collection_name="test_documents",
        query_vector=query_vec,
        limit=5,
    )


def test_search_empty_results(adapter, mock_qdrant_client):
    mock_qdrant_client.search.return_value = []

    results = asyncio.run(adapter.search([0.1] * 8, k=3))
    assert results == []


# ---------------------------------------------------------------------------
# Test: health_check
# ---------------------------------------------------------------------------


def test_health_check_success(adapter, mock_qdrant_client):
    mock_qdrant_client.get_collections.return_value = MagicMock(collections=[])

    ok = asyncio.run(adapter.health_check())
    assert ok is True
    mock_qdrant_client.get_collections.assert_awaited_once()


def test_health_check_failure(adapter, mock_qdrant_client):
    mock_qdrant_client.get_collections.side_effect = ConnectionError("unreachable")

    ok = asyncio.run(adapter.health_check())
    assert ok is False


# ---------------------------------------------------------------------------
# Test: client exception propagates on upsert/search
# ---------------------------------------------------------------------------


def test_upsert_exception_propagates(adapter, mock_qdrant_client):
    mock_qdrant_client.upsert.side_effect = RuntimeError("connection lost")

    with pytest.raises(RuntimeError, match="connection lost"):
        asyncio.run(adapter.upsert("x", [0.1] * 8, {}))


def test_search_exception_propagates(adapter, mock_qdrant_client):
    mock_qdrant_client.search.side_effect = RuntimeError("timeout")

    with pytest.raises(RuntimeError, match="timeout"):
        asyncio.run(adapter.search([0.1] * 8, k=3))
