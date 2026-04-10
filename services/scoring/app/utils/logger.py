import json
import time
import uuid
from typing import Any

SERVICE_NAME = "scoring"


class StructuredLogger:
    """
    Structured JSON logger that emits to stdout for collection by Docker / k8s log aggregators.
    Every log line includes mandatory PMOS observability fields.
    """

    def __init__(self, layer: str = "service"):
        self.layer = layer

    def _emit(self, level: str, message: str, **extra: Any) -> None:
        record = {
            "level": level,
            "message": message,
            "service": SERVICE_NAME,
            "layer": self.layer,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            **extra,
        }
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


def new_span_id() -> str:
    return str(uuid.uuid4())


# Default module-level logger
logger = StructuredLogger(layer="service")
