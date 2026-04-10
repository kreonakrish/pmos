from typing import List, Optional

try:
    from qdrant_client import AsyncQdrantClient
    from qdrant_client.models import (
        Distance,
        PointStruct,
        VectorParams,
    )
except ImportError:
    AsyncQdrantClient = None
    Distance = VectorParams = PointStruct = None

from app.adapters.base import SearchResult, VectorStoreAdapter
from app.utils.logger import get_logger

logger = get_logger(layer="adapter")


class QdrantAdapter(VectorStoreAdapter):
    """VectorStoreAdapter backed by a Qdrant collection."""

    def __init__(self, settings) -> None:
        self._client = AsyncQdrantClient(
            host=settings.qdrant_host,
            port=settings.qdrant_port,
            api_key=settings.qdrant_api_key or None,
            prefer_grpc=settings.qdrant_prefer_grpc,
        )
        self._collection = f"{settings.qdrant_collection_prefix}_documents"
        self._dimension = settings.embedding_dimension

    # ------------------------------------------------------------------
    # VectorStoreAdapter interface
    # ------------------------------------------------------------------

    async def upsert(self, id: str, vector: List[float], metadata: dict) -> None:
        await self._client.upsert(
            collection_name=self._collection,
            points=[PointStruct(id=id, vector=vector, payload=metadata)],
        )
        logger.info("Qdrant upsert", doc_id=id, collection=self._collection)

    async def search(
        self,
        query_vector: List[float],
        k: int,
        filters: Optional[dict] = None,
    ) -> List[SearchResult]:
        results = await self._client.search(
            collection_name=self._collection,
            query_vector=query_vector,
            limit=k,
        )
        return [
            SearchResult(
                id=str(r.id),
                content=r.payload.get("content", ""),
                score=float(r.score),
                source="qdrant",
                metadata=r.payload,
            )
            for r in results
        ]

    async def delete(self, id: str) -> None:
        from qdrant_client.models import PointIdsList  # noqa: lazy import OK — only called at runtime

        await self._client.delete(
            collection_name=self._collection,
            points_selector=PointIdsList(points=[id]),
        )
        logger.info("Qdrant delete", doc_id=id, collection=self._collection)

    async def health_check(self) -> bool:
        try:
            await self._client.get_collections()
            return True
        except Exception as exc:
            logger.error("Qdrant health check failed", error=str(exc))
            return False

    async def create_collection(self, name: str, dimension: int) -> None:
        existing = await self._client.get_collections()
        existing_names = [c.name for c in existing.collections]
        if name not in existing_names:
            await self._client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=dimension, distance=Distance.COSINE),
            )
            logger.info("Qdrant collection created", name=name, dimension=dimension)

    async def ensure_collection(self) -> None:
        """Ensure the default documents collection exists."""
        await self.create_collection(self._collection, self._dimension)
