import json
import time
import uuid
from typing import Any

from app.config import settings


class StructuredLogger:
    """Structured JSON logger — no bare print() statements allowed."""

    def __init__(self, layer: str = "service"):
        self.service = settings.service_name
        self.layer = layer

    def _emit(self, level: str, message: str, **extra: Any) -> None:
        record: dict[str, Any] = {
            "level": level,
            "message": message,
            "service": self.service,
            "layer": self.layer,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "span_id": str(uuid.uuid4()),
        }
        record.update(extra)
        print(json.dumps(record))  # stdout → collected by Docker/k8s

    def debug(self, message: str, **extra: Any) -> None:
        self._emit("DEBUG", message, **extra)

    def info(self, message: str, **extra: Any) -> None:
        self._emit("INFO", message, **extra)

    def warning(self, message: str, **extra: Any) -> None:
        self._emit("WARNING", message, **extra)

    def error(self, message: str, **extra: Any) -> None:
        self._emit("ERROR", message, **extra)

    def critical(self, message: str, **extra: Any) -> None:
        self._emit("CRITICAL", message, **extra)


def get_logger(layer: str = "service") -> StructuredLogger:
    return StructuredLogger(layer=layer)
