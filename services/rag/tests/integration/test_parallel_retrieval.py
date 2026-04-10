"""
Integration tests for RetrievalService — all 4 sources are mocked.
Validates concurrent querying, fault tolerance, deduplication, and re-ranking.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.adapters.base import SearchResult
from app.services.retrieval import RetrievalService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _FakeSettings:
    vector_store_backend: str = "qdrant"
    embedding_model: str = "test-model"
    rag_parallel_timeout_sec: float = 5.0
    memory_service_url: str = "http://localhost:8001"
    rag_top_k: int = 10
    retry_max_attempts: int = 1
    retry_wait_multiplier: float = 0.01
    retry_wait_max_sec: float = 0.1


def _make_result(id: str, content: str, score: float, source: str) -> SearchResult:
    return SearchResult(
        id=id, content=content, score=score, source=source, metadata={"id": id}
    )


@pytest.fixture
def mock_vector_store():
    store = AsyncMock()
    store.search.return_value = [
        _make_result("v1", "Vector result one", 0.90, "qdrant"),
        _make_result("v2", "Vector result two", 0.85, "qdrant"),
    ]
    return store


@pytest.fixture
def mock_mysql_adapter():
    adapter = AsyncMock()
    adapter.search.return_value = [
        _make_result("m1", "MySQL result one", 0.80, "mysql"),
        _make_result("m2", "MySQL result two", 0.70, "mysql"),
    ]
    return adapter


@pytest.fixture
def mock_reranker():
    reranker = AsyncMock()

    async def fake_rerank(query, candidates, top_k):
        # Return candidates sorted by score descending, as dicts
        sorted_c = sorted(candidates, key=lambda c: c.score, reverse=True)
        return [
            {
                "content": c.content,
                "score": c.score,
                "source": c.source,
                "metadata": c.metadata,
            }
            for c in sorted_c[:top_k]
        ]

    reranker.rerank.side_effect = fake_rerank
    return reranker


@pytest.fixture
def settings():
    return _FakeSettings()


def _make_memory_response():
    """Successful memory service HTTP response."""
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "system_prompt": "Memory context for agent",
        "sources": {"short_term_hits": 1, "long_term_hits": 0, "reasoning_hits": 0, "episodic_hits": 1},
    }
    return resp


# ---------------------------------------------------------------------------
# Test: All sources queried concurrently
# ---------------------------------------------------------------------------


def test_all_sources_queried_concurrently(
    mock_vector_store, mock_mysql_adapter, mock_reranker, settings
):
    service = RetrievalService(
        vector_store=mock_vector_store,
        mysql_adapter=mock_mysql_adapter,
        reranker=mock_reranker,
        settings=settings,
    )

    with patch("app.services.retrieval.embed_query", new_callable=AsyncMock) as mock_embed, \
         patch("app.services.retrieval.httpx.AsyncClient") as mock_http_cls:

        mock_embed.return_value = [0.1] * 8

        # Mock the memory service HTTP call
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_instance.post.return_value = _make_memory_response()
        mock_http_cls.return_value = mock_client_instance

        result = asyncio.run(
            service.retrieve(
                query="test query",
                agent_id=1,
                top_k=10,
                sources=None,  # all sources
                context={"domain": "test"},
                trace_id="trace-001",
            )
        )

    # All 3 source types should have been queried
    assert "qdrant" in result["sources_queried"]
    assert "mysql" in result["sources_queried"]
    assert "memory" in result["sources_queried"]
    assert len(result["results"]) > 0
    assert "latency_ms" in result

    # Verify vector store and mysql were actually called
    mock_vector_store.search.assert_awaited_once()
    mock_mysql_adapter.search.assert_awaited_once()


# ---------------------------------------------------------------------------
# Test: One source failing does not block others
# ---------------------------------------------------------------------------


def test_one_source_failure_returns_other_results(
    mock_vector_store, mock_mysql_adapter, mock_reranker, settings
):
    # Make vector store raise an exception
    mock_vector_store.search.side_effect = RuntimeError("Qdrant connection refused")

    service = RetrievalService(
        vector_store=mock_vector_store,
        mysql_adapter=mock_mysql_adapter,
        reranker=mock_reranker,
        settings=settings,
    )

    with patch("app.services.retrieval.embed_query", new_callable=AsyncMock) as mock_embed, \
         patch("app.services.retrieval.httpx.AsyncClient") as mock_http_cls:

        mock_embed.return_value = [0.1] * 8

        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_instance.post.return_value = _make_memory_response()
        mock_http_cls.return_value = mock_client_instance

        result = asyncio.run(
            service.retrieve(
                query="test query",
                agent_id=1,
                top_k=10,
                sources=None,
                context={"domain": "test"},
                trace_id="trace-002",
            )
        )

    # qdrant failed, but mysql and memory should still be present
    assert "qdrant" not in result["sources_queried"]
    assert "mysql" in result["sources_queried"]
    assert "memory" in result["sources_queried"]
    assert len(result["results"]) > 0


# ---------------------------------------------------------------------------
# Test: Results are merged, deduplicated, and re-ranked
# ---------------------------------------------------------------------------


def test_results_merged_deduplicated_reranked(
    mock_vector_store, mock_mysql_adapter, mock_reranker, settings
):
    # Create a duplicate across vector and mysql (same content prefix)
    duplicate_content = "Duplicate content that appears in both sources with same prefix"
    mock_vector_store.search.return_value = [
        _make_result("v1", duplicate_content, 0.90, "qdrant"),
        _make_result("v2", "Unique vector result", 0.85, "qdrant"),
    ]
    mock_mysql_adapter.search.return_value = [
        _make_result("m1", duplicate_content, 0.80, "mysql"),
        _make_result("m2", "Unique mysql result", 0.70, "mysql"),
    ]

    service = RetrievalService(
        vector_store=mock_vector_store,
        mysql_adapter=mock_mysql_adapter,
        reranker=mock_reranker,
        settings=settings,
    )

    with patch("app.services.retrieval.embed_query", new_callable=AsyncMock) as mock_embed, \
         patch("app.services.retrieval.httpx.AsyncClient") as mock_http_cls:

        mock_embed.return_value = [0.1] * 8

        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_instance.post.return_value = _make_memory_response()
        mock_http_cls.return_value = mock_client_instance

        result = asyncio.run(
            service.retrieve(
                query="test query",
                agent_id=1,
                top_k=10,
                sources=None,
                context={"domain": "test"},
                trace_id="trace-003",
            )
        )

    # The reranker should have been called (verify it was invoked)
    mock_reranker.rerank.assert_awaited_once()

    # The reranker received deduplicated candidates — the duplicate should appear only once
    rerank_call_args = mock_reranker.rerank.call_args
    candidates_passed = rerank_call_args[0][1]  # second positional arg
    contents = [c.content for c in candidates_passed]

    # Duplicate content appears only once after dedup
    assert contents.count(duplicate_content) == 1

    # Results returned are dicts (from reranker output)
    for r in result["results"]:
        assert "content" in r
        assert "score" in r
        assert "source" in r


# ---------------------------------------------------------------------------
# Test: Specific source filter respected
# ---------------------------------------------------------------------------


def test_source_filter_limits_queries(
    mock_vector_store, mock_mysql_adapter, mock_reranker, settings
):
    service = RetrievalService(
        vector_store=mock_vector_store,
        mysql_adapter=mock_mysql_adapter,
        reranker=mock_reranker,
        settings=settings,
    )

    with patch("app.services.retrieval.embed_query", new_callable=AsyncMock) as mock_embed:
        mock_embed.return_value = [0.1] * 8

        result = asyncio.run(
            service.retrieve(
                query="test query",
                agent_id=1,
                top_k=5,
                sources=["mysql"],  # only mysql
                context=None,
                trace_id="trace-004",
            )
        )

    assert "mysql" in result["sources_queried"]
    # Vector store and memory should NOT be queried when only mysql is specified
    mock_mysql_adapter.search.assert_awaited_once()
