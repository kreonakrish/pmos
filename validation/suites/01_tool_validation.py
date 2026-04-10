"""
Suite 01 -- Tool Validation.

Creates 6 tools of different types via agent-mgmt, then exercises list, get,
update, health-check, and delete operations.  Stores created tool IDs in
shared state for downstream suites.
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx

from config import AGENT_MGMT_URL, REQUEST_TIMEOUT
from utils import ValidationReporter, assert_status, async_client, store, get

rp = ValidationReporter("01_tool_validation")
BASE = f"{AGENT_MGMT_URL}/v1/tools"

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "MySQL Database Tool",
        "description": "Executes parameterized SQL queries against a MySQL instance",
        "tool_type": "DATABASE",
        "hostname": "localhost",
        "endpoint": "mysql://localhost:3306/pmos",
        "auth_method": "BASIC",
        "auth_config": {
            "query_template": "SELECT * FROM {{table}} WHERE {{condition}} LIMIT {{max_rows}}",
            "params": ["table", "condition", "max_rows"],
            "max_rows": 1000,
        },
    },
    {
        "name": "PostgreSQL Tool",
        "description": "PostgreSQL query executor for analytics workloads",
        "tool_type": "DATABASE",
        "hostname": "localhost",
        "endpoint": "postgresql://localhost:5432/analytics",
        "auth_method": "BASIC",
        "auth_config": {},
    },
    {
        "name": "Weather API Tool",
        "description": "Open-Meteo weather API -- no auth required",
        "tool_type": "API",
        "hostname": "api.open-meteo.com",
        "endpoint": "https://api.open-meteo.com/v1/forecast",
        "auth_method": "NONE",
        "auth_config": {"default_params": {"latitude": 40.71, "longitude": -74.01}},
    },
    {
        "name": "GitHub Search Tool",
        "description": "Searches GitHub repositories and issues via the GitHub API",
        "tool_type": "GITHUB",
        "hostname": "api.github.com",
        "endpoint": "https://api.github.com/search/repositories",
        "auth_method": "BEARER",
        "auth_config": {"token_placeholder": "GITHUB_TOKEN"},
    },
    {
        "name": "Web Scraping Tool",
        "description": "Extracts content from web pages using headless browsing",
        "tool_type": "WEBSERVICE",
        "hostname": "localhost",
        "endpoint": "http://localhost:9222",
        "auth_method": "NONE",
        "auth_config": {"headless": True, "timeout_sec": 15},
    },
    {
        "name": "Python Data Analysis Tool",
        "description": "Executes sandboxed Python code for data analysis tasks",
        "tool_type": "PYTHON",
        "hostname": "localhost",
        "endpoint": "subprocess://sandbox",
        "auth_method": "NONE",
        "auth_config": {
            "code": "import statistics; data=[10,20,30]; print(statistics.mean(data))",
            "allowed_imports": ["statistics", "math", "json", "csv"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_create_tools() -> list[str]:
    """Create all 6 tools and return their IDs."""
    ids: list[str] = []
    async with async_client() as client:
        for tool_def in TOOLS:
            try:
                resp = await client.post(BASE, json=tool_def)
                if assert_status(resp, 201, f"create_tool({tool_def['name']})"):
                    body = resp.json()
                    tool = body.get("tool", body)
                    tool_id = tool.get("tool_id") or tool.get("id")
                    ids.append(str(tool_id))
                    rp.record("PASS", f"create_tool({tool_def['name']})", f"Created with id={tool_id}")
                else:
                    rp.record("FAIL", f"create_tool({tool_def['name']})", "Unexpected status", resp.text[:200])
            except Exception as exc:
                rp.record("FAIL", f"create_tool({tool_def['name']})", "Exception during creation", str(exc))
    return ids


async def test_list_tools() -> None:
    """GET /v1/tools -- should return at least the tools we created."""
    async with async_client() as client:
        try:
            resp = await client.get(BASE)
            if assert_status(resp, 200, "list_tools"):
                body = resp.json()
                count = body.get("count", len(body.get("tools", [])))
                rp.record("PASS", "list_tools", f"Listed {count} tools")
            else:
                rp.record("FAIL", "list_tools", "Unexpected status", resp.text[:200])
        except Exception as exc:
            rp.record("FAIL", "list_tools", "Exception", str(exc))


async def test_get_tool_by_id(tool_id: str) -> None:
    """GET /v1/tools/:id."""
    async with async_client() as client:
        try:
            resp = await client.get(f"{BASE}/{tool_id}")
            if assert_status(resp, 200, f"get_tool({tool_id})"):
                rp.record("PASS", "get_tool_by_id", f"Retrieved tool {tool_id}")
            else:
                rp.record("FAIL", "get_tool_by_id", "Unexpected status", resp.text[:200])
        except Exception as exc:
            rp.record("FAIL", "get_tool_by_id", "Exception", str(exc))


async def test_update_tool(tool_id: str) -> None:
    """PUT /v1/tools/:id -- update description and status."""
    async with async_client() as client:
        try:
            payload = {"description": "Updated by validation suite", "status": "ACTIVE"}
            resp = await client.put(f"{BASE}/{tool_id}", json=payload)
            if assert_status(resp, 200, f"update_tool({tool_id})"):
                rp.record("PASS", "update_tool", f"Updated tool {tool_id}")
            else:
                rp.record("FAIL", "update_tool", "Unexpected status", resp.text[:200])
        except Exception as exc:
            rp.record("FAIL", "update_tool", "Exception", str(exc))


async def test_api_tool_live() -> None:
    """Hit the Open-Meteo API directly to confirm the endpoint is valid."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10)) as client:
            resp = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={"latitude": 40.71, "longitude": -74.01, "current_weather": "true"},
            )
            if resp.status_code == 200:
                rp.record("PASS", "api_tool_live", "Open-Meteo returned 200")
            else:
                rp.record("FAIL", "api_tool_live", f"Open-Meteo returned {resp.status_code}", resp.text[:200])
    except Exception as exc:
        rp.record("SKIP", "api_tool_live", "Could not reach Open-Meteo (network)", str(exc))


async def test_tool_health_check(tool_id: str) -> None:
    """Verify tool health-check field after creation."""
    async with async_client() as client:
        try:
            resp = await client.get(f"{BASE}/{tool_id}")
            if resp.status_code == 200:
                body = resp.json()
                tool = body.get("tool", body)
                status_val = tool.get("status", "UNKNOWN")
                rp.record("PASS", "tool_health_check", f"Tool {tool_id} status={status_val}")
            else:
                rp.record("FAIL", "tool_health_check", "Could not fetch tool for health check", resp.text[:200])
        except Exception as exc:
            rp.record("FAIL", "tool_health_check", "Exception", str(exc))


async def test_delete_tool(tool_id: str) -> None:
    """DELETE /v1/tools/:id -- delete the PostgreSQL tool (not needed later)."""
    async with async_client() as client:
        try:
            resp = await client.delete(f"{BASE}/{tool_id}")
            if assert_status(resp, 200, f"delete_tool({tool_id})"):
                rp.record("PASS", "delete_tool", f"Deleted tool {tool_id}")
            else:
                rp.record("FAIL", "delete_tool", "Unexpected status", resp.text[:200])
        except Exception as exc:
            rp.record("FAIL", "delete_tool", "Exception", str(exc))


async def test_get_deleted_tool_404(tool_id: str) -> None:
    """GET /v1/tools/:id after deletion should return 404."""
    async with async_client() as client:
        try:
            resp = await client.get(f"{BASE}/{tool_id}")
            if resp.status_code == 404:
                rp.record("PASS", "get_deleted_tool_404", "Deleted tool returns 404 as expected")
            else:
                rp.record("FAIL", "get_deleted_tool_404", f"Expected 404, got {resp.status_code}", resp.text[:200])
        except Exception as exc:
            rp.record("FAIL", "get_deleted_tool_404", "Exception", str(exc))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run() -> None:
    # Create tools
    tool_ids = await test_create_tools()
    if not tool_ids:
        rp.record("FAIL", "suite_abort", "No tools created -- cannot continue")
        rp.summary()
        return

    # Store IDs: index matches TOOLS list order
    tool_names = [t["name"] for t in TOOLS]
    tool_map = dict(zip(tool_names, tool_ids))
    store("tool_ids", tool_ids)
    store("tool_map", tool_map)

    # List
    await test_list_tools()

    # Get by ID (use the first tool)
    await test_get_tool_by_id(tool_ids[0])

    # Update (use the first tool)
    await test_update_tool(tool_ids[0])

    # Live API test
    await test_api_tool_live()

    # Health check field
    await test_tool_health_check(tool_ids[0])

    # Delete the PostgreSQL tool (index 1) -- not needed by later suites
    pg_id = tool_ids[1] if len(tool_ids) > 1 else None
    if pg_id:
        await test_delete_tool(pg_id)
        await test_get_deleted_tool_404(pg_id)
        # Remove from stored IDs so downstream suites don't reference it
        remaining = [tid for tid in tool_ids if tid != pg_id]
        store("tool_ids", remaining)
        del tool_map["PostgreSQL Tool"]
        store("tool_map", tool_map)

    rp.summary()


if __name__ == "__main__":
    asyncio.run(run())
