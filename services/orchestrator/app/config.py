from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    service_name: str = "orchestrator"
    orchestrator_port: int = 8000

    # Neo4j (execution graph — set NEO4J_URI in .env; no hardcoded default)
    neo4j_uri: str = ""
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    neo4j_database: str = "neo4j"

    # Ontology Neo4j (Business Ontology / Semantic Spine).
    # In production this typically points to a separate graph DB; for dev each
    # falls back to the execution-graph value when unset.
    ontology_neo4j_uri: str = ""
    ontology_neo4j_user: str = ""
    ontology_neo4j_password: str = ""
    ontology_neo4j_database: str = ""

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Downstream services
    memory_service_url: str = "http://localhost:8001"
    scoring_service_url: str = "http://localhost:8003"
    rag_service_url: str = "http://localhost:8002"
    meta_assembly_url: str = "http://localhost:8004"
    agent_mgmt_url: str = "http://localhost:4001"
    translator_service_url: str = "http://localhost:8005"
    translator_timeout_sec: float = 30.0

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

    # Circuit breaker
    cb_timeout_sec: int = 30
    cb_failure_threshold: int = 5

    # Retry
    retry_max_attempts: int = 3
    retry_strategy: str = "EXPONENTIAL"
    retry_wait_multiplier: float = 1.0
    retry_wait_max_sec: int = 10

    # Capability negotiation (bidding)
    bid_timeout_sec: float = 15.0
    bid_confidence_weight: float = 0.45
    bid_memory_weight: float = 0.15
    bid_latency_weight: float = 0.10
    # Phase 22 — weight on the bid's self-declared coverage ratio
    # (answerable / (answerable + not_answerable)). When a bid carries no
    # structured coverage (legacy shape), the coverage term is treated as
    # 1.0 — neutral — so legacy bids aren't unfairly demoted.
    bid_coverage_weight: float = 0.30

    # Sub-agent spawning
    max_sub_agent_depth: int = 3

    # Logging
    log_level: str = "INFO"

    # MySQL (for orchestrator-owned tables)
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_db: str = "pmos"
    mysql_user: str = "root"
    mysql_password: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
