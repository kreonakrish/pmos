import json
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    service_name: str = "scoring"
    scoring_port: int = 8003

    # MySQL
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_db: str = "pmos"
    mysql_user: str = "root"
    mysql_password: str = ""

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Scoring configuration — all from env/DB, never hardcoded
    scoring_history_window: int = 50
    band_sensitivity_factor: float = 1.0
    band_min_width: float = 0.05

    # RL configuration
    rl_learning_rate: float = 0.1
    rl_feedback_weights: str = (
        '{"automated":0.4,"user":0.3,"inter_agent":0.2,"orchestrator":0.1}'
    )

    # Logging
    log_level: str = "INFO"

    # Retry / circuit breaker
    retry_max_attempts: int = 3
    retry_wait_multiplier: float = 1.0
    retry_wait_max_sec: float = 10.0
    cb_timeout_sec: float = 30.0

    @property
    def rl_feedback_weights_dict(self) -> dict:
        return json.loads(self.rl_feedback_weights)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
