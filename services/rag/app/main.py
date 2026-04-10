import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_client import make_asgi_app

from app.config import settings
from app.adapters.faiss_adapter import FAISSAdapter
from app.adapters.mysql_fulltext import MySQLFullTextAdapter
from app.routes.health import router as health_router
from app.routes.rag import router as rag_router
from app.services.ingestion import IngestionService
from app.services.reranker import Reranker
from app.services.retrieval import RetrievalService
from app.services.stream_consumer import DocumentStreamConsumer
from app.utils.logger import get_logger

logger = get_logger(layer="main")


def _build_vector_store(s):
    backend = s.vector_store_backend.lower()
    if backend == "qdrant":
        from app.adapters.qdrant_adapter import QdrantAdapter
        return QdrantAdapter(s)
    elif backend == "faiss":
        return FAISSAdapter(s)
    elif backend == "pinecone":
        from app.adapters.pinecone_adapter import PineconeAdapter
        return PineconeAdapter(s)
    elif backend == "weaviate":
        from app.adapters.weaviate_adapter import WeaviateAdapter
        return WeaviateAdapter(s)
    else:
        raise ValueError(f"Unknown vector_store_backend: {backend}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("RAG service starting", port=settings.rag_port)

    # Build adapters
    vector_store = _build_vector_store(settings)
    faiss_adapter = FAISSAdapter(settings)
    mysql_adapter = MySQLFullTextAdapter(settings)

    # Ensure Qdrant collection exists (no-op for other backends)
    if hasattr(vector_store, "ensure_collection"):
        try:
            await vector_store.ensure_collection()
        except Exception as exc:
            logger.warning("Could not ensure vector store collection", error=str(exc))

    # Load persisted FAISS index if available
    try:
        await faiss_adapter.load("documents")
    except Exception as exc:
        logger.warning("Could not load FAISS index", error=str(exc))

    # Services
    reranker = Reranker(settings.reranker_model)
    retrieval_svc = RetrievalService(vector_store, mysql_adapter, reranker, settings)
    ingestion_svc = IngestionService(vector_store, faiss_adapter, mysql_adapter, settings)

    # Redis stream consumer
    consumer = DocumentStreamConsumer(settings.redis_url, ingestion_svc)
    try:
        await consumer.start()
    except Exception as exc:
        logger.warning("Stream consumer could not start", error=str(exc))

    # Attach to app state
    app.state.settings = settings
    app.state.vector_store = vector_store
    app.state.mysql_adapter = mysql_adapter
    app.state.retrieval_service = retrieval_svc
    app.state.ingestion_service = ingestion_svc
    app.state.stream_consumer = consumer

    logger.info("RAG service ready")
    yield

    # Shutdown
    logger.info("RAG service shutting down")
    await consumer.stop()
    try:
        await faiss_adapter.persist("documents")
    except Exception as exc:
        logger.warning("Could not persist FAISS index on shutdown", error=str(exc))
    logger.info("RAG service stopped")


app = FastAPI(
    title="PMOS RAG Service",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(rag_router)

# Prometheus metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)
