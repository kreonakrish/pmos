"""FAISS adapter — per-agent index shards stored on disk."""
from __future__ import annotations

import asyncio
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import numpy as np

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger()

_faiss_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="faiss")
_index_locks: dict[int, threading.Lock] = {}
_lock_registry = threading.Lock()


def _get_index_lock(agent_id: int) -> threading.Lock:
    with _lock_registry:
        if agent_id not in _index_locks:
            _index_locks[agent_id] = threading.Lock()
        return _index_locks[agent_id]


class FAISSAdapter:
    """
    Per-agent FAISS IndexFlatIP shards.

    Index files are stored at: {index_path}/agent_{agent_id}.index
    A companion mapping file at {index_path}/agent_{agent_id}.map.json
    maps internal FAISS integer positions → external memory_id strings.
    """

    def __init__(self, index_path: str | None = None, dimension: int | None = None) -> None:
        self.index_path = index_path or settings.faiss_index_path
        self.dimension = dimension or settings.embedding_dimension
        os.makedirs(self.index_path, exist_ok=True)

    def _index_file(self, agent_id: int) -> str:
        return os.path.join(self.index_path, f"agent_{agent_id}.index")

    def _map_file(self, agent_id: int) -> str:
        return os.path.join(self.index_path, f"agent_{agent_id}.map.json")

    def _load_map(self, agent_id: int) -> list[str]:
        path = self._map_file(agent_id)
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_map(self, agent_id: int, mapping: list[str]) -> None:
        path = self._map_file(agent_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(mapping, f)

    def get_or_create_index(self, agent_id: int):
        """Load existing index or create a new one. Sync — use from executor."""
        import faiss  # type: ignore

        path = self._index_file(agent_id)
        if os.path.exists(path):
            return faiss.read_index(path)
        index = faiss.IndexFlatIP(self.dimension)
        return index

    def _add_sync(self, agent_id: int, vector: np.ndarray, memory_id: str) -> None:
        import faiss  # type: ignore

        lock = _get_index_lock(agent_id)
        with lock:
            index = self.get_or_create_index(agent_id)
            mapping = self._load_map(agent_id)
            vec = vector.reshape(1, -1).astype(np.float32)
            # Normalise so dot-product == cosine similarity
            faiss.normalize_L2(vec)
            index.add(vec)
            mapping.append(memory_id)
            faiss.write_index(index, self._index_file(agent_id))
            self._save_map(agent_id, mapping)
            logger.info(
                "FAISS vector added",
                layer="adapter",
                agent_id=agent_id,
                memory_id=memory_id,
                index_size=index.ntotal,
            )

    def _search_sync(
        self, agent_id: int, query_vector: np.ndarray, k: int
    ) -> list[tuple[str, float]]:
        import faiss  # type: ignore

        path = self._index_file(agent_id)
        if not os.path.exists(path):
            return []

        lock = _get_index_lock(agent_id)
        with lock:
            index = self.get_or_create_index(agent_id)
            mapping = self._load_map(agent_id)

            if index.ntotal == 0:
                return []

            k = min(k, index.ntotal)
            vec = query_vector.reshape(1, -1).astype(np.float32)
            faiss.normalize_L2(vec)
            distances, indices = index.search(vec, k)

        results: list[tuple[str, float]] = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0 or idx >= len(mapping):
                continue
            results.append((mapping[idx], float(dist)))

        results.sort(key=lambda x: x[1], reverse=True)
        return results

    async def add(self, agent_id: int, vector: np.ndarray, memory_id: str) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(_faiss_executor, self._add_sync, agent_id, vector, memory_id)

    async def search(
        self, agent_id: int, query_vector: np.ndarray, k: int = 5
    ) -> list[tuple[str, float]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            _faiss_executor, self._search_sync, agent_id, query_vector, k
        )

    def get_index_size(self, agent_id: int) -> int:
        """Return number of vectors in agent's index."""
        path = self._index_file(agent_id)
        if not os.path.exists(path):
            return 0
        import faiss  # type: ignore
        index = faiss.read_index(path)
        return index.ntotal


_faiss_adapter: Optional[FAISSAdapter] = None


def get_faiss_adapter() -> FAISSAdapter:
    global _faiss_adapter
    if _faiss_adapter is None:
        _faiss_adapter = FAISSAdapter()
    return _faiss_adapter
