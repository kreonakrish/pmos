"""Tests for WeaviateAdapter — all Weaviate client calls are mocked."""
import asyncio
import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.adapters.base import SearchResult


class _FakeSettings:
    weaviate_url: str = "http://localhost:8080"
    weaviate_api_key: str = ""


@pytest.fixture
def mock_weaviate_client():
    client = MagicMock()
    client.collections = MagicMock()
    client.is_ready.return_value = True
    return client


@pytest.fixture
def adapter(mock_weaviate_client):
    with patch("app.adapters.weaviate_adapter.weaviate") as mock_weaviate_mod:
        mock_weaviate_mod.connect_to_custom.return_value = mock_weaviate_client
        # Also patch AuthApiKey since settings has no key
        with patch("app.adapters.weaviate_adapter.AuthApiKey", MagicMock()):
            from app.adapters.weaviate_adapter import WeaviateAdapter

            adp = WeaviateAdapter(_FakeSettings())

    adp._client = mock_weaviate_client
    return adp


# ---------------------------------------------------------------------------
# Test: upsert calls client correctly
# ---------------------------------------------------------------------------


def test_upsert_calls_collection_insert(adapter, mock_weaviate_client):
    mock_collection = MagicMock()
    mock_weaviate_client.collections.get.return_value = mock_collection

    vector = [0.1] * 8
    metadata = {"content": "hello", "tag": "test"}

    asyncio.run(adapter.upsert("doc_1", vector, metadata))

    mock_weaviate_client.collections.get.assert_called_once_with("PmosDocument")
    mock_collection.data.insert.assert_called_once()
    call_kwargs = mock_collection.data.insert.call_args.kwargs
    assert call_kwargs["properties"] == metadata
    assert call_kwargs["vector"] == vector


# ---------------------------------------------------------------------------
# Test: search returns SearchResult list
# ---------------------------------------------------------------------------


def test_search_returns_search_results(adapter, mock_weaviate_client):
    obj1 = MagicMock()
    obj1.uuid = uuid.uuid4()
    obj1.properties = {"content": "result one", "extra": "a"}
    obj1.metadata = MagicMock()
    obj1.metadata.score = 0.92

    obj2 = MagicMock()
    obj2.uuid = uuid.uuid4()
    obj2.properties = {"content": "result two", "extra": "b"}
    obj2.metadata = MagicMock()
    obj2.metadata.score = 0.75

    mock_collection = MagicMock()
    mock_response = MagicMock()
    mock_response.objects = [obj1, obj2]
    mock_collection.query.near_vector.return_value = mock_response
    mock_weaviate_client.collections.get.return_value = mock_collection

    query_vec = [0.2] * 8
    results = asyncio.run(adapter.search(query_vec, k=5))

    assert len(results) == 2
    assert isinstance(results[0], SearchResult)
    assert results[0].content == "result one"
    assert results[0].score == 0.92
    assert results[0].source == "weaviate"

    assert results[1].content == "result two"
    assert results[1].score == 0.75


def test_search_empty_results(adapter, mock_weaviate_client):
    mock_collection = MagicMock()
    mock_response = MagicMock()
    mock_response.objects = []
    mock_collection.query.near_vector.return_value = mock_response
    mock_weaviate_client.collections.get.return_value = mock_collection

    results = asyncio.run(adapter.search([0.1] * 8, k=3))
    assert results == []


# ---------------------------------------------------------------------------
# Test: health_check
# ---------------------------------------------------------------------------


def test_health_check_success(adapter, mock_weaviate_client):
    mock_weaviate_client.is_ready.return_value = True

    ok = asyncio.run(adapter.health_check())
    assert ok is True


def test_health_check_failure(adapter, mock_weaviate_client):
    mock_weaviate_client.is_ready.side_effect = ConnectionError("unreachable")

    ok = asyncio.run(adapter.health_check())
    assert ok is False


def test_health_check_returns_false(adapter, mock_weaviate_client):
    mock_weaviate_client.is_ready.return_value = False

    ok = asyncio.run(adapter.health_check())
    assert ok is False
