"""Configuration for the Translator service.

Loads from .env via pydantic-settings. Mirrors the orchestrator's settings shape
where it overlaps so a single shared .env Just Works.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    service_name: str = "translator"
    translator_port: int = 8005

    # Execution Neo4j (kept for parity / shared driver code paths).
    neo4j_uri: str = ""
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    neo4j_database: str = "neo4j"

    # Ontology Neo4j — what this service actually queries. Each value falls
    # back to the execution-graph counterpart so dev only needs one URI.
    ontology_neo4j_uri: str = ""
    ontology_neo4j_user: str = ""
    ontology_neo4j_password: str = ""
    ontology_neo4j_database: str = ""

    # Qdrant (translation_examples collection)
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_api_key: str = ""
    qdrant_prefer_grpc: bool = False

    # Embedder
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    # LLM
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 4096
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    google_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    max_concurrent_llm_calls: int = 10

    # MySQL (kept available for cross-service joins later)
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_db: str = "pmos"
    mysql_user: str = "root"
    mysql_password: str = ""

    # Logging
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        # The repo's shared monorepo .env carries fields owned by other
        # services. The translator only consumes a narrow subset; ignore the
        # rest so pydantic v2 doesn't reject them as ``extra_forbidden``.
        extra = "ignore"


settings = Settings()
