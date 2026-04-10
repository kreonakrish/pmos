"""Tests for FAISSAdapter — no external services required.

When faiss-cpu is not installed, we mock the faiss module so that the adapter
can still be exercised in a lightweight test environment.
"""
import asyncio
import sys
import types
from unittest.mock import MagicMock

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# If faiss is not installed, inject a lightweight mock module before importing
# the adapter so that the module-level `import faiss` resolves.
# ---------------------------------------------------------------------------
_real_faiss = None
try:
    import faiss as _real_faiss
except ImportError:
    _fake_faiss = types.ModuleType("faiss")

    class _FakeIndexFlatIP:
        """Minimal in-memory replacement for faiss.IndexFlatIP."""

        def __init__(self, dim: int):
            self.d = dim
            self.ntotal = 0
            self._vectors: list[np.ndarray] = []

        def add(self, vecs: np.ndarray):
            for v in vecs:
                self._vectors.append(v.copy())
                self.ntotal += 1

        def search(self, query: np.ndarray, k: int):
            if self.ntotal == 0:
                return np.array([[]]), np.array([[]])
            # brute-force inner product search
            q = query[0]
            scores = []
            for i, v in enumerate(self._vectors):
                scores.append((float(np.dot(q, v)), i))
            scores.sort(key=lambda x: x[0], reverse=True)
            scores = scores[:k]
            distances = np.array([[s for s, _ in scores]], dtype=np.float32)
            indices = np.array([[i for _, i in scores]], dtype=np.int64)
            return distances, indices

    _fake_faiss.IndexFlatIP = _FakeIndexFlatIP

    def _normalize_L2(vecs: np.ndarray):
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1
        vecs[:] = vecs / norms

    _fake_faiss.normalize_L2 = _normalize_L2

    def _write_index(index, path):
        pass  # no-op for tests

    def _read_index(path):
        raise FileNotFoundError(f"Mock faiss: {path}")

    _fake_faiss.write_index = _write_index
    _fake_faiss.read_index = _read_index

    sys.modules["faiss"] = _fake_faiss
    # Also patch the adapter module's reference
    import app.adapters.faiss_adapter as _faiss_mod
    _faiss_mod.faiss = _fake_faiss

from app.adapters.faiss_adapter import FAISSAdapter


class _FakeSettings:
    faiss_index_path: str
    embedding_dimension: int = 8  # small for tests

    def __init__(self, path: str):
        self.faiss_index_path = path
        self.embedding_dimension = 8


def _rand_vec(dim: int = 8) -> list[float]:
    v = np.random.rand(dim).astype("float32")
    v /= np.linalg.norm(v)
    return v.tolist()


@pytest.fixture
def tmp_settings(tmp_path):
    return _FakeSettings(str(tmp_path))


@pytest.fixture
def adapter(tmp_settings):
    return FAISSAdapter(tmp_settings)


# ---------------------------------------------------------------------------
# Test: build index and search
# ---------------------------------------------------------------------------


def test_upsert_and_search(adapter):
    vectors = [_rand_vec() for _ in range(10)]
    for i, v in enumerate(vectors):
        asyncio.run(adapter.upsert(str(i), v, {"content": f"doc {i}", "_collection": "test"}))

    query = vectors[0]  # exact match should score near 1.0
    results = asyncio.run(adapter.search(query, k=3, filters={"_collection": "test"}))

    assert len(results) == 3
    assert results[0].id == "0"
    assert results[0].score > 0.9


def test_search_returns_correct_ordering(adapter):
    """Nearest vector should always be first."""
    vecs = [_rand_vec() for _ in range(5)]
    for i, v in enumerate(vecs):
        asyncio.run(adapter.upsert(str(i), v, {"content": f"doc {i}", "_collection": "col"}))

    query = vecs[2]
    results = asyncio.run(adapter.search(query, k=5, filters={"_collection": "col"}))

    assert results[0].id == "2"
    # Scores should be non-increasing
    for a, b in zip(results, results[1:]):
        assert a.score >= b.score


def test_shard_isolation(tmp_settings):
    """Vectors inserted under different collection names must not interfere."""
    adapter = FAISSAdapter(tmp_settings)
    v1 = _rand_vec()
    v2 = _rand_vec()

    asyncio.run(adapter.upsert("a", v1, {"content": "A", "_collection": "col_x"}))
    asyncio.run(adapter.upsert("b", v2, {"content": "B", "_collection": "col_y"}))

    # Search col_x with v2 vector — should NOT return b
    results_x = asyncio.run(adapter.search(v2, k=5, filters={"_collection": "col_x"}))
    ids_x = {r.id for r in results_x}
    assert "b" not in ids_x

    results_y = asyncio.run(adapter.search(v1, k=5, filters={"_collection": "col_y"}))
    ids_y = {r.id for r in results_y}
    assert "a" not in ids_y


def test_persist_and_load(tmp_settings):
    """Persisted index should survive a round-trip and still return correct results."""
    if _real_faiss is None:
        pytest.skip("faiss-cpu not installed — persist/load requires real faiss")

    adapter = FAISSAdapter(tmp_settings)
    vecs = [_rand_vec() for _ in range(5)]
    for i, v in enumerate(vecs):
        asyncio.run(adapter.upsert(str(i), v, {"content": f"doc {i}", "_collection": "documents"}))

    asyncio.run(adapter.persist("documents"))

    # Load into a fresh adapter instance
    fresh = FAISSAdapter(tmp_settings)
    asyncio.run(fresh.load("documents"))

    query = vecs[3]
    results = asyncio.run(fresh.search(query, k=1, filters={"_collection": "documents"}))
    assert results[0].id == "3"


def test_search_empty_index_returns_empty(adapter):
    results = asyncio.run(adapter.search(_rand_vec(), k=5, filters={"_collection": "empty_col"}))
    assert results == []


def test_health_check_always_true(adapter):
    ok = asyncio.run(adapter.health_check())
    assert ok is True
