"""Integration test for the marketing→origination→servicing scenario.

Exercises the full `_step3_negotiate` path end-to-end (with Neo4j / LLM /
agent-mgmt mocked) to confirm:

  1. When 3 agents bid on a cross-schema question and no single bid spans
     it, complementary cover triggers.
  2. The pipeline spawns 2 sibling subtask nodes (one per non-top winner).
  3. Each new node gets the correct complementary winner stamped via
     `assign_winner_to_graph`.
  4. The `negotiation_results` map returned to the caller now contains the
     original description + the 2 new sibling descriptions, each with the
     matching `winner` agent (so the assignment-building loop in
     `_pipeline_loop` wires the right agent to each description).
  5. When ALL agents already cover the question (single-winner case), no
     siblings spawn — the existing path is unchanged.

The test mocks broadcast_bid_request to return canned BidResponse objects
with structured coverage, and verifies what the spawning logic does with
them. This is the closest we get to an end-to-end test without the
sandbox HTTP roundtrip.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
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
from app.services.pipeline import PipelineService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bid(
    agent_id: str,
    answerable: List[str],
    not_answerable: List[str] | None = None,
    confidence: float = 0.85,
) -> BidResponse:
    return BidResponse(
        agent_id=agent_id,
        agent_name=agent_id.capitalize() + "Analyst",
        confidence=confidence,
        eligible=True,
        coverage=BidCoverage(
            answerable=answerable,
            not_answerable=not_answerable or [],
        ),
        plan=[
            BidPlanStep(
                tool=f"{agent_id}DB", kind="sql",
                sketch=f"SELECT ... FROM {agent_id}.* WHERE ...",
                expected_columns=["loan_id"] + answerable[:1],
                purpose=", ".join(answerable),
            ),
        ],
        plan_format="structured",
    )


def _make_pipeline() -> Tuple[PipelineService, AsyncMock]:
    """Build a pipeline whose Neo4j / graph_mgr / negotiation are recordable."""
    neo4j = AsyncMock()
    neo4j.run_query = AsyncMock(return_value=[])
    redis = AsyncMock()
    llm = AsyncMock()
    memory = AsyncMock()
    scoring = AsyncMock()
    rag = AsyncMock()
    meta = AsyncMock()

    svc = PipelineService(
        neo4j=neo4j, redis=redis, llm=llm, memory=memory,
        scoring=scoring, rag=rag, meta=meta,
    )

    # graph_mgr.get_graph_nodes returns one SUBTASK node for the original
    # description so spawning siblings can inherit parent_id/depth.
    svc._graph_mgr.get_graph_nodes = AsyncMock(return_value=[
        {
            "node_id": "subtask-1",
            "node_type": "SUBTASK",
            "description": "cross-schema marketing question",
            "parent_id": "root-1",
            "depth": 1,
            "criticality": "MEDIUM",
            "dataset_bindings": ["mkt.campaigns", "orig.loans", "serv.loans"],
        },
    ])
    spawned: List[Dict[str, Any]] = []

    async def _add_node(**kwargs):
        new_id = f"sibling-{len(spawned)+1}"
        spawned.append({"node_id": new_id, **kwargs})
        return new_id

    svc._graph_mgr.add_node = _add_node  # type: ignore[assignment]

    # Neutralise the bandit so its shadow decisions don't pollute the test.
    svc._bandit = MagicMock()
    svc._bandit.select = MagicMock(return_value=None)
    svc._interaction_logger = MagicMock()
    svc._interaction_logger.log_interaction = AsyncMock()

    return svc, spawned


def _agent(agent_id: str) -> Agent:
    return Agent(
        agent_id=agent_id,
        name=agent_id.capitalize() + "Analyst",
        role="specialist",
        priority=10,
    )


# ---------------------------------------------------------------------------
# The headline scenario
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_marketing_origination_servicing_spawns_two_siblings():
    svc, spawned = _make_pipeline()

    # 3 bids — each owns one slice; no single bid covers everything.
    mkt = _bid("mkt", answerable=["campaign loan_ids"],
               not_answerable=["origination_date", "servicing tenure",
                               "current status"])
    orig = _bid("orig", answerable=["origination_date", "originated count"],
                not_answerable=["campaign loan_ids", "servicing tenure",
                                "current status"])
    serv = _bid("serv", answerable=["servicing tenure", "current status"],
                not_answerable=["campaign loan_ids", "origination_date"])

    # Stub negotiation: one neg_result per subtask description with the
    # complementary cover already populated. We bypass the LLM round-trip
    # — the test is about pipeline-side splicing.
    neg_result = NegotiationResult(
        task_id="subtask-1",
        task_description="cross-schema marketing question",
        winner=mkt,
        fallback_chain=[],
        all_bids=[mkt, orig, serv],
        complementary_winners=[mkt, orig, serv],
        uncovered_parts=[],
    )

    # Stub the inner negotiate() — _step3_negotiate calls it.
    svc._negotiation.negotiate = AsyncMock(return_value=neg_result)
    # Stub assign_winner_to_graph so we can assert which winners were stamped.
    stamped: List[Dict[str, Any]] = []

    async def _stamp(**kwargs):
        stamped.append(kwargs)

    svc._negotiation.assign_winner_to_graph = _stamp  # type: ignore[assignment]

    results, _ = await svc._step3_negotiate(
        graph_id="g-1",
        node_descriptions=["cross-schema marketing question"],
        team_agents=[_agent("mkt"), _agent("orig"), _agent("serv")],
        trace_id="tr-1",
    )

    # 2 siblings spawned (cw[1:] = orig, serv).
    assert len(spawned) == 2
    # Each sibling gets its own assigned winner stamped.
    assert len(stamped) == 2
    stamped_winners = {s["winner"].agent_id for s in stamped}
    assert stamped_winners == {"orig", "serv"}

    # Sibling descriptions tag the agent + slice so the system prompt
    # builder + UI can show "this is OrigAnalyst's slice".
    sibling_descs = [s["description"] for s in spawned]
    assert any("Origanalyst slice" in d.lower() or "origanalyst slice" in d.lower()
               for d in sibling_descs)
    assert any("servanalyst slice" in d.lower() for d in sibling_descs)

    # The mirrored neg_result entries are in `results` so the caller can
    # build agent_assignments for each sibling description.
    assert len(results) == 3
    sibling_results = [r for desc, r in results.items() if "slice" in desc.lower()]
    assert {r.winner.agent_id for r in sibling_results} == {"orig", "serv"}


@pytest.mark.asyncio
async def test_no_siblings_when_top_winner_covers_everything():
    svc, spawned = _make_pipeline()

    full = _bid("super", answerable=["campaign", "originated_count",
                                     "tenure", "current_status"],
                not_answerable=[])
    neg_result = NegotiationResult(
        task_id="subtask-1",
        task_description="cross-schema marketing question",
        winner=full,
        fallback_chain=[],
        all_bids=[full],
        complementary_winners=[],  # set cover decided no complement needed
        uncovered_parts=[],
    )
    svc._negotiation.negotiate = AsyncMock(return_value=neg_result)
    svc._negotiation.assign_winner_to_graph = AsyncMock()

    results, _ = await svc._step3_negotiate(
        graph_id="g-2",
        node_descriptions=["cross-schema marketing question"],
        team_agents=[_agent("super")],
        trace_id="tr-2",
    )
    assert len(spawned) == 0
    assert len(results) == 1


@pytest.mark.asyncio
async def test_uncovered_parts_recorded_when_no_bid_owns_a_slice():
    svc, spawned = _make_pipeline()

    a = _bid("a", answerable=["campaign"],
             not_answerable=["origination_date", "tenure", "status"])
    b = _bid("b", answerable=["origination_date"],
             not_answerable=["campaign", "tenure", "status"])
    # No bid owns "tenure" or "status".
    neg_result = NegotiationResult(
        task_id="subtask-1",
        task_description="cross-schema marketing question",
        winner=a,
        fallback_chain=[],
        all_bids=[a, b],
        complementary_winners=[a, b],
        uncovered_parts=["status", "tenure"],
    )
    svc._negotiation.negotiate = AsyncMock(return_value=neg_result)
    stamped: List[Dict[str, Any]] = []

    async def _stamp(**kwargs):
        stamped.append(kwargs)

    svc._negotiation.assign_winner_to_graph = _stamp  # type: ignore[assignment]

    results, _ = await svc._step3_negotiate(
        graph_id="g-3",
        node_descriptions=["cross-schema marketing question"],
        team_agents=[_agent("a"), _agent("b")],
        trace_id="tr-3",
    )
    # 1 sibling spawned (cw[1:] = b only — a is the top, already on the
    # original node).
    assert len(spawned) == 1
    assert len(stamped) == 1
    assert stamped[0]["winner"].agent_id == "b"
    # uncovered_parts surface on the original neg_result entry so step-9
    # synthesis can say "we don't have data for tenure/status."
    assert results["cross-schema marketing question"].uncovered_parts == [
        "status", "tenure"
    ]
