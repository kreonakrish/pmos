"""Unit tests for the python_reduce step-8 aggregation strategy.

Tested behaviours:
  - When self._current_aggregation_strategy=='python_reduce' AND the team
    has a PYTHON-tool agent → _execute_agent_with_tools is called with
    PythonAnalyst, the encoded per-source JSON in the description, and
    the response is returned verbatim.
  - When no PYTHON agent on the team → fall back to LLM synthesis (the
    legacy _step8_aggregation path).
  - When sandbox raises → fall back to LLM synthesis (no 500 to user).
  - When zero successful node results → return the same canned string
    as the LLM path so callers don't branch on emptiness.

These tests stub the heavy collaborators (LLM, executor, Neo4j) and
exercise the helper in isolation. Behaviour parity with
_step8_aggregation on the fallback path matters more than the exact
prompt text.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agent_selector import Agent
from app.services.patterns import TeamContext
from app.services.pipeline import PipelineService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_service(
    *,
    llm_complete_response: str = "fallback-llm-answer",
    executor_response: str = "python-reduced-answer",
    executor_raises: bool = False,
) -> PipelineService:
    """Build a PipelineService with stubbed downstreams."""
    neo4j = AsyncMock()
    neo4j.update_graph_status = AsyncMock()
    neo4j.run_query = AsyncMock(return_value=[])

    redis = AsyncMock()
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=llm_complete_response)

    memory = AsyncMock()
    scoring = AsyncMock()
    rag = AsyncMock()
    meta = AsyncMock()

    svc = PipelineService(
        neo4j=neo4j,
        redis=redis,
        llm=llm,
        memory=memory,
        scoring=scoring,
        rag=rag,
        meta=meta,
    )

    # Stub the executor — _step8_python_reduce calls _execute_agent_with_tools
    # which is heavy (sandbox HTTP roundtrip). Replace it.
    if executor_raises:
        async def _raise(*a, **kw):
            raise RuntimeError("sandbox blew up")
        svc._execute_agent_with_tools = _raise  # type: ignore[assignment]
    else:
        async def _ok(*a, **kw):
            return executor_response, ["Python Analysis Tool"]
        svc._execute_agent_with_tools = _ok  # type: ignore[assignment]

    # Skip the agent-id resolver — not under test.
    svc._resolve_agent_db_id = MagicMock(return_value=42)
    return svc


def _team_with_python() -> TeamContext:
    return TeamContext(
        team_id="t-1",
        name="Test",
        agents=[
            {
                "agent_id": "py-1",
                "agent_name": "PythonAnalyst",
                "foundation_model": "gpt-4o",
                "role": "specialist",
                "tools": [{"tool_type": "PYTHON",
                           "tool_name": "Python Analysis Tool"}],
            },
            {
                "agent_id": "db-1",
                "agent_name": "DBAnalyst",
                "tools": [{"tool_type": "DATABASE", "tool_name": "Servicing DB"}],
            },
        ],
    )


def _team_without_python() -> TeamContext:
    return TeamContext(
        team_id="t-2",
        name="No-Python",
        agents=[
            {
                "agent_id": "db-1",
                "agent_name": "DBAnalyst",
                "tools": [{"tool_type": "DATABASE", "tool_name": "Sakila"}],
            },
        ],
    )


def _node_results(successful: int = 2, failed: int = 0) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for i in range(successful):
        rows.append({
            "node_id": f"n-{i}",
            "description": f"count loans in tool-{i}",
            "llm_response": f"tool-{i} found 1247 loans",
            "status": "SUCCESS",
            "agent_id": f"a-{i}",
            "agent_name": f"Agent{i}",
            "tools_used": [f"tool-{i}"],
        })
    for i in range(failed):
        rows.append({
            "node_id": f"f-{i}",
            "description": "failed task",
            "llm_response": "",
            "status": "FAILED",
        })
    return rows


# ---------------------------------------------------------------------------
# Routing — execute() picks the right step-8 based on the strategy flag
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_step8_python_reduce_routes_to_python_agent_when_present():
    svc = _make_service(executor_response="**Total: 45 matches**")
    svc._last_team_context = _team_with_python()

    result = await svc._step8_python_reduce(
        message="how many total loans?",
        node_results=_node_results(successful=2),
        graph_id="g-1",
        primary=None,
        trace_id="tr-1",
        instructions="Sum the per-source counts.",
    )
    assert result == "**Total: 45 matches**"
    # Graph marked COMPLETED so step-9 can proceed.
    svc._neo4j.update_graph_status.assert_awaited_once()


@pytest.mark.asyncio
async def test_step8_python_reduce_falls_back_when_no_python_agent():
    svc = _make_service(llm_complete_response="legacy-llm-answer")
    svc._last_team_context = _team_without_python()

    result = await svc._step8_python_reduce(
        message="how many?",
        node_results=_node_results(successful=2),
        graph_id="g-2",
        primary=None,
        trace_id="tr-2",
    )
    assert result == "legacy-llm-answer"
    svc._llm.complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_step8_python_reduce_falls_back_when_sandbox_raises():
    """A broken Python sandbox must NOT cripple the user's answer —
    we degrade to LLM synthesis."""
    svc = _make_service(
        llm_complete_response="legacy-after-failure",
        executor_raises=True,
    )
    svc._last_team_context = _team_with_python()

    result = await svc._step8_python_reduce(
        message="how many?",
        node_results=_node_results(successful=1),
        graph_id="g-3",
        primary=None,
        trace_id="tr-3",
    )
    assert result == "legacy-after-failure"
    svc._llm.complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_step8_python_reduce_returns_canned_when_no_successful_results():
    """Mirrors _step8_aggregation's behaviour for empty input."""
    svc = _make_service()
    svc._last_team_context = _team_with_python()

    result = await svc._step8_python_reduce(
        message="how many?",
        node_results=_node_results(successful=0, failed=2),
        graph_id="g-4",
        primary=None,
        trace_id="tr-4",
    )
    assert "unable to complete" in result.lower()


@pytest.mark.asyncio
async def test_step8_python_reduce_passes_results_as_json_to_executor():
    """The reducer must see the per-source results in a structured form
    Python can parse, not free-text the LLM has to re-extract."""
    captured: Dict[str, Any] = {}

    async def _capture(**kwargs):
        captured.update(kwargs)
        return "ok", []

    svc = _make_service()
    svc._last_team_context = _team_with_python()
    svc._execute_agent_with_tools = _capture  # type: ignore[assignment]

    await svc._step8_python_reduce(
        message="count loans",
        node_results=[
            {"description": "count in tool A", "llm_response": "1200",
             "status": "SUCCESS", "agent_name": "A", "tools_used": ["a"]},
            {"description": "count in tool B", "llm_response": "350",
             "status": "SUCCESS", "agent_name": "B", "tools_used": ["b"]},
        ],
        graph_id="g-5",
        primary=None,
        trace_id="tr-5",
        instructions="Sum and avoid double counting.",
    )

    desc = captured["task_description"]
    assert "count loans" in desc
    assert "Sum and avoid double counting." in desc
    assert "count in tool A" in desc
    assert "count in tool B" in desc
    # The encoded payload is JSON inside a code fence — Python can parse it.
    import json, re
    m = re.search(r"```json\n(.*?)```", desc, re.DOTALL)
    assert m, "expected JSON fence in description"
    parsed = json.loads(m.group(1))
    assert isinstance(parsed, list) and len(parsed) == 2
    assert parsed[0]["agent"] == "A"
    assert parsed[1]["agent"] == "B"


@pytest.mark.asyncio
async def test_step8_python_reduce_uses_default_instructions_when_none_given():
    captured: Dict[str, Any] = {}

    async def _capture(**kwargs):
        captured.update(kwargs)
        return "ok", []

    svc = _make_service()
    svc._last_team_context = _team_with_python()
    svc._execute_agent_with_tools = _capture  # type: ignore[assignment]

    await svc._step8_python_reduce(
        message="anything",
        node_results=_node_results(successful=1),
        graph_id="g-6",
        primary=None,
        trace_id="tr-6",
        instructions="",  # empty — fall back to default
    )
    desc = captured["task_description"]
    assert "Use your Python tool" in desc


# ---------------------------------------------------------------------------
# TeamContext PYTHON filter — sanity check the helper this all relies on
# ---------------------------------------------------------------------------

def test_team_context_finds_python_agents():
    tc = _team_with_python()
    py = tc.agents_with_tool_type("PYTHON")
    assert len(py) == 1
    assert py[0]["agent_name"] == "PythonAnalyst"


def test_team_context_returns_empty_when_no_python():
    tc = _team_without_python()
    assert tc.agents_with_tool_type("PYTHON") == []


# ---------------------------------------------------------------------------
# Strategy flag — the per-request reset must work so a prior python_reduce
# request doesn't leak into the next one
# ---------------------------------------------------------------------------

def test_aggregation_strategy_defaults_to_default():
    svc = _make_service()
    assert svc._current_aggregation_strategy == "default"
    assert svc._current_aggregation_instructions == ""


# ---------------------------------------------------------------------------
# Phase 6 — reducer gets join keys + expected columns from bid plans
# ---------------------------------------------------------------------------

import json as _json


def _service_with_bid_meta(bid_meta_rows):
    """A pipeline whose Neo4j returns the given rows for the bid-meta lookup."""
    svc = _make_service()
    svc._last_team_context = _team_with_python()
    svc._neo4j.run_query = AsyncMock(return_value=bid_meta_rows)
    return svc


def _capture_executor(svc):
    captured: Dict[str, Any] = {}

    async def _capture(**kwargs):
        captured.update(kwargs)
        return "ok", []

    svc._execute_agent_with_tools = _capture  # type: ignore[assignment]
    return captured


@pytest.mark.asyncio
async def test_python_reduce_passes_expected_columns_per_source():
    """Each input item should carry the bid plan's `expected_columns`
    so the reducer's prompt knows what shape each agent promised."""
    svc = _service_with_bid_meta([
        {"node_id": "n-orig", "bid_plan_format": "structured",
         "bid_plan": _json.dumps([{"tool": "OrigDB", "kind": "sql",
                                   "expected_columns": ["loan_id",
                                                        "originated_at"]}]),
         "bid_coverage": _json.dumps({"answerable": ["origination"]})},
        {"node_id": "n-serv", "bid_plan_format": "structured",
         "bid_plan": _json.dumps([{"tool": "ServDB", "kind": "sql",
                                   "expected_columns": ["loan_id",
                                                        "current_status"]}]),
         "bid_coverage": _json.dumps({"answerable": ["servicing"]})},
    ])
    captured = _capture_executor(svc)

    await svc._step8_python_reduce(
        message="cross-schema",
        node_results=[
            {"node_id": "n-orig", "description": "originated count",
             "llm_response": "[{loan_id:1}]", "status": "SUCCESS",
             "agent_name": "OrigAgent"},
            {"node_id": "n-serv", "description": "servicing tenure",
             "llm_response": "[{loan_id:1, current_status: ACTIVE}]",
             "status": "SUCCESS", "agent_name": "ServAgent"},
        ],
        graph_id="g-1", primary=None, trace_id="tr-1",
    )

    desc = captured["task_description"]
    # Each per-source entry should carry expected_columns.
    m = __import__("re").search(r"```json\n(.*?)```", desc, __import__("re").DOTALL)
    assert m
    parsed = _json.loads(m.group(1))
    assert parsed[0]["expected_columns"] == ["loan_id", "originated_at"]
    assert parsed[1]["expected_columns"] == ["loan_id", "current_status"]
    assert parsed[0]["answerable"] == ["origination"]


@pytest.mark.asyncio
async def test_python_reduce_surfaces_candidate_join_keys():
    """A column name in two or more agents' expected_columns becomes a
    candidate join key the reducer is told to merge on."""
    svc = _service_with_bid_meta([
        {"node_id": "n-1", "bid_plan_format": "structured",
         "bid_plan": _json.dumps([{"tool": "A", "kind": "sql",
                                   "expected_columns": ["loan_id", "amount"]}]),
         "bid_coverage": _json.dumps({})},
        {"node_id": "n-2", "bid_plan_format": "structured",
         "bid_plan": _json.dumps([{"tool": "B", "kind": "sql",
                                   "expected_columns": ["loan_id", "status"]}]),
         "bid_coverage": _json.dumps({})},
    ])
    captured = _capture_executor(svc)

    await svc._step8_python_reduce(
        message="cross-schema",
        node_results=[
            {"node_id": "n-1", "description": "from A", "llm_response": "ok",
             "status": "SUCCESS"},
            {"node_id": "n-2", "description": "from B", "llm_response": "ok",
             "status": "SUCCESS"},
        ],
        graph_id="g-2", primary=None, trace_id="tr-2",
    )

    desc = captured["task_description"]
    # `loan_id` appears in both → join key. `amount` and `status` only once → not.
    assert "CANDIDATE JOIN KEYS" in desc
    assert "loan_id" in desc.split("CANDIDATE JOIN KEYS")[1].split("\n")[0]
    # Make sure unique columns aren't surfaced as keys (they may appear
    # elsewhere in the prompt as expected_columns, but not in the keys list).
    keys_line = desc.split("CANDIDATE JOIN KEYS")[1].split("\n")[0]
    assert "amount" not in keys_line
    assert "status" not in keys_line


@pytest.mark.asyncio
async def test_python_reduce_skips_join_hint_when_no_overlap():
    """Single-source case (no overlap) → no CANDIDATE JOIN KEYS block."""
    svc = _service_with_bid_meta([
        {"node_id": "n-1", "bid_plan_format": "structured",
         "bid_plan": _json.dumps([{"tool": "A", "kind": "sql",
                                   "expected_columns": ["foo"]}]),
         "bid_coverage": _json.dumps({})},
    ])
    captured = _capture_executor(svc)

    await svc._step8_python_reduce(
        message="single",
        node_results=[
            {"node_id": "n-1", "description": "x", "llm_response": "ok",
             "status": "SUCCESS"},
        ],
        graph_id="g-3", primary=None, trace_id="tr-3",
    )
    assert "CANDIDATE JOIN KEYS" not in captured["task_description"]


@pytest.mark.asyncio
async def test_python_reduce_ignores_legacy_bids_for_join_keys():
    """A legacy-format bid contributes nothing to expected_columns or
    join keys — the reducer just sees `expected_columns: []` for it."""
    svc = _service_with_bid_meta([
        {"node_id": "n-1", "bid_plan_format": "legacy",
         "bid_plan": _json.dumps([{"tool": "A", "expected_columns": ["loan_id"]}]),
         "bid_coverage": ""},
        {"node_id": "n-2", "bid_plan_format": "structured",
         "bid_plan": _json.dumps([{"tool": "B", "kind": "sql",
                                   "expected_columns": ["loan_id"]}]),
         "bid_coverage": _json.dumps({})},
    ])
    captured = _capture_executor(svc)

    await svc._step8_python_reduce(
        message="mixed",
        node_results=[
            {"node_id": "n-1", "description": "legacy", "llm_response": "ok",
             "status": "SUCCESS"},
            {"node_id": "n-2", "description": "structured", "llm_response": "ok",
             "status": "SUCCESS"},
        ],
        graph_id="g-4", primary=None, trace_id="tr-4",
    )
    desc = captured["task_description"]
    # Only one structured agent declared loan_id; legacy is ignored → not a join key.
    assert "CANDIDATE JOIN KEYS" not in desc
