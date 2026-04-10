from typing import List, Optional

try:
    from pinecone import Pinecone
except ImportError:
    Pinecone = None

from app.adapters.base import SearchResult, VectorStoreAdapter
from app.utils.logger import get_logger

logger = get_logger(layer="adapter")


class PineconeAdapter(VectorStoreAdapter):
    """
    VectorStoreAdapter backed by Pinecone.
    Requires: pinecone-client>=3.0.0
    Config env vars: PINECONE_API_KEY, PINECONE_ENVIRONMENT, PINECONE_INDEX
    """

    def __init__(self, settings) -> None:
        self._pc = Pinecone(api_key=settings.pinecone_api_key)
        self._index_name: str = settings.pinecone_index
        self._index = self._pc.Index(self._index_name)

    # ------------------------------------------------------------------
    # VectorStoreAdapter interface
    # ------------------------------------------------------------------

    async def upsert(self, id: str, vector: List[float], metadata: dict) -> None:
        self._index.upsert(vectors=[(id, vector, metadata)])
        logger.info("Pinecone upsert", doc_id=id, index=self._index_name)

    async def search(
        self,
        query_vector: List[float],
        k: int,
        filters: Optional[dict] = None,
    ) -> List[SearchResult]:
        kwargs: dict = {"vector": query_vector, "top_k": k, "include_metadata": True}
        if filters:
            kwargs["filter"] = filters
        response = self._index.query(**kwargs)
        return [
            SearchResult(
                id=match["id"],
                content=match.get("metadata", {}).get("content", ""),
                score=float(match["score"]),
                source="pinecone",
                metadata=match.get("metadata", {}),
            )
            for match in response.get("matches", [])
        ]

    async def delete(self, id: str) -> None:
        self._index.delete(ids=[id])
        logger.info("Pinecone delete", doc_id=id, index=self._index_name)

    async def health_check(self) -> bool:
        try:
            self._index.describe_index_stats()
            return True
        except Exception as exc:
            logger.error("Pinecone health check failed", error=str(exc))
            return False

    async def create_collection(self, name: str, dimension: int) -> None:
        # Pinecone index creation is usually done via the console / API outside app startup.
        # Raise a warning; the index must pre-exist.
        logger.warning(
            "Pinecone create_collection called — index must be pre-created in Pinecone console",
            name=name,
            dimension=dimension,
        )
