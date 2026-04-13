from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    service_name: str = "meta-assembly"
    meta_assembly_port: int = 8004
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_db: str = "pmos"
    mysql_user: str = "root"
    mysql_password: str = ""
    neo4j_uri: str = ""
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    redis_url: str = "redis://localhost:6379"
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o"
    openai_api_key: str = ""
    meta_allowed_imports: str = (
        "requests,json,re,math,datetime,collections,itertools,functools,numpy,pandas"
    )
    meta_sandbox_timeout_sec: int = 30
    meta_sandbox_memory_mb: int = 256
    log_level: str = "INFO"

    # Retry / circuit-breaker
    retry_max_attempts: int = 3
    retry_wait_multiplier: int = 1
    retry_wait_max_sec: int = 10

    @property
    def allowed_imports_list(self) -> list[str]:
        return [i.strip() for i in self.meta_allowed_imports.split(",")]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
