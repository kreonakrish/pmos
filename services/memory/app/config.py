from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    service_name: str = "memory"
    memory_port: int = 8001
    redis_url: str = "redis://localhost:6379"
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_db: str = "pmos"
    mysql_user: str = "root"
    mysql_password: str = ""
    faiss_index_path: str = "/data/faiss"
    short_term_ttl_sec: int = 3600
    distillation_interval_min: int = 30
    distillation_frequency_threshold: int = 3
    embedding_model: str = "sentence-transformers/all-mpnet-base-v2"
    embedding_dimension: int = 768
    log_level: str = "INFO"
    # Retry config
    retry_max_attempts: int = 3
    retry_wait_multiplier: int = 1
    retry_wait_max_sec: int = 10
    # Redis stream group
    redis_stream_group: str = "memory-service"
    redis_stream_consumer: str = "consumer-1"
    redis_memory_stream: str = "memory:writes"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
