"""Unit tests for capability negotiation — bid contract + grounding (Phase 22).

Covers Phase 1+2 of the bid-as-capability-contract refactor:
  - Bid coercion helpers (`_coerce_coverage`, `_coerce_plan`).
  - Bid response parser handling new nested shape, legacy shape, fenced
    JSON, and brace-balanced free-text JSON (incl. quoted braces inside SQL).
  - End-to-end `_request_agent_bid` populating coverage/plan when the LLM
    emits the new shape, and falling back to plan_format='legacy' when it
    emits the old shape or malformed output.
  - `assign_winner_to_graph` persisting `bid_plan`, `bid_coverage`,
    `bid_plan_format` onto the TaskNode.

These tests stub Neo4j/LLM/memory/agent-mgmt — we exercise the negotiation
logic in isolation. The grounding-query Cypher is exercised behaviourally
(stub returns rows; expect them in the prompt) rather than by inspecting
the literal Cypher text — easier to refactor.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.bid import (
    BidCoverage,
    BidPlanStep,
    BidRequest,
    BidResponse,
    NegotiationResult,
)
from app.services.agent_selector import Agent
from app.services.capability_negotiation import CapabilityNegotiationService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_service(
    *,
    llm_response: str = '{"confidence":0.8,"eligible":true,"reasoning":"ok"}',
    grounding_rows: List[Dict[str, Any]] | None = None,
    relationship_rows: List[Dict[str, Any]] | None = None,
    binding_filter_rows: List[Dict[str, Any]] | None = None,
) -> CapabilityNegotiationService:
    neo4j = AsyncMock()
    # Three distinct calls hit run_query in order:
    #   1. grounding lookup (assets + cols + samples)
    #   2. relationships among accessible assets
    #   3. dataset-binding filter (post-bid, in `_apply_dataset_binding_filter`)
    # The same mock serves all three with `side_effect`.
    neo4j.run_query = AsyncMock(side_effect=[
        grounding_rows or [],
        relationship_rows or [],
        binding_filter_rows or [],
    ])
    neo4j.create_execution_event = AsyncMock()

    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=llm_response)

    memory = AsyncMock()
    memory.assemble_prompt = AsyncMock(return_value={
        "system_prompt": "",
        "sources": {},
    })

    agent_mgmt = AsyncMock()
    agent_mgmt.get_agent_tools = AsyncMock(return_value=[
        {
            "id": 1,
            "tool_id": "tool-uuid-1",
            "name": "Servicing DB",
            "tool_type": "DATABASE",
            "description": "MySQL pmos_servicing",
        },
    ])

    return CapabilityNegotiationService(
        neo4j=neo4j,
        llm=llm,
        memory=memory,
        agent_mgmt=agent_mgmt,
    )


def _agent(agent_id: str = "a-1", name: str = "ServicingAnalyst") -> Agent:
    return Agent(
        agent_id=agent_id,
        name=name,
        foundation_model="gpt-4o",
        role="specialist",
        priority=10,
    )


# ---------------------------------------------------------------------------
# Coverage coercion
# ---------------------------------------------------------------------------

def test_coerce_coverage_well_formed():
    cov = CapabilityNegotiationService._coerce_coverage({
        "answerable": ["count", "dates"],
        "not_answerable": ["servicing tenure"],
        "reason_missing": "no servicing tool bound",
    })
    assert cov is not None
    assert cov.answerable == ["count", "dates"]
    assert cov.not_answerable == ["servicing tenure"]
    assert cov.reason_missing == "no servicing tool bound"


def test_coerce_coverage_drops_empty_strings():
    cov = CapabilityNegotiationService._coerce_coverage({
        "answerable": ["count", "  ", ""],
        "not_answerable": [None, "tenure"],
    })
    assert cov is not None
    assert cov.answerable == ["count"]
    assert cov.not_answerable == ["tenure"]


def test_coerce_coverage_returns_none_for_non_dict():
    assert CapabilityNegotiationService._coerce_coverage(None) is None
    assert CapabilityNegotiationService._coerce_coverage("nope") is None
    assert CapabilityNegotiationService._coerce_coverage([]) is None


def test_coerce_coverage_returns_none_when_both_lists_empty():
    assert CapabilityNegotiationService._coerce_coverage({}) is None
    assert CapabilityNegotiationService._coerce_coverage(
        {"answerable": [], "not_answerable": []}
    ) is None


def test_coerce_coverage_caps_long_lists():
    big = {"answerable": [f"part-{i}" for i in range(100)],
           "not_answerable": [f"miss-{i}" for i in range(100)]}
    cov = CapabilityNegotiationService._coerce_coverage(big)
    assert cov is not None
    assert len(cov.answerable) == 24
    assert len(cov.not_answerable) == 24


def test_bid_coverage_ratio():
    assert BidCoverage().ratio() == 0.0
    assert BidCoverage(answerable=["a", "b"]).ratio() == 1.0
    assert BidCoverage(answerable=["a"], not_answerable=["x", "y", "z"]).ratio() == 0.25


# ---------------------------------------------------------------------------
# Plan coercion
# ---------------------------------------------------------------------------

def test_coerce_plan_well_formed():
    steps = CapabilityNegotiationService._coerce_plan([
        {
            "tool": "Servicing DB",
            "kind": "sql",
            "sketch": "SELECT count(*) FROM servicing.loans",
            "expected_columns": ["count"],
            "purpose": "count loans",
        },
    ])
    assert len(steps) == 1
    assert steps[0].tool == "Servicing DB"
    assert steps[0].kind == "sql"
    assert steps[0].expected_columns == ["count"]


def test_coerce_plan_returns_empty_for_non_list():
    assert CapabilityNegotiationService._coerce_plan(None) == []
    assert CapabilityNegotiationService._coerce_plan({"k": "v"}) == []
    assert CapabilityNegotiationService._coerce_plan("nope") == []


def test_coerce_plan_caps_at_12_steps():
    raw = [{"tool": f"t-{i}", "kind": "sql"} for i in range(20)]
    assert len(CapabilityNegotiationService._coerce_plan(raw)) == 12


def test_coerce_plan_skips_non_dict_items():
    raw = [
        {"tool": "ok", "kind": "sql"},
        "garbage",
        None,
        {"tool": "ok2", "kind": "cypher"},
    ]
    steps = CapabilityNegotiationService._coerce_plan(raw)
    assert [s.tool for s in steps] == ["ok", "ok2"]


def test_coerce_plan_lowercases_kind_and_truncates_long_sketches():
    raw = [{"tool": "t", "kind": "SQL", "sketch": "x" * 5000}]
    steps = CapabilityNegotiationService._coerce_plan(raw)
    assert steps[0].kind == "sql"
    assert len(steps[0].sketch) == 2000


# ---------------------------------------------------------------------------
# Bid response parser
# ---------------------------------------------------------------------------

def test_parser_direct_json():
    raw = '{"confidence": 0.9, "eligible": true}'
    out = CapabilityNegotiationService._parse_bid_response(raw)
    assert out["confidence"] == 0.9


def test_parser_fenced_markdown_with_nested_objects():
    raw = (
        "Here's my bid:\n"
        "```json\n"
        '{"confidence": 0.85, "coverage": {"answerable": ["count"]}, '
        '"plan": [{"tool": "DB", "kind": "sql"}]}\n'
        "```"
    )
    out = CapabilityNegotiationService._parse_bid_response(raw)
    assert out["confidence"] == 0.85
    assert out["coverage"]["answerable"] == ["count"]
    assert out["plan"][0]["tool"] == "DB"


def test_parser_brace_balanced_with_nested_arrays():
    """No fence — agent emitted JSON with prose around it. The brace-balance
    fallback must pull the whole nested object, not just the inner {}."""
    raw = (
        "Sure, here is the bid object\n"
        '{"confidence": 0.6, "plan": [{"tool": "X", "kind": "sql"}], '
        '"coverage": {"answerable": ["a"], "not_answerable": []}}'
        "\nLet me know if you need more."
    )
    out = CapabilityNegotiationService._parse_bid_response(raw)
    assert out["confidence"] == 0.6
    assert isinstance(out["plan"], list) and out["plan"][0]["tool"] == "X"


def test_parser_handles_brace_inside_sql_sketch():
    """A `{}` inside a quoted SQL string must not fool the brace counter."""
    raw = (
        '{"confidence": 0.7, "plan": [{"sketch": "SELECT JSON_OBJECT(\'k\','
        '\'v\') FROM t /* {leftover} */", "kind": "sql"}], "eligible": true}'
    )
    out = CapabilityNegotiationService._parse_bid_response(raw)
    assert out["confidence"] == 0.7
    assert out["plan"][0]["kind"] == "sql"


def test_parser_garbage_returns_defaults():
    out = CapabilityNegotiationService._parse_bid_response("totally not json")
    assert out["confidence"] == 0.5
    assert out["eligible"] is True


# ---------------------------------------------------------------------------
# End-to-end _request_agent_bid — populates coverage/plan
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_request_agent_bid_populates_structured_coverage_and_plan():
    structured = json.dumps({
        "confidence": 0.92,
        "eligible": True,
        "reasoning": "I can fully answer with my servicing tool.",
        "coverage": {
            "answerable": ["loan count", "tenure"],
            "not_answerable": [],
            "reason_missing": "",
        },
        "plan": [
            {
                "tool": "Servicing DB",
                "kind": "sql",
                "sketch": "SELECT count(*), MIN(serviced_since) FROM servicing.loans",
                "expected_columns": ["count", "first_date"],
                "purpose": "count loans + tenure",
            },
        ],
    })

    svc = _make_service(llm_response=structured)
    bid = await svc._request_agent_bid(
        agent=_agent(),
        bid_request=BidRequest(
            task_id="t-1", task_description="how many loans?",
        ),
        trace_id="tr-1",
    )

    assert bid.confidence > 0.9
    assert bid.plan_format == "structured"
    assert bid.coverage is not None
    assert bid.coverage.answerable == ["loan count", "tenure"]
    assert len(bid.plan) == 1
    assert bid.plan[0].tool == "Servicing DB"
    assert bid.plan[0].expected_columns == ["count", "first_date"]


@pytest.mark.asyncio
async def test_request_agent_bid_falls_back_to_legacy_shape():
    """Legacy {confidence, reasoning, eligible} → coverage None, plan empty,
    plan_format='legacy'."""
    legacy = '{"confidence": 0.7, "reasoning": "fits", "eligible": true}'
    svc = _make_service(llm_response=legacy)
    bid = await svc._request_agent_bid(
        agent=_agent(),
        bid_request=BidRequest(task_id="t-2", task_description="hi"),
        trace_id="tr-2",
    )
    assert bid.coverage is None
    assert bid.plan == []
    assert bid.plan_format == "legacy"


@pytest.mark.asyncio
async def test_request_agent_bid_marks_legacy_when_garbage_response():
    svc = _make_service(llm_response="i cannot generate JSON sorry")
    bid = await svc._request_agent_bid(
        agent=_agent(),
        bid_request=BidRequest(task_id="t-3", task_description="hi"),
        trace_id="tr-3",
    )
    # Defaults from parser: confidence=0.5 (then +0.05 boost = 0.55), eligible=True
    assert bid.plan_format == "legacy"
    assert bid.coverage is None


@pytest.mark.asyncio
async def test_request_agent_bid_includes_grounded_schema_in_prompt():
    """When dataset_bindings is set and Neo4j returns assets, the prompt
    rendered to the LLM must contain the asset name and at least one
    column with sample values + flags."""
    grounding = [{
        "asset_fq_name": "pmos_servicing.loans",
        "asset_type": "TABLE",
        "asset_comment": "loan servicing rows",
        "row_count": 12345,
        "source_type": "MYSQL",
        "columns": [
            {
                "column": "loan_id",
                "data_type": "BIGINT",
                "sample_values": ["1001", "1002", "1003"],
                "is_pk": True,
                "is_fk": False,
                "fk_references": None,
                "business_attribute": "loan_id",
                "business_entity": "Loan",
                "business_domain": "Servicing",
                "map_confidence": 0.9,
            },
        ],
        "bound_tool_id": "tool-uuid-1",
    }]
    relationships = [{
        "from_asset": "pmos_servicing.loans",
        "to_asset": "pmos_origination.loans",
        "via": "loan_id -> loan_id",
    }]

    svc = _make_service(
        llm_response='{"confidence":0.8,"eligible":true,"reasoning":"ok",'
                     '"coverage":{"answerable":["count"]},"plan":[]}',
        grounding_rows=grounding,
        relationship_rows=relationships,
    )

    captured: Dict[str, Any] = {}
    orig_complete = svc._llm.complete

    async def _capture(messages, **kw):
        captured["prompt"] = messages[0]["content"]
        return await orig_complete(messages=messages, **kw)

    svc._llm.complete = _capture  # type: ignore[assignment]

    await svc._request_agent_bid(
        agent=_agent(),
        bid_request=BidRequest(
            task_id="t-4",
            task_description="how many loans?",
            dataset_bindings=["pmos_servicing.loans"],
        ),
        trace_id="tr-4",
    )

    prompt = captured["prompt"]
    assert "pmos_servicing.loans" in prompt
    assert "loan_id" in prompt
    assert "PK" in prompt  # PK flag should render
    assert "12,345 rows" in prompt or "12345" in prompt
    # Relationship surfaced.
    assert "pmos_origination.loans" in prompt
    assert "JOIN PATHS" in prompt


# ---------------------------------------------------------------------------
# assign_winner_to_graph persists plan + coverage
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_assign_winner_persists_plan_and_coverage_on_tasknode():
    svc = _make_service()
    captured: List[Dict[str, Any]] = []

    async def _capture_run_query(cypher, params=None, **kw):
        captured.append({"cypher": cypher, "params": params or {}})
        return []

    svc._neo4j.run_query = _capture_run_query  # type: ignore[assignment]

    winner = BidResponse(
        agent_id="a-1",
        agent_name="ServicingAnalyst",
        confidence=0.9,
        coverage=BidCoverage(answerable=["count", "tenure"], not_answerable=[]),
        plan=[BidPlanStep(tool="Servicing DB", kind="sql",
                          sketch="SELECT count(*) FROM loans",
                          expected_columns=["count"])],
        plan_format="structured",
    )

    await svc.assign_winner_to_graph(
        task_id="node-1",
        graph_id="g-1",
        winner=winner,
        fallback_chain=[],
        trace_id="tr-1",
    )

    # First run_query is the TaskNode SET cypher.
    set_call = captured[0]
    assert "bid_plan" in set_call["cypher"]
    assert "bid_coverage" in set_call["cypher"]
    assert "bid_plan_format" in set_call["cypher"]
    plan_json = json.loads(set_call["params"]["bid_plan"])
    assert plan_json[0]["tool"] == "Servicing DB"
    cov_json = json.loads(set_call["params"]["bid_coverage"])
    assert cov_json["answerable"] == ["count", "tenure"]
    assert set_call["params"]["plan_format"] == "structured"


@pytest.mark.asyncio
async def test_assign_winner_persists_empty_plan_when_legacy():
    svc = _make_service()
    captured: List[Dict[str, Any]] = []

    async def _capture_run_query(cypher, params=None, **kw):
        captured.append({"cypher": cypher, "params": params or {}})
        return []

    svc._neo4j.run_query = _capture_run_query  # type: ignore[assignment]

    winner = BidResponse(
        agent_id="a-1", agent_name="LegacyAgent",
        confidence=0.6, plan_format="legacy",
    )
    await svc.assign_winner_to_graph(
        task_id="node-2", graph_id="g-2", winner=winner,
        fallback_chain=[], trace_id="tr-2",
    )
    params = captured[0]["params"]
    assert params["bid_plan"] == "[]"
    assert params["bid_coverage"] == ""
    assert params["plan_format"] == "legacy"
