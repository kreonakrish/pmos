"""OpenTelemetry setup and Prometheus metrics for the orchestrator service."""

from prometheus_client import Counter, Histogram, CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

REQUEST_TOTAL = Counter(
    "request_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)

REQUEST_DURATION = Histogram(
    "request_duration_seconds",
    "HTTP request duration",
    ["method", "path"],
)

LLM_CALL_TOTAL = Counter(
    "llm_call_total",
    "Total LLM API calls",
    ["model", "status"],
)

LLM_LATENCY = Histogram(
    "llm_latency_seconds",
    "LLM call latency",
    ["model"],
)


def get_metrics() -> tuple[bytes, str]:
    """Return Prometheus metrics in text exposition format."""
    return generate_latest(), CONTENT_TYPE_LATEST
