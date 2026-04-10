import json
import time
import uuid
import logging
from typing import Any

SERVICE_NAME = "memory"


class StructuredLogger:
    def __init__(self, name: str = SERVICE_NAME):
        self.service = name

    def _emit(self, level: str, message: str, **extra: Any) -> None:
        record: dict[str, Any] = {
            "level": level,
            "message": message,
            "service": self.service,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        record.update(extra)
        print(json.dumps(record), flush=True)

    def info(self, message: str, **extra: Any) -> None:
        self._emit("INFO", message, **extra)

    def warning(self, message: str, **extra: Any) -> None:
        self._emit("WARNING", message, **extra)

    def error(self, message: str, **extra: Any) -> None:
        self._emit("ERROR", message, **extra)

    def debug(self, message: str, **extra: Any) -> None:
        self._emit("DEBUG", message, **extra)

    def critical(self, message: str, **extra: Any) -> None:
        self._emit("CRITICAL", message, **extra)


def get_logger(name: str = SERVICE_NAME) -> StructuredLogger:
    return StructuredLogger(name)


def new_span_id() -> str:
    return str(uuid.uuid4())
