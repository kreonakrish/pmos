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

# Financial Governance — token counters and dollar-cost counter, labeled by
# model+provider+service so /v1/finops can break costs down across the three
# Python services (orchestrator, translator, meta-assembly).
LLM_PROMPT_TOKENS = Counter(
    "llm_prompt_tokens_total",
    "Total prompt (input) tokens consumed by LLM calls",
    ["model", "provider", "service"],
)

LLM_COMPLETION_TOKENS = Counter(
    "llm_completion_tokens_total",
    "Total completion (output) tokens produced by LLM calls",
    ["model", "provider", "service"],
)

LLM_COST_USD = Counter(
    "llm_cost_usd_total",
    "Total USD cost of LLM calls (computed from model_pricing table)",
    ["model", "provider", "service"],
)


def get_metrics() -> tuple[bytes, str]:
    """Return Prometheus metrics in text exposition format."""
    return generate_latest(), CONTENT_TYPE_LATEST
