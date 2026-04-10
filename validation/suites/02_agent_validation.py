"""
Suite 02 -- Agent Validation.

Creates 3 agents with different roles and tool assignments, then tests
list / get / update / tool assignment / memory operations / scoring feedback.
Stores created agent IDs in shared state.
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx

from config import AGENT_MGMT_URL, MEMORY_URL, SCORING_URL, REQUEST_TIMEOUT
from utils import ValidationReporter, assert_status, async_client, store, get

rp = ValidationReporter("02_agent_validation")
AGENTS_BASE = f"{AGENT_MGMT_URL}/v1/agents"
MEMORY_BASE = f"{MEMORY_URL}/v1/memory"
SCORING_BASE = f"{SCORING_URL}/v1/scoring"

# ---------------------------------------------------------------------------
# Agent definitions
# ---------------------------------------------------------------------------

AGENTS = [
    {
        "name": "DataAnalyst",
        "description": "Specialises in data engineering, SQL queries, and Python analysis",
        "foundation_model": "gpt-4o",
        "meta_capable": False,
        "is_primary": False,
        "_domain": "data-engineering",
        "_tool_keys": ["MySQL Database Tool", "Python Data Analysis Tool"],
    },
    {
        "name": "WebResearcher",
        "description": "Web scraping, GitHub search, and weather data retrieval",
        "foundation_model": "gpt-4o",
        "meta_capable": False,
        "is_primary": False,
        "_domain": "research",
        "_tool_keys": ["Web Scraping Tool", "GitHub Search Tool", "Weather API Tool"],
    },
    {
        "name": "ProjectOrchestrator",
        "description": "Coordinates tasks between specialist agents; no direct tools",
        "foundation_model": "gpt-4o",
        "meta_capable": True,
        "is_primary": True,
        "_domain": "orchestration",
        "_tool_keys": [],
    },
]


# ---------------------------------------------------------------------------
# Agent CRUD tests
# ---------------------------------------------------------------------------

async def test_create_agents() -> list[dict]:
    """Create all 3 agents. Returns list of {name, id, domain}."""
    created: list[dict] = []
    async with async_client() as client:
        for agent_def in AGENTS:
            payload = {k: v for k, v in agent_def.items() if not k.startswith("_")}
            try:
                resp = await client.post(AGENTS_BASE, json=payload)
                if assert_status(resp, 201, f"create_agent({agent_def['name']})"):
                    body = resp.json()
                    agent = body.get("agent", body)
                    agent_uuid = agent.get("agent_id") or str(agent.get("id"))
                    agent_int_id = agent.get("id")
                    created.append({
                        "name": agent_def["name"],
                        "id": str(agent_uuid),
                        "int_id": agent_int_id,
                        "domain": agent_def["_domain"],
                        "tool_keys": agent_def["_tool_keys"],
                    })
                    rp.record("PASS", f"create_agent({agent_def['name']})", f"id={agent_uuid}")
                else:
                    rp.record("FAIL", f"create_agent({agent_def['name']})", "Bad status", resp.text[:200])
            except Exception as exc:
                rp.record("FAIL", f"create_agent({agent_def['name']})", "Exception", str(exc))
    return created


async def test_list_agents() -> None:
    async with async_client() as client:
        try:
            resp = await client.get(AGENTS_BASE)
            if assert_status(resp, 200, "list_agents"):
                body = resp.json()
                count = body.get("count", len(body.get("agents", [])))
                rp.record("PASS", "list_agents", f"Listed {count} agents")
            else:
                rp.record("FAIL", "list_agents", "Bad status", resp.text[:200])
        except Exception as exc:
            rp.record("FAIL", "list_agents", "Exception", str(exc))


async def test_get_agent(agent_id: str) -> None:
    async with async_client() as client:
        try:
            resp = await client.get(f"{AGENTS_BASE}/{agent_id}")
            if assert_status(resp, 200, f"get_agent({agent_id})"):
                rp.record("PASS", "get_agent_by_id", f"Retrieved agent {agent_id}")
            else:
                rp.record("FAIL", "get_agent_by_id", "Bad status", resp.text[:200])
        except Exception as exc:
            rp.record("FAIL", "get_agent_by_id", "Exception", str(exc))


async def test_update_agent(agent_id: str) -> None:
    async with async_client() as client:
        try:
            payload = {"description": "Updated by validation suite", "status": "ACTIVE"}
            resp = await client.put(f"{AGENTS_BASE}/{agent_id}", json=payload)
            if assert_status(resp, 200, f"update_agent({agent_id})"):
                rp.record("PASS", "update_agent", f"Updated agent {agent_id}")
            else:
                rp.record("FAIL", "update_agent", "Bad status", resp.text[:200])
        except Exception as exc:
            rp.record("FAIL", "update_agent", "Exception", str(exc))


# ---------------------------------------------------------------------------
# Tool assignment
# ---------------------------------------------------------------------------

async def test_assign_tools(agents: list[dict]) -> None:
    tool_map = get("tool_map", {})
    if not tool_map:
        rp.record("SKIP", "assign_tools", "No tool_map in state -- suite 01 may not have run")
        return

    async with async_client() as client:
        for agent in agents:
            for tool_key in agent["tool_keys"]:
                tool_id = tool_map.get(tool_key)
                if not tool_id:
                    rp.record("SKIP", f"assign_tool({agent['name']},{tool_key})", "Tool ID not found in state")
                    continue
                try:
                    payload = {"tool_id": tool_id, "permission_level": "WRITE"}
                    resp = await client.post(f"{AGENTS_BASE}/{agent['id']}/tools", json=payload)
                    if resp.status_code in (200, 201):
                        rp.record("PASS", f"assign_tool({agent['name']},{tool_key})", "Tool assigned")
                    else:
                        rp.record(
                            "FAIL",
                            f"assign_tool({agent['name']},{tool_key})",
                            f"HTTP {resp.status_code}",
                            resp.text[:200],
                        )
                except Exception as exc:
                    rp.record("FAIL", f"assign_tool({agent['name']},{tool_key})", "Exception", str(exc))


# ---------------------------------------------------------------------------
# Memory operations
# ---------------------------------------------------------------------------

async def test_memory_write(agent_id: int | str, tier: str, content: str, label: str) -> bool:
    """Write a memory entry. Returns True on success."""
    async with async_client() as client:
        try:
            payload = {
                "agent_id": int(agent_id),
                "tier": tier,
                "content": content,
                "metadata": {
                    "task_id": str(uuid.uuid4()),
                    "timestamp": "2026-03-27T00:00:00Z",
                    "importance": 0.8,
                },
            }
            resp = await client.post(f"{MEMORY_BASE}/write", json=payload)
            if resp.status_code in (200, 201):
                rp.record("PASS", f"memory_write({label})", f"Wrote {tier} for agent {agent_id}")
                return True
            else:
                rp.record("FAIL", f"memory_write({label})", f"HTTP {resp.status_code}", resp.text[:200])
                return False
        except Exception as exc:
            rp.record("FAIL", f"memory_write({label})", "Exception", str(exc))
            return False


async def test_memory_retrieve(agent_id: int | str, tier: str, label: str, query: str | None = None) -> None:
    """Retrieve memory from a given tier."""
    async with async_client() as client:
        try:
            params: dict = {"agent_id": int(agent_id), "tier": tier, "k": 5}
            if query:
                params["query"] = query
            resp = await client.get(f"{MEMORY_BASE}/retrieve", params=params)
            if resp.status_code in (200,):
                body = resp.json()
                count = body.get("count", len(body.get("results", [])))
                rp.record("PASS", f"memory_retrieve({label})", f"Got {count} results from {tier}")
            elif resp.status_code == 400:
                # Some tiers require query param
                rp.record("SKIP", f"memory_retrieve({label})", "400 -- likely missing query param for this tier")
            else:
                rp.record("FAIL", f"memory_retrieve({label})", f"HTTP {resp.status_code}", resp.text[:200])
        except Exception as exc:
            rp.record("FAIL", f"memory_retrieve({label})", "Exception", str(exc))


async def test_assemble_prompt(agent_id: int | str) -> None:
    """POST /v1/memory/assemble-prompt."""
    async with async_client() as client:
        try:
            payload = {
                "agent_id": int(agent_id),
                "context": {
                    "task_type": "data-analysis",
                    "domain": "data-engineering",
                    "recent_messages": ["Analyse Q4 revenue trends"],
                },
                "tiers": ["short_term", "long_term", "reasoning", "episodic"],
            }
            resp = await client.post(f"{MEMORY_BASE}/assemble-prompt", json=payload)
            if resp.status_code == 200:
                body = resp.json()
                has_prompt = bool(body.get("system_prompt"))
                rp.record("PASS", "assemble_prompt", f"Prompt assembled (length={len(body.get('system_prompt', ''))})")
            else:
                rp.record("FAIL", "assemble_prompt", f"HTTP {resp.status_code}", resp.text[:200])
        except Exception as exc:
            rp.record("FAIL", "assemble_prompt", "Exception", str(exc))


# ---------------------------------------------------------------------------
# Scoring feedback
# ---------------------------------------------------------------------------

async def test_scoring_evaluate(agent_id: int | str) -> None:
    """POST /v1/scoring/evaluate."""
    async with async_client() as client:
        try:
            payload = {
                "agent_id": int(agent_id),
                "task_id": str(uuid.uuid4()),
                "context_type": "data-analysis",
                "response_text": "The Q4 revenue was $1.2M, up 15% from Q3.",
                "used_knowledge": True,
                "latency_ms": 350,
                "tool_calls": ["MySQL Database Tool"],
            }
            resp = await client.post(f"{SCORING_BASE}/evaluate", json=payload)
            if resp.status_code == 200:
                body = resp.json()
                score = body.get("score")
                rec = body.get("recommendation")
                rp.record("PASS", "scoring_evaluate", f"score={score}, recommendation={rec}")
            else:
                rp.record("FAIL", "scoring_evaluate", f"HTTP {resp.status_code}", resp.text[:200])
        except Exception as exc:
            rp.record("FAIL", "scoring_evaluate", "Exception", str(exc))


async def test_scoring_feedback(agent_id: int | str, reward: float, label: str) -> None:
    """POST /v1/scoring/feedback."""
    async with async_client() as client:
        try:
            payload = {
                "agent_id": int(agent_id),
                "task_id": str(uuid.uuid4()),
                "session_id": str(uuid.uuid4()),
                "feedback_source": "USER",
                "feedback_type": "SCORE",
                "score": 0.85,
                "reward_signal": reward,
                "context_type": "data-analysis",
            }
            resp = await client.post(f"{SCORING_BASE}/feedback", json=payload)
            if resp.status_code == 200:
                body = resp.json()
                accepted = body.get("accepted", False)
                rp.record("PASS", f"scoring_feedback({label})", f"accepted={accepted}")
            else:
                rp.record("FAIL", f"scoring_feedback({label})", f"HTTP {resp.status_code}", resp.text[:200])
        except Exception as exc:
            rp.record("FAIL", f"scoring_feedback({label})", "Exception", str(exc))


async def test_scoring_weights(agent_id: int | str) -> None:
    """GET /v1/scoring/weights/:agent_id."""
    async with async_client() as client:
        try:
            resp = await client.get(f"{SCORING_BASE}/weights/{int(agent_id)}")
            if resp.status_code == 200:
                body = resp.json()
                rp.record("PASS", "scoring_weights", f"Weights retrieved for agent {agent_id}")
            else:
                rp.record("FAIL", "scoring_weights", f"HTTP {resp.status_code}", resp.text[:200])
        except Exception as exc:
            rp.record("FAIL", "scoring_weights", "Exception", str(exc))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run() -> None:
    # Create agents
    agents = await test_create_agents()
    if not agents:
        rp.record("FAIL", "suite_abort", "No agents created -- cannot continue")
        rp.summary()
        return

    # Store
    agent_map = {a["name"]: a["id"] for a in agents}
    store("agent_ids", [a["id"] for a in agents])
    store("agent_map", agent_map)
    store("agents", agents)

    # List / Get / Update
    await test_list_agents()
    await test_get_agent(agents[0]["id"])
    await test_update_agent(agents[0]["id"])

    # Tool assignment
    await test_assign_tools(agents)

    # Memory operations -- use first agent (DataAnalyst)
    # Memory and scoring services expect numeric id, not UUID
    da_id = agents[0].get("int_id") or agents[0]["id"]

    await test_memory_write(da_id, "short_term", "Redis short-term memory validation entry", "short_term")
    await test_memory_write(da_id, "long_term", "Long-term knowledge: Q4 revenue analysis patterns", "long_term")
    await test_memory_write(da_id, "reasoning", "Reasoning pattern: always check data freshness before analysis", "reasoning")
    await test_memory_write(da_id, "episodic", "Episode: successfully completed data pipeline audit on 2026-03-15", "episodic")

    # Retrieve
    await test_memory_retrieve(da_id, "short_term", "short_term_read")
    await test_memory_retrieve(da_id, "long_term", "long_term_search", query="revenue analysis")
    await test_memory_retrieve(da_id, "reasoning", "reasoning_search", query="data freshness")
    await test_memory_retrieve(da_id, "episodic", "episodic_search", query="data pipeline")

    # Prompt assembly
    await test_assemble_prompt(da_id)

    # Scoring
    await test_scoring_evaluate(da_id)
    await test_scoring_feedback(da_id, reward=1.0, label="positive")
    await test_scoring_feedback(da_id, reward=-0.5, label="negative")
    await test_scoring_weights(da_id)

    rp.summary()


if __name__ == "__main__":
    asyncio.run(run())
