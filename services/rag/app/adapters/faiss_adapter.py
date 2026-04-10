import asyncio
import json
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

try:
    import faiss
except ImportError:
    faiss = None
import numpy as np

from app.adapters.base import SearchResult, VectorStoreAdapter
from app.utils.logger import get_logger

logger = get_logger(layer="adapter")

_executor = ThreadPoolExecutor(max_workers=2)


class FAISSAdapter(VectorStoreAdapter):
    """
    Document-level FAISS index, separate from per-agent memory FAISS shards.
    Supports multiple named collections; each is a distinct index file.
    """

    def __init__(self, settings) -> None:
        self._base_path: str = settings.faiss_index_path
        self._dimension: int = settings.embedding_dimension
        # Active indices: collection_name -> (faiss.Index, id_map, metadata)
        self._indices: Dict[str, faiss.Index] = {}
        self._id_maps: Dict[str, Dict[int, str]] = {}   # faiss_idx -> doc_id
        self._metadata: Dict[str, Dict[str, dict]] = {}  # doc_id -> metadata
        self._default_collection = "documents"
        os.makedirs(self._base_path, exist_ok=True)

    # ------------------------------------------------------------------
    # VectorStoreAdapter interface
    # ------------------------------------------------------------------

    async def upsert(self, id: str, vector: List[float], metadata: dict) -> None:
        collection = metadata.get("_collection", self._default_collection)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(_executor, self._upsert_sync, id, vector, metadata, collection)

    async def search(
        self,
        query_vector: List[float],
        k: int,
        filters: Optional[dict] = None,
    ) -> List[SearchResult]:
        collection = (filters or {}).get("_collection", self._default_collection)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor, self._search_sync, query_vector, k, collection)

    async def delete(self, id: str) -> None:
        # FAISS does not support in-place deletion easily; mark as removed in metadata
        for col in self._metadata:
            if id in self._metadata[col]:
                self._metadata[col][id]["_deleted"] = True
                logger.info("FAISS soft-delete", doc_id=id, collection=col)

    async def health_check(self) -> bool:
        return True  # FAISS is local; always healthy if process is up

    async def create_collection(self, name: str, dimension: int) -> None:
        if name not in self._indices:
            index = faiss.IndexFlatIP(dimension)  # Inner Product ≡ cosine for normalised vecs
            self._indices[name] = index
            self._id_maps[name] = {}
            self._metadata[name] = {}
            logger.info("FAISS collection created", name=name, dimension=dimension)

    # ------------------------------------------------------------------
    # Persist / load
    # ------------------------------------------------------------------

    async def persist(self, collection: str | None = None) -> None:
        loop = asyncio.get_event_loop()
        col = collection or self._default_collection
        await loop.run_in_executor(_executor, self._persist_sync, col)

    async def load(self, collection: str | None = None) -> None:
        loop = asyncio.get_event_loop()
        col = collection or self._default_collection
        await loop.run_in_executor(_executor, self._load_sync, col)

    # ------------------------------------------------------------------
    # Sync helpers (run in thread pool)
    # ------------------------------------------------------------------

    def _ensure_collection(self, name: str) -> None:
        if name not in self._indices:
            index = faiss.IndexFlatIP(self._dimension)
            self._indices[name] = index
            self._id_maps[name] = {}
            self._metadata[name] = {}

    def _upsert_sync(
        self,
        id: str,
        vector: List[float],
        metadata: dict,
        collection: str,
    ) -> None:
        self._ensure_collection(collection)
        index = self._indices[collection]
        id_map = self._id_maps[collection]
        meta_store = self._metadata[collection]

        vec = np.array([vector], dtype=np.float32)
        faiss.normalize_L2(vec)
        faiss_idx = index.ntotal
        index.add(vec)
        id_map[faiss_idx] = id
        meta_store[id] = metadata
        logger.info("FAISS upsert", doc_id=id, collection=collection, total=index.ntotal)

    def _search_sync(
        self,
        query_vector: List[float],
        k: int,
        collection: str,
    ) -> List[SearchResult]:
        self._ensure_collection(collection)
        index = self._indices[collection]
        id_map = self._id_maps[collection]
        meta_store = self._metadata[collection]

        if index.ntotal == 0:
            return []

        q = np.array([query_vector], dtype=np.float32)
        faiss.normalize_L2(q)
        actual_k = min(k, index.ntotal)
        distances, indices = index.search(q, actual_k)

        results: List[SearchResult] = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0:
                continue
            doc_id = id_map.get(int(idx))
            if not doc_id:
                continue
            meta = meta_store.get(doc_id, {})
            if meta.get("_deleted"):
                continue
            results.append(
                SearchResult(
                    id=doc_id,
                    content=meta.get("content", ""),
                    score=float(dist),
                    source="faiss",
                    metadata=meta,
                )
            )
        return results

    def _persist_sync(self, collection: str) -> None:
        self._ensure_collection(collection)
        index_path = os.path.join(self._base_path, f"{collection}.index")
        meta_path = os.path.join(self._base_path, f"{collection}_meta.json")
        faiss.write_index(self._indices[collection], index_path)
        with open(meta_path, "w") as f:
            json.dump(
                {
                    "id_map": {str(k): v for k, v in self._id_maps[collection].items()},
                    "metadata": self._metadata[collection],
                },
                f,
            )
        logger.info("FAISS persisted", collection=collection, path=index_path)

    def _load_sync(self, collection: str) -> None:
        index_path = os.path.join(self._base_path, f"{collection}.index")
        meta_path = os.path.join(self._base_path, f"{collection}_meta.json")
        if not os.path.exists(index_path):
            logger.warning("FAISS index not found, starting fresh", collection=collection)
            self._ensure_collection(collection)
            return
        self._indices[collection] = faiss.read_index(index_path)
        with open(meta_path, "r") as f:
            data = json.load(f)
        self._id_maps[collection] = {int(k): v for k, v in data["id_map"].items()}
        self._metadata[collection] = data["metadata"]
        logger.info(
            "FAISS loaded",
            collection=collection,
            total=self._indices[collection].ntotal,
        )
