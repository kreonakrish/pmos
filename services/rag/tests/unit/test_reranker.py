"""Unit tests for the Reranker — mocks the CrossEncoder model."""
import asyncio
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.adapters.base import SearchResult
from app.services.reranker import Reranker


def _make_candidates(n: int) -> list[SearchResult]:
    return [
        SearchResult(
            id=str(i),
            content=f"Candidate document number {i}",
            score=float(i) / n,
            source="qdrant",
            metadata={"chunk_index": i, "document_id": f"doc_{i}"},
        )
        for i in range(n)
    ]


@pytest.fixture
def mock_reranker():
    with patch("app.services.reranker.CrossEncoder") as MockCE:
        instance = MagicMock()
        MockCE.return_value = instance
        r = Reranker("cross-encoder/ms-marco-MiniLM-L-6-v2")
        r._model = instance
        yield r, instance


def test_rerank_returns_top_k(mock_reranker):
    reranker, model_mock = mock_reranker
    candidates = _make_candidates(5)
    # Assign descending scores so candidate 4 ranks first
    model_mock.predict.return_value = np.array([0.1, 0.3, 0.5, 0.7, 0.9])

    result = asyncio.run(reranker.rerank("test query", candidates, top_k=3))

    assert len(result) == 3
    # Highest score (0.9) belongs to candidate index 4
    assert result[0]["score"] == pytest.approx(0.9)
    assert result[0]["content"] == "Candidate document number 4"


def test_rerank_preserves_metadata(mock_reranker):
    reranker, model_mock = mock_reranker
    candidates = _make_candidates(3)
    model_mock.predict.return_value = np.array([0.8, 0.5, 0.2])

    result = asyncio.run(reranker.rerank("query", candidates, top_k=3))

    # All metadata keys preserved
    for item in result:
        assert "chunk_index" in item["metadata"]
        assert "document_id" in item["metadata"]


def test_rerank_empty_candidates(mock_reranker):
    reranker, _ = mock_reranker
    result = asyncio.run(reranker.rerank("query", [], top_k=5))
    assert result == []


def test_rerank_top_k_less_than_candidates(mock_reranker):
    reranker, model_mock = mock_reranker
    candidates = _make_candidates(10)
    model_mock.predict.return_value = np.arange(10, dtype=float)

    result = asyncio.run(reranker.rerank("query", candidates, top_k=4))
    assert len(result) == 4
    # Highest score (9) should be first
    assert result[0]["score"] == pytest.approx(9.0)


def test_rerank_top_k_greater_than_candidates(mock_reranker):
    reranker, model_mock = mock_reranker
    candidates = _make_candidates(3)
    model_mock.predict.return_value = np.array([0.3, 0.1, 0.2])

    result = asyncio.run(reranker.rerank("query", candidates, top_k=10))
    assert len(result) == 3  # cannot return more than available
