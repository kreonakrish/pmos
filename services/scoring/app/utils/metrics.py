"""
Prometheus metrics definitions for the scoring service.
Exposed on GET /metrics via the prometheus_client ASGI middleware.
"""
from prometheus_client import Counter, Gauge, Histogram

# ── Request-level metrics ──────────────────────────────────────────────────────
REQUEST_TOTAL = Counter(
    "request_total",
    "Total HTTP requests received",
    ["method", "path", "status"],
)

REQUEST_DURATION = Histogram(
    "request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
)

# ── Scoring-specific metrics ──────────────────────────────────────────────────
SCORE_VALUE = Gauge(
    "score_value",
    "Most-recent score computed for an agent in a context type",
    ["agent_id", "context_type"],
)

BAND_WIDTH = Gauge(
    "band_width",
    "Current adaptive band width (high - low) for an agent + context type",
    ["agent_id", "context_type"],
)
