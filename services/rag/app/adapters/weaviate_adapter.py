import uuid
from typing import List, Optional

try:
    import weaviate
    from weaviate.auth import AuthApiKey
except ImportError:
    weaviate = None
    AuthApiKey = None

from app.adapters.base import SearchResult, VectorStoreAdapter
from app.utils.logger import get_logger

logger = get_logger(layer="adapter")

_CLASS_NAME = "PmosDocument"


class WeaviateAdapter(VectorStoreAdapter):
    """
    VectorStoreAdapter backed by Weaviate.
    Requires: weaviate-client>=4.4.0
    Config env vars: WEAVIATE_URL, WEAVIATE_API_KEY
    """

    def __init__(self, settings) -> None:
        auth = AuthApiKey(settings.weaviate_api_key) if settings.weaviate_api_key else None
        self._client = weaviate.connect_to_custom(
            http_host=settings.weaviate_url.rstrip("/"),
            http_port=80,
            http_secure=False,
            grpc_host=settings.weaviate_url.rstrip("/"),
            grpc_port=50051,
            grpc_secure=False,
            auth_credentials=auth,
        )
        self._class_name = _CLASS_NAME

    # ------------------------------------------------------------------
    # VectorStoreAdapter interface
    # ------------------------------------------------------------------

    async def upsert(self, id: str, vector: List[float], metadata: dict) -> None:
        collection = self._client.collections.get(self._class_name)
        collection.data.insert(
            properties=metadata,
            uuid=self._to_uuid(id),
            vector=vector,
        )
        logger.info("Weaviate upsert", doc_id=id, class_name=self._class_name)

    async def search(
        self,
        query_vector: List[float],
        k: int,
        filters: Optional[dict] = None,
    ) -> List[SearchResult]:
        collection = self._client.collections.get(self._class_name)
        response = collection.query.near_vector(
            near_vector=query_vector,
            limit=k,
            return_metadata=["score"],
        )
        results: List[SearchResult] = []
        for obj in response.objects:
            props = obj.properties or {}
            results.append(
                SearchResult(
                    id=str(obj.uuid),
                    content=props.get("content", ""),
                    score=float(obj.metadata.score if obj.metadata else 0.0),
                    source="weaviate",
                    metadata=props,
                )
            )
        return results

    async def delete(self, id: str) -> None:
        collection = self._client.collections.get(self._class_name)
        collection.data.delete_by_id(self._to_uuid(id))
        logger.info("Weaviate delete", doc_id=id)

    async def health_check(self) -> bool:
        try:
            return self._client.is_ready()
        except Exception as exc:
            logger.error("Weaviate health check failed", error=str(exc))
            return False

    async def create_collection(self, name: str, dimension: int) -> None:
        import weaviate.classes.config as wc

        if not self._client.collections.exists(name):
            self._client.collections.create(
                name=name,
                vectorizer_config=wc.Configure.Vectorizer.none(),
                properties=[
                    wc.Property(name="content", data_type=wc.DataType.TEXT),
                ],
            )
            logger.info("Weaviate collection created", name=name)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_uuid(id: str) -> str:
        try:
            uuid.UUID(id)
            return id
        except ValueError:
            return str(uuid.uuid5(uuid.NAMESPACE_DNS, id))
