"""
Suite 03 -- Team Validation.

Creates a team with a hierarchy of agents, then tests list / get / update /
add-agent / remove-agent / validate operations.
Stores team ID in shared state.
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx

from config import AGENT_MGMT_URL, REQUEST_TIMEOUT
from utils import ValidationReporter, assert_status, async_client, store, get

rp = ValidationReporter("03_team_validation")
TEAMS_BASE = f"{AGENT_MGMT_URL}/v1/teams"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_create_team() -> str | None:
    """Create 'Data Research Team'. Returns team_id or None."""
    async with async_client() as client:
        try:
            payload = {
                "name": "Data Research Team",
                "description": "Cross-functional team combining data analysis and web research",
                "use_smart_workflow": True,
                "accuracy_threshold": 0.75,
                "max_retries": 3,
                "retry_strategy": "EXPONENTIAL",
            }
            resp = await client.post(TEAMS_BASE, json=payload)
            if assert_status(resp, 201, "create_team"):
                body = resp.json()
                team = body.get("team", body)
                team_id = team.get("team_id") or team.get("id")
                rp.record("PASS", "create_team", f"Created team id={team_id}")
                return str(team_id)
            else:
                rp.record("FAIL", "create_team", "Bad status", resp.text[:200])
                return None
        except Exception as exc:
            rp.record("FAIL", "create_team", "Exception", str(exc))
            return None


async def test_add_agent_to_team(team_id: str, agent_id: str, role: str, priority: int, label: str) -> bool:
    """POST /v1/teams/:team_id/agents."""
    async with async_client() as client:
        try:
            payload = {
                "agent_id": agent_id,
                "priority": priority,
                "role": role,
            }
            resp = await client.post(f"{TEAMS_BASE}/{team_id}/agents", json=payload)
            if resp.status_code in (200, 201):
                rp.record("PASS", f"add_agent({label})", f"Added agent {agent_id} as {role}")
                return True
            else:
                rp.record("FAIL", f"add_agent({label})", f"HTTP {resp.status_code}", resp.text[:200])
                return False
        except Exception as exc:
            rp.record("FAIL", f"add_agent({label})", "Exception", str(exc))
            return False


async def test_list_teams() -> None:
    async with async_client() as client:
        try:
            resp = await client.get(TEAMS_BASE)
            if assert_status(resp, 200, "list_teams"):
                body = resp.json()
                count = body.get("count", len(body.get("teams", [])))
                rp.record("PASS", "list_teams", f"Listed {count} teams")
            else:
                rp.record("FAIL", "list_teams", "Bad status", resp.text[:200])
        except Exception as exc:
            rp.record("FAIL", "list_teams", "Exception", str(exc))


async def test_get_team(team_id: str) -> None:
    async with async_client() as client:
        try:
            resp = await client.get(f"{TEAMS_BASE}/{team_id}")
            if assert_status(resp, 200, f"get_team({team_id})"):
                body = resp.json()
                team = body.get("team", body)
                name = team.get("name", "?")
                rp.record("PASS", "get_team_by_id", f"Retrieved team '{name}'")
            else:
                rp.record("FAIL", "get_team_by_id", "Bad status", resp.text[:200])
        except Exception as exc:
            rp.record("FAIL", "get_team_by_id", "Exception", str(exc))


async def test_update_team(team_id: str) -> None:
    """PUT /v1/teams/:team_id -- update accuracy threshold and retries."""
    async with async_client() as client:
        try:
            payload = {
                "accuracy_threshold": 0.80,
                "max_retries": 5,
                "description": "Updated by validation suite -- higher accuracy bar",
            }
            resp = await client.put(f"{TEAMS_BASE}/{team_id}", json=payload)
            if assert_status(resp, 200, f"update_team({team_id})"):
                rp.record("PASS", "update_team", f"Updated team {team_id}")
            else:
                rp.record("FAIL", "update_team", "Bad status", resp.text[:200])
        except Exception as exc:
            rp.record("FAIL", "update_team", "Exception", str(exc))


async def test_update_team_priorities(team_id: str) -> None:
    """Update the team's retry strategy to test priority update path."""
    async with async_client() as client:
        try:
            payload = {"retry_strategy": "FIBONACCI"}
            resp = await client.put(f"{TEAMS_BASE}/{team_id}", json=payload)
            if assert_status(resp, 200, "update_priorities"):
                rp.record("PASS", "update_priorities", "Changed retry strategy to FIBONACCI")
            else:
                rp.record("FAIL", "update_priorities", "Bad status", resp.text[:200])
        except Exception as exc:
            rp.record("FAIL", "update_priorities", "Exception", str(exc))


async def test_remove_agent_from_team(team_id: str, agent_id: str, label: str) -> None:
    """DELETE /v1/teams/:team_id/agents/:agent_id."""
    async with async_client() as client:
        try:
            resp = await client.delete(f"{TEAMS_BASE}/{team_id}/agents/{agent_id}")
            if resp.status_code in (200, 204):
                rp.record("PASS", f"remove_agent({label})", f"Removed agent {agent_id}")
            else:
                rp.record("FAIL", f"remove_agent({label})", f"HTTP {resp.status_code}", resp.text[:200])
        except Exception as exc:
            rp.record("FAIL", f"remove_agent({label})", "Exception", str(exc))


async def test_re_add_agent(team_id: str, agent_id: str) -> None:
    """Re-add a previously removed agent to confirm idempotency."""
    async with async_client() as client:
        try:
            payload = {"agent_id": agent_id, "priority": 3, "role": "backup"}
            resp = await client.post(f"{TEAMS_BASE}/{team_id}/agents", json=payload)
            if resp.status_code in (200, 201):
                rp.record("PASS", "re_add_agent", f"Re-added agent {agent_id}")
            else:
                rp.record("FAIL", "re_add_agent", f"HTTP {resp.status_code}", resp.text[:200])
        except Exception as exc:
            rp.record("FAIL", "re_add_agent", "Exception", str(exc))


async def test_validate_team(team_id: str) -> None:
    """Validate team by fetching it and checking structure."""
    async with async_client() as client:
        try:
            resp = await client.get(f"{TEAMS_BASE}/{team_id}")
            if resp.status_code != 200:
                rp.record("FAIL", "validate_team", f"Cannot fetch team: HTTP {resp.status_code}")
                return
            body = resp.json()
            team = body.get("team", body)

            # Check required fields exist
            errors: list[str] = []
            for field in ("name", "accuracy_threshold", "max_retries", "retry_strategy"):
                if field not in team and field not in body:
                    errors.append(f"missing field: {field}")

            if errors:
                rp.record("FAIL", "validate_team", "Structural issues", "; ".join(errors))
            else:
                rp.record("PASS", "validate_team", "Team structure valid")
        except Exception as exc:
            rp.record("FAIL", "validate_team", "Exception", str(exc))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run() -> None:
    agent_map = get("agent_map", {})
    if not agent_map:
        rp.record("SKIP", "suite_skip", "No agent_map in state -- suite 02 may not have run")
        rp.summary()
        return

    orchestrator_id = agent_map.get("ProjectOrchestrator")
    da_id = agent_map.get("DataAnalyst")
    wr_id = agent_map.get("WebResearcher")

    if not all([orchestrator_id, da_id, wr_id]):
        rp.record("FAIL", "suite_abort", "Missing agent IDs in state", str(agent_map))
        rp.summary()
        return

    # Create team
    team_id = await test_create_team()
    if not team_id:
        rp.summary()
        return

    store("team_id", team_id)

    # Add agents with hierarchy
    await test_add_agent_to_team(team_id, orchestrator_id, "orchestrator", 0, "orchestrator")
    await test_add_agent_to_team(team_id, da_id, "specialist", 1, "DataAnalyst_specialist")
    await test_add_agent_to_team(team_id, wr_id, "specialist", 2, "WebResearcher_specialist")

    # List / Get
    await test_list_teams()
    await test_get_team(team_id)

    # Update team metadata and priorities
    await test_update_team(team_id)
    await test_update_team_priorities(team_id)

    # Remove an agent, then re-add
    await test_remove_agent_from_team(team_id, wr_id, "WebResearcher")
    await test_re_add_agent(team_id, wr_id)

    # Validate final state
    await test_validate_team(team_id)

    rp.summary()


if __name__ == "__main__":
    asyncio.run(run())
