from prometheus_client import Counter, Histogram

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

GAPS_DETECTED_TOTAL = Counter(
    "capability_gaps_detected_total",
    "Total capability gaps detected",
)

SPECS_GENERATED_TOTAL = Counter(
    "capability_specs_generated_total",
    "Total capability specs generated",
    ["outcome"],  # success | failed
)
