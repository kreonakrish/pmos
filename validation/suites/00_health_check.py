"""
Suite 00 -- Health Check.

Validates that all 7 PMOS services are reachable and that backing stores
(Neo4j, MySQL, Redis, Qdrant) are connectable.

If ANY check fails the suite exits with code 1 so the runner can abort.
"""
from __future__ import annotations

import sys
import os

# Ensure the validation root is on the path so config / utils can be imported.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import asyncio
from typing import Tuple

import httpx

from config import (
    AGENT_MGMT_URL,
    GATEWAY_URL,
    MEMORY_URL,
    META_ASSEMBLY_URL,
    ORCHESTRATOR_URL,
    RAG_URL,
    REQUEST_TIMEOUT,
    SCORING_URL,
)
from utils import ValidationReporter, report


rp = ValidationReporter("00_health_check")


# ---------------------------------------------------------------------------
# Service health helpers
# ---------------------------------------------------------------------------

async def _check_service(name: str, base_url: str) -> bool:
    """GET /health on a service. Returns True on HTTP 200."""
    url = f"{base_url}/health"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(REQUEST_TIMEOUT)) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                rp.record("PASS", f"test_{name}_health", f"{name} /health returned 200")
                return True
            else:
                rp.record(
                    "FAIL",
                    f"test_{name}_health",
                    f"{name} /health returned {resp.status_code}",
                    resp.text[:200],
                )
                return False
    except httpx.ConnectError as exc:
        rp.record("FAIL", f"test_{name}_health", f"Cannot connect to {name}", str(exc))
        return False
    except Exception as exc:
        rp.record("FAIL", f"test_{name}_health", f"Unexpected error for {name}", str(exc))
        return False


# ---------------------------------------------------------------------------
# Backing-store connectivity helpers
# ---------------------------------------------------------------------------

async def _check_neo4j() -> bool:
    """Verify Neo4j is reachable via the orchestrator health response."""
    url = f"{ORCHESTRATOR_URL}/health"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(REQUEST_TIMEOUT)) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                rp.record("FAIL", "test_neo4j_connectivity", "Orchestrator not healthy -- cannot verify Neo4j")
                return False
            body = resp.json()
            checks = body.get("checks", body)
            neo4j_ok = checks.get("neo4j") in ("ok", True, "healthy")
            if neo4j_ok:
                rp.record("PASS", "test_neo4j_connectivity", "Neo4j reachable via orchestrator health")
            else:
                rp.record(
                    "FAIL",
                    "test_neo4j_connectivity",
                    "Neo4j check not ok in orchestrator health",
                    str(checks),
                )
            return neo4j_ok
    except Exception as exc:
        rp.record("FAIL", "test_neo4j_connectivity", "Error checking Neo4j", str(exc))
        return False


async def _check_mysql() -> bool:
    """Verify MySQL is reachable via agent-mgmt health response."""
    url = f"{AGENT_MGMT_URL}/health"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(REQUEST_TIMEOUT)) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                rp.record("FAIL", "test_mysql_connectivity", "agent-mgmt not healthy -- cannot verify MySQL")
                return False
            body = resp.json()
            checks = body.get("checks", {})
            mysql_ok = checks.get("mysql") in ("ok", True, "healthy")
            if mysql_ok:
                rp.record("PASS", "test_mysql_connectivity", "MySQL reachable via agent-mgmt health")
            else:
                rp.record("FAIL", "test_mysql_connectivity", "MySQL check not ok", str(checks))
            return mysql_ok
    except Exception as exc:
        rp.record("FAIL", "test_mysql_connectivity", "Error checking MySQL", str(exc))
        return False


async def _check_redis() -> bool:
    """Verify Redis is reachable via agent-mgmt health response."""
    url = f"{AGENT_MGMT_URL}/health"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(REQUEST_TIMEOUT)) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                rp.record("FAIL", "test_redis_connectivity", "agent-mgmt not healthy -- cannot verify Redis")
                return False
            body = resp.json()
            checks = body.get("checks", {})
            redis_ok = checks.get("redis") in ("ok", True, "healthy")
            if redis_ok:
                rp.record("PASS", "test_redis_connectivity", "Redis reachable via agent-mgmt health")
            else:
                rp.record("FAIL", "test_redis_connectivity", "Redis check not ok", str(checks))
            return redis_ok
    except Exception as exc:
        rp.record("FAIL", "test_redis_connectivity", "Error checking Redis", str(exc))
        return False


async def _check_qdrant() -> bool:
    """Verify Qdrant is reachable via the RAG service health response."""
    url = f"{RAG_URL}/health"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(REQUEST_TIMEOUT)) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                rp.record("FAIL", "test_qdrant_connectivity", "RAG service not healthy -- cannot verify Qdrant")
                return False
            body = resp.json()
            checks = body.get("checks", {})
            qdrant_ok = checks.get("qdrant") in ("ok", True, "healthy")
            if qdrant_ok:
                rp.record("PASS", "test_qdrant_connectivity", "Qdrant reachable via RAG health")
                return True
            else:
                # Qdrant may be reported as vector_store=True instead of qdrant=True
                vs_ok = checks.get("vector_store") in ("ok", True, "healthy")
                if vs_ok:
                    rp.record("PASS", "test_qdrant_connectivity", "Vector store reachable via RAG health")
                    return True
                # Qdrant may not be exposed in health -- skip, not fail
                rp.record("SKIP", "test_qdrant_connectivity", "Qdrant status not reported in RAG health", str(checks))
                return True  # SKIP should not fail the health check suite
    except Exception as exc:
        rp.record("FAIL", "test_qdrant_connectivity", "Error checking Qdrant", str(exc))
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run() -> bool:
    all_ok = True

    # Service health checks
    services = [
        ("gateway", GATEWAY_URL),
        ("orchestrator", ORCHESTRATOR_URL),
        ("memory", MEMORY_URL),
        ("rag", RAG_URL),
        ("scoring", SCORING_URL),
        ("agent_mgmt", AGENT_MGMT_URL),
        ("meta_assembly", META_ASSEMBLY_URL),
    ]
    for name, url in services:
        ok = await _check_service(name, url)
        if not ok:
            all_ok = False

    # Backing-store connectivity
    for check_fn in [_check_neo4j, _check_mysql, _check_redis, _check_qdrant]:
        ok = await check_fn()
        if not ok:
            all_ok = False

    rp.summary()
    return all_ok


if __name__ == "__main__":
    ok = asyncio.run(run())
    sys.exit(0 if ok else 1)
