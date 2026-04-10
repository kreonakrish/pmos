from app.adapters.base import SearchResult, VectorStoreAdapter

__all__ = [
    "VectorStoreAdapter",
    "SearchResult",
    "QdrantAdapter",
    "FAISSAdapter",
    "PineconeAdapter",
    "WeaviateAdapter",
    "MySQLFullTextAdapter",
]


def __getattr__(name: str):
    """Lazy import adapters to avoid requiring all ML dependencies at import time."""
    if name == "FAISSAdapter":
        from app.adapters.faiss_adapter import FAISSAdapter
        return FAISSAdapter
    if name == "MySQLFullTextAdapter":
        from app.adapters.mysql_fulltext import MySQLFullTextAdapter
        return MySQLFullTextAdapter
    if name == "PineconeAdapter":
        from app.adapters.pinecone_adapter import PineconeAdapter
        return PineconeAdapter
    if name == "QdrantAdapter":
        from app.adapters.qdrant_adapter import QdrantAdapter
        return QdrantAdapter
    if name == "WeaviateAdapter":
        from app.adapters.weaviate_adapter import WeaviateAdapter
        return WeaviateAdapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
