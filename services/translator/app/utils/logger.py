import json
import time
import uuid
from typing import Any

SERVICE_NAME = "translator"


class StructuredLogger:
    """Structured JSON logger — emits to stdout for Docker/k8s collection."""

    def _build_record(self, level: str, message: str, **extra: Any) -> dict:
        record: dict[str, Any] = {
            "level": level,
            "message": message,
            "service": SERVICE_NAME,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        record.update(extra)
        # Ensure span_id present if not provided
        if "span_id" not in record:
            record["span_id"] = str(uuid.uuid4())
        return record

    def _emit(self, record: dict) -> None:
        print(json.dumps(record), flush=True)

    def info(self, message: str, **extra: Any) -> None:
        self._emit(self._build_record("INFO", message, **extra))

    def error(self, message: str, **extra: Any) -> None:
        self._emit(self._build_record("ERROR", message, **extra))

    def warning(self, message: str, **extra: Any) -> None:
        self._emit(self._build_record("WARNING", message, **extra))

    def debug(self, message: str, **extra: Any) -> None:
        self._emit(self._build_record("DEBUG", message, **extra))

    def critical(self, message: str, **extra: Any) -> None:
        self._emit(self._build_record("CRITICAL", message, **extra))


logger = StructuredLogger()
