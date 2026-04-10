import json
import time
import uuid
from typing import Any

SERVICE_NAME = "rag"


class StructuredLogger:
    def __init__(self, layer: str = "service"):
        self._layer = layer

    def _emit(self, level: str, message: str, **extra: Any) -> None:
        record: dict[str, Any] = {
            "level": level,
            "message": message,
            "service": SERVICE_NAME,
            "layer": self._layer,
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

    def with_trace(self, trace_id: str, span_id: str | None = None) -> "StructuredLogger":
        child = _BoundLogger(self._layer, trace_id, span_id or str(uuid.uuid4()))
        return child


class _BoundLogger(StructuredLogger):
    def __init__(self, layer: str, trace_id: str, span_id: str):
        super().__init__(layer)
        self._trace_id = trace_id
        self._span_id = span_id

    def _emit(self, level: str, message: str, **extra: Any) -> None:
        extra.setdefault("trace_id", self._trace_id)
        extra.setdefault("span_id", self._span_id)
        super()._emit(level, message, **extra)


def get_logger(layer: str = "service") -> StructuredLogger:
    return StructuredLogger(layer=layer)
