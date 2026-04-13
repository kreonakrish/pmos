"""
PMOS Validation Suite -- Central configuration.

All service URLs and timeouts are env-driven so the suite can run against
local, staging, or production deployments without code changes.

Override any value via environment variable, e.g.:
    PMOS_GATEWAY_URL=https://api.example.com ./scripts/run_tests.sh
"""
import os

# ---------------------------------------------------------------------------
# Service base URLs (env-overridable; defaults assume localhost dev)
# ---------------------------------------------------------------------------
GATEWAY_URL       = os.environ.get("PMOS_GATEWAY_URL",       "http://localhost:4000")
ORCHESTRATOR_URL  = os.environ.get("PMOS_ORCHESTRATOR_URL",  "http://localhost:8000")
MEMORY_URL        = os.environ.get("PMOS_MEMORY_URL",        "http://localhost:8001")
RAG_URL           = os.environ.get("PMOS_RAG_URL",           "http://localhost:8002")
SCORING_URL       = os.environ.get("PMOS_SCORING_URL",       "http://localhost:8003")
AGENT_MGMT_URL    = os.environ.get("PMOS_AGENT_MGMT_URL",    "http://localhost:4001")
META_ASSEMBLY_URL = os.environ.get("PMOS_META_ASSEMBLY_URL", "http://localhost:8004")

# ---------------------------------------------------------------------------
# Timeouts (seconds, env-overridable)
# ---------------------------------------------------------------------------
REQUEST_TIMEOUT = int(os.environ.get("PMOS_REQUEST_TIMEOUT", "30"))
POLL_TIMEOUT    = int(os.environ.get("PMOS_POLL_TIMEOUT",    "60"))
POLL_INTERVAL   = int(os.environ.get("PMOS_POLL_INTERVAL",   "2"))

# ---------------------------------------------------------------------------
# Shared state (populated by suites in order)
# ---------------------------------------------------------------------------
state: dict = {}
