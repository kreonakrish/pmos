"""
PMOS Validation Suite -- Central configuration.

Service base URLs, timeouts, and shared state used across all suites.
Suites execute in numeric order and populate ``state`` for downstream suites.
"""

# ---------------------------------------------------------------------------
# Service base URLs
# ---------------------------------------------------------------------------
GATEWAY_URL = "http://localhost:4000"
ORCHESTRATOR_URL = "http://localhost:8000"
MEMORY_URL = "http://localhost:8001"
RAG_URL = "http://localhost:8002"
SCORING_URL = "http://localhost:8003"
AGENT_MGMT_URL = "http://localhost:4001"
META_ASSEMBLY_URL = "http://localhost:8004"

# ---------------------------------------------------------------------------
# Timeouts (seconds)
# ---------------------------------------------------------------------------
REQUEST_TIMEOUT = 30
POLL_TIMEOUT = 60
POLL_INTERVAL = 2

# ---------------------------------------------------------------------------
# Shared state (populated by suites in order)
# ---------------------------------------------------------------------------
state: dict = {}
