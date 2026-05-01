"""Unit tests for the bid contract injection into the execution prompt
(Phase 5).

`PipelineService._fetch_bid_contract(node_id)` reads bid_plan + bid_coverage
off the TaskNode and renders a commitment block the executor prepends to
the agent's system prompt. The block:
  - lists the agent's `answerable` parts (and what other agents own),
  - enumerates plan steps (tool, kind, purpose, sketch, expected_columns),
  - demands row-level JSON output when any plan step is sql/cypher.

Returns "" — degrades to today's behaviour — when:
  - node_id is empty (speculative or legacy paths),
  - the node has no plan stamped (bidding skipped via schema-meta override),
  - plan_format == 'legacy' (the bid LLM emitted the old shape),
  - the Neo4j read fails.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from app.services.pipeline import PipelineService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pipeline_with_neo4j_rows(rows):
    neo4j = AsyncMock()
    neo4j.run_query = AsyncMock(return_value=rows)
    redis = AsyncMock()
    llm = AsyncMock()
    memory = AsyncMock()
    scoring = AsyncMock()
    rag = AsyncMock()
    meta = AsyncMock()

    return PipelineService(
        neo4j=neo4j, redis=redis, llm=llm, memory=memory,
        scoring=scoring, rag=rag, meta=meta,
    )


# ---------------------------------------------------------------------------
# Empty / degenerate paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_bid_contract_returns_empty_for_blank_node_id():
    svc = _make_pipeline_with_neo4j_rows([])
    out = await svc._fetch_bid_contract(node_id="", trace_id="tr")
    assert out == ""
    # No Neo4j call when node_id is blank — saves a round trip.
    svc._neo4j.run_query.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_bid_contract_returns_empty_when_no_rows():
    svc = _make_pipeline_with_neo4j_rows([])
    out = await svc._fetch_bid_contract(node_id="n-1", trace_id="tr")
    assert out == ""


@pytest.mark.asyncio
async def test_fetch_bid_contract_returns_empty_when_legacy_format():
    svc = _make_pipeline_with_neo4j_rows([{
        "bid_plan": '[{"tool":"X","kind":"sql"}]',
        "bid_coverage": '{"answerable":["count"]}',
        "bid_plan_format": "legacy",
    }])
    out = await svc._fetch_bid_contract(node_id="n-1", trace_id="tr")
    assert out == ""


@pytest.mark.asyncio
async def test_fetch_bid_contract_returns_empty_when_both_fields_blank():
    svc = _make_pipeline_with_neo4j_rows([{
        "bid_plan": "",
        "bid_coverage": "",
        "bid_plan_format": "structured",
    }])
    out = await svc._fetch_bid_contract(node_id="n-1", trace_id="tr")
    assert out == ""


@pytest.mark.asyncio
async def test_fetch_bid_contract_degrades_on_neo4j_error():
    svc = _make_pipeline_with_neo4j_rows([])

    async def _raise(*a, **kw):
        raise RuntimeError("neo4j down")

    svc._neo4j.run_query = _raise  # type: ignore[assignment]
    out = await svc._fetch_bid_contract(node_id="n-1", trace_id="tr")
    assert out == ""


# ---------------------------------------------------------------------------
# Happy-path rendering
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_bid_contract_renders_full_block_for_database_agent():
    plan = [
        {
            "tool": "Servicing DB",
            "kind": "sql",
            "sketch": "SELECT loan_id, serviced_since FROM servicing.loans",
            "expected_columns": ["loan_id", "serviced_since"],
            "purpose": "tenure",
        },
    ]
    coverage = {
        "answerable": ["servicing tenure", "current status"],
        "not_answerable": ["origination_date", "campaign loan_ids"],
        "reason_missing": "no origination/marketing tools bound",
    }
    svc = _make_pipeline_with_neo4j_rows([{
        "bid_plan": json.dumps(plan),
        "bid_coverage": json.dumps(coverage),
        "bid_plan_format": "structured",
    }])

    out = await svc._fetch_bid_contract(node_id="n-1", trace_id="tr")

    assert "BID CONTRACT" in out
    # Agent's slice is surfaced.
    assert "servicing tenure" in out
    assert "current status" in out
    # The non-slice parts are surfaced too so the agent doesn't claim them.
    assert "origination_date" in out
    # Plan content rendered.
    assert "Servicing DB" in out
    assert "kind=sql" in out
    assert "purpose: tenure" in out
    assert "loan_id" in out
    # Row-level JSON demand when sql/cypher in plan.
    assert "JSON array of row objects" in out


@pytest.mark.asyncio
async def test_fetch_bid_contract_omits_json_demand_for_python_only_plan():
    plan = [{"tool": "Python", "kind": "python", "sketch": "df.groupby(...)",
             "expected_columns": []}]
    coverage = {"answerable": ["aggregate counts"], "not_answerable": []}
    svc = _make_pipeline_with_neo4j_rows([{
        "bid_plan": json.dumps(plan),
        "bid_coverage": json.dumps(coverage),
        "bid_plan_format": "structured",
    }])
    out = await svc._fetch_bid_contract(node_id="n-1", trace_id="tr")
    assert "BID CONTRACT" in out
    assert "Python" in out
    # No JSON-row demand for python-only plans — the python tool returns
    # whatever it returns and the reducer trusts it.
    assert "JSON array of row objects" not in out


@pytest.mark.asyncio
async def test_fetch_bid_contract_handles_malformed_json_gracefully():
    """The plan field on the node was somehow corrupted — render a safe
    minimal contract from coverage alone rather than 500ing the request."""
    svc = _make_pipeline_with_neo4j_rows([{
        "bid_plan": "{this is not json",
        "bid_coverage": '{"answerable":["count"],"not_answerable":[]}',
        "bid_plan_format": "structured",
    }])
    out = await svc._fetch_bid_contract(node_id="n-1", trace_id="tr")
    assert "BID CONTRACT" in out
    assert "count" in out
    # No plan rendered, no row-JSON demand.
    assert "Plan steps" not in out
    assert "JSON array of row objects" not in out


@pytest.mark.asyncio
async def test_fetch_bid_contract_skips_non_dict_plan_items():
    plan = [
        {"tool": "DB", "kind": "sql", "expected_columns": ["x"]},
        "garbage",
        None,
        {"tool": "Graph", "kind": "cypher", "expected_columns": ["y"]},
    ]
    svc = _make_pipeline_with_neo4j_rows([{
        "bid_plan": json.dumps(plan),
        "bid_coverage": '{"answerable":["a"]}',
        "bid_plan_format": "structured",
    }])
    out = await svc._fetch_bid_contract(node_id="n-1", trace_id="tr")
    assert "DB" in out
    assert "Graph" in out
    # Both row-shaped tools present → row-JSON demand.
    assert "JSON array of row objects" in out
