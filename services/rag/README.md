# RAG Service

Multi-source Retrieval-Augmented Generation service for PMOS. Provides parallel retrieval across multiple vector store backends, MySQL full-text search, and agent memory, with cross-encoder re-ranking.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/rag/query` | Parallel retrieval across configured sources, merged and re-ranked |
| `POST` | `/v1/rag/ingest` | Ingest a document: chunk, embed, and write to all configured stores |
| `GET` | `/health` | Health check (vector store, MySQL, Redis connectivity) |
| `GET` | `/metrics` | Prometheus metrics |

## Adapter System

The service uses a `VectorStoreAdapter` abstract base class with swappable implementations:

- **QdrantAdapter** -- default, connects to Qdrant via async gRPC/HTTP client
- **FAISSAdapter** -- local FAISS index with per-collection shard isolation
- **PineconeAdapter** -- managed Pinecone index
- **WeaviateAdapter** -- Weaviate vector database

The active backend is selected by the `VECTOR_STORE_BACKEND` environment variable. Additional sources (MySQL full-text, agent memory service) are always available.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RAG_PORT` | `8002` | Service listen port |
| `VECTOR_STORE_BACKEND` | `qdrant` | Active vector backend: `qdrant`, `faiss`, `pinecone`, `weaviate` |
| `QDRANT_HOST` | `localhost` | Qdrant server host |
| `QDRANT_PORT` | `6333` | Qdrant HTTP port |
| `QDRANT_GRPC_PORT` | `6334` | Qdrant gRPC port |
| `QDRANT_API_KEY` | `` | Qdrant API key (empty for local) |
| `QDRANT_COLLECTION_PREFIX` | `pmos` | Prefix for Qdrant collection names |
| `MYSQL_HOST` | `localhost` | MySQL host |
| `MYSQL_PORT` | `3306` | MySQL port |
| `MYSQL_DB` | `pmos` | MySQL database name |
| `MYSQL_USER` | `root` | MySQL user |
| `MYSQL_PASSWORD` | `` | MySQL password |
| `REDIS_URL` | `redis://localhost:6379` | Redis connection URL |
| `EMBEDDING_MODEL` | `sentence-transformers/all-mpnet-base-v2` | Sentence-transformer model for embeddings |
| `RERANKER_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Cross-encoder model for re-ranking |
| `RAG_TOP_K` | `10` | Default number of results to return |
| `RAG_PARALLEL_TIMEOUT_SEC` | `5.0` | Timeout per source during parallel retrieval |
| `RAG_CHUNK_SIZE` | `500` | Characters per chunk during ingestion |
| `RAG_CHUNK_OVERLAP` | `50` | Overlap between adjacent chunks |
| `FAISS_INDEX_PATH` | `/data/faiss` | Directory for FAISS index persistence |
| `MEMORY_SERVICE_URL` | `http://localhost:8001` | Memory service base URL |
| `PINECONE_API_KEY` | `` | Pinecone API key |
| `PINECONE_ENVIRONMENT` | `` | Pinecone environment |
| `PINECONE_INDEX` | `pmos-documents` | Pinecone index name |
| `WEAVIATE_URL` | `http://localhost:8080` | Weaviate server URL |
| `WEAVIATE_API_KEY` | `` | Weaviate API key |
| `RETRY_MAX_ATTEMPTS` | `3` | Max retry attempts for downstream calls |
| `LOG_LEVEL` | `INFO` | Logging level |

## Running

```bash
# Install dependencies
pip install -r requirements.txt

# Start the service
uvicorn app.main:app --host 0.0.0.0 --port 8002

# Or via Docker
docker build -t pmos-rag .
docker run -p 8002:8002 --env-file .env pmos-rag
```

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=app --cov-report=term-missing

# Run specific test suites
pytest tests/unit/ -v
pytest tests/adapters/ -v
pytest tests/integration/ -v
```
