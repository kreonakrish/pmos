"""Qdrant adapter for the translator service.

Backs the ``translation_examples`` collection used to store promoted
translation memories (NL question -> canonical entities + dataset bindings).
``ensure_collection()`` is called from the FastAPI lifespan and is idempotent.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

try:
    from qdrant_client import AsyncQdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams
except ImportError:  # pragma: no cover - dependency missing in test env
    AsyncQdrantClient = None  # type: ignore[assignment]
    Distance = VectorParams = PointStruct = None  # type: ignore[assignment]

from shared.translator_contracts import (
    TRANSLATION_EXAMPLES_COLLECTION,
    TRANSLATION_EXAMPLES_DIM,
)

from app.config import settings
from app.utils.logger import logger


class QdrantAdapter:
    """Wraps Qdrant for the translator's ``translation_examples`` collection."""

    def __init__(self) -> None:
        if AsyncQdrantClient is None:
            self._client = None
            logger.warning(
                "qdrant-client not installed — adapter disabled",
                layer="adapter",
            )
            return
        self._client = AsyncQdrantClient(
            host=settings.qdrant_host,
            port=settings.qdrant_port,
            api_key=settings.qdrant_api_key or None,
            prefer_grpc=settings.qdrant_prefer_grpc,
        )
        self._collection = TRANSLATION_EXAMPLES_COLLECTION
        self._dimension = TRANSLATION_EXAMPLES_DIM

    async def ensure_collection(self, dimension: Optional[int] = None) -> None:
        """Create the translation_examples collection (idempotent).

        When ``dimension`` is supplied, the existing collection is inspected
        and **recreated** if its vector size doesn't match. This guards against
        the operator switching the embedder model after the collection was
        first bootstrapped.
        """
        if self._client is None:
            return
        target_dim = int(dimension) if dimension else int(self._dimension)
        try:
            existing = await self._client.get_collections()
            names = [c.name for c in existing.collections]
            if self._collection in names:
                # Inspect current dim so a model swap is handled cleanly.
                current_dim: Optional[int] = None
                try:
                    info = await self._client.get_collection(self._collection)
                    current_dim = int(info.config.params.vectors.size)  # type: ignore[union-attr]
                except Exception:
                    current_dim = None

                if current_dim == target_dim:
                    self._dimension = target_dim
                    logger.info(
                        "Qdrant collection already exists",
                        layer="adapter",
                        collection=self._collection,
                        dimension=current_dim,
                    )
                    return

                logger.warning(
                    "Qdrant collection dimension mismatch — recreating",
                    layer="adapter",
                    collection=self._collection,
                    current_dim=current_dim,
                    target_dim=target_dim,
                )
                await self._client.delete_collection(self._collection)

            await self._client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(size=target_dim, distance=Distance.COSINE),
            )
            self._dimension = target_dim
            logger.info(
                "Qdrant collection created",
                layer="adapter",
                collection=self._collection,
                dimension=target_dim,
            )
        except Exception as exc:
            logger.error(
                "Qdrant ensure_collection failed",
                layer="adapter",
                collection=self._collection,
                error=str(exc),
            )

    async def health_check(self) -> bool:
        if self._client is None:
            return False
        try:
            await self._client.get_collections()
            return True
        except Exception as exc:
            logger.error("Qdrant health check failed", layer="adapter", error=str(exc))
            return False

    async def upsert_example(
        self,
        point_id: str,
        vector: List[float],
        payload: Dict[str, Any],
        trace_id: str = "",
    ) -> None:
        if self._client is None:
            raise RuntimeError("Qdrant client not initialised")
        await self._client.upsert(
            collection_name=self._collection,
            points=[PointStruct(id=point_id, vector=vector, payload=payload)],
        )
        logger.info(
            "Qdrant upsert",
            layer="adapter",
            collection=self._collection,
            point_id=point_id,
            trace_id=trace_id,
        )

    async def search(
        self,
        query_vector: List[float],
        k: int = 5,
        query_filter: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        if self._client is None:
            return []
        results = await self._client.search(
            collection_name=self._collection,
            query_vector=query_vector,
            limit=k,
        )
        return [
            {
                "id": str(r.id),
                "score": float(r.score),
                "payload": r.payload or {},
            }
            for r in results
        ]
