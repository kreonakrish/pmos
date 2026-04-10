from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    service_name: str = "rag"
    rag_port: int = 8002
    vector_store_backend: str = "qdrant"  # qdrant | faiss | pinecone | weaviate
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_grpc_port: int = 6334
    qdrant_api_key: str = ""
    qdrant_collection_prefix: str = "pmos"
    qdrant_prefer_grpc: bool = True
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_db: str = "pmos"
    mysql_user: str = "root"
    mysql_password: str = ""
    redis_url: str = "redis://localhost:6379"
    embedding_model: str = "sentence-transformers/all-mpnet-base-v2"
    embedding_dimension: int = 768
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    rag_top_k: int = 10
    rag_parallel_timeout_sec: float = 5.0
    rag_chunk_size: int = 500
    rag_chunk_overlap: int = 50
    faiss_index_path: str = "/data/faiss"
    memory_service_url: str = "http://localhost:8001"
    log_level: str = "INFO"
    # Pinecone
    pinecone_api_key: str = ""
    pinecone_environment: str = ""
    pinecone_index: str = "pmos-documents"
    # Weaviate
    weaviate_url: str = "http://localhost:8080"
    weaviate_api_key: str = ""
    # Retry / circuit breaker
    retry_max_attempts: int = 3
    retry_wait_multiplier: float = 1.0
    retry_wait_max_sec: float = 10.0

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
