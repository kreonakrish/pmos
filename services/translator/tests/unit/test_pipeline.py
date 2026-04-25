"""Unit tests for TranslatorPipeline (Phase C2).

Mocks every external dependency (Neo4j, LLM, Qdrant, embedder) so the
pipeline's branching logic can be exercised without a live stack.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Make ``shared`` and ``app`` importable just like main.py does at runtime.
_SERVICE_ROOT = Path(__file__).resolve().parents[2]  # services/translator/
_REPO_ROOT = _SERVICE_ROOT.parents[1]  # repo root
for p in (_REPO_ROOT, _SERVICE_ROOT):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

from app.services.pipeline import (  # noqa: E402
    MAX_DIALOG_TURNS,
    TranslatorPipeline,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_pipeline(
    neo4j_rows_by_query=None,
    llm_responses=None,
    qdrant_hits=None,
    embedder_available=True,
):
    """Build a pipeline with mocked deps. ``neo4j_rows_by_query`` is a list of
    rows returned by successive ``run_query`` calls (queue-style).
    """
    neo4j = MagicMock()
    rows_queue = list(neo4j_rows_by_query or [])

    async def _run_query(cypher, parameters=None, trace_id=""):
        if rows_queue:
            return rows_queue.pop(0)
        return []

    neo4j.run_query = AsyncMock(side_effect=_run_query)

    llm = MagicMock()
    llm_queue = list(llm_responses or [])

    async def _complete(messages=None, trace_id="", **kwargs):
        if llm_queue:
            return llm_queue.pop(0)
        return ""

    llm.complete = AsyncMock(side_effect=_complete)

    qdrant = MagicMock()
    qdrant.search = AsyncMock(return_value=qdrant_hits or [])
    qdrant.upsert_example = AsyncMock(return_value=None)

    embedder = MagicMock()
    embedder.available = MagicMock(return_value=embedder_available)
    embedder.embed = AsyncMock(return_value=[0.0] * 384)

    return TranslatorPipeline(
        neo4j=neo4j,
        qdrant=qdrant,
        llm=llm,
        embedder=embedder,
    )


# ---------------------------------------------------------------------------
# Test 1: fallback when ontology returns nothing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_translate_returns_fallback_when_no_ontology_matches():
    """With an empty ontology response the pipeline must short-circuit to
    the fallback result with no canonical entities."""
    pipeline = _make_pipeline(
        neo4j_rows_by_query=[
            # NER+intent doesn't hit Neo4j; first Neo4j call is schema RAG.
            [],
        ],
        llm_responses=[
            # Step 1 NER+intent
            json.dumps({"intent": "metric_lookup", "spans": ["nonexistent_span"]}),
        ],
        qdrant_hits=[],
        embedder_available=True,
    )

    result = await pipeline.translate(
        question="What was the revenue of UnknownEntity?",
        team_id="t1",
        conversation_id="c1",
        trace_id="trace-1",
    )

    assert result["fallback_used"] is True
    assert result["canonical_entities"] == []
    assert result["dataset_bindings"] == []
    assert result["domain_subtasks"] == []
    assert result["intent"] == "metric_lookup"
    assert result["trace_id"] == "trace-1"


# ---------------------------------------------------------------------------
# Test 2: full happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_translate_full_path():
    """Mock the ontology to return a Payment entity + revenue attribute. Mock
    the LLM to pick the entity in entity-resolution and emit a decomposition.
    """
    schema_rag_rows = [
        {
            "span": "payment",
            "entity_hits": [
                {"name": "Payment", "domain": "Finance", "type": "entity"}
            ],
            "attribute_hits": [
                {
                    "name": "revenue",
                    "fq_name": "Finance.Payment.revenue",
                    "entity": "Payment",
                    "domain": "Finance",
                    "type": "attribute",
                }
            ],
        }
    ]
    binding_rows = [
        {
            "attribute_fq_name": "Finance.Payment.revenue",
            "asset_fq_name": "warehouse.finance.payments",
            "asset_type": "table",
            "column_name": "revenue_usd",
            "source_uri": "postgres://prod/finance",
            "map_version": 1,
            "map_confidence": 0.92,
        }
    ]

    pipeline = _make_pipeline(
        neo4j_rows_by_query=[schema_rag_rows, binding_rows],
        llm_responses=[
            # Step 1: NER+intent
            json.dumps({"intent": "metric_lookup", "spans": ["payment", "revenue"]}),
            # Step 3: Entity resolution — pick Payment entity + revenue attribute
            json.dumps(
                {
                    "canonical_entities": [
                        {"name": "Payment", "domain": "Finance"},
                        {
                            "name": "revenue",
                            "fq_name": "Finance.Payment.revenue",
                            "domain": "Finance",
                        },
                    ],
                    "relationships": [],
                }
            ),
            # Step 6: Decomposition
            json.dumps(
                {
                    "domain_subtasks": [
                        "Aggregate revenue_usd from warehouse.finance.payments for the requested period.",
                        "Compare revenue across periods if a comparison was implied.",
                    ]
                }
            ),
        ],
        qdrant_hits=[],
        embedder_available=True,
    )

    result = await pipeline.translate(
        question="What's the revenue for our payments product?",
        team_id="t1",
        conversation_id="c1",
        trace_id="trace-2",
    )

    assert result["fallback_used"] is False
    assert len(result["canonical_entities"]) > 0
    assert len(result["domain_subtasks"]) > 0
    assert result["intent"] == "metric_lookup"
    assert result["domain"] == "Finance"
    # Bindings should have rolled up by asset_fq_name
    assert len(result["dataset_bindings"]) == 1
    binding = result["dataset_bindings"][0]
    assert binding["asset_fq_name"] == "warehouse.finance.payments"
    assert "revenue_usd" in binding["columns"]
    # Versions captured
    assert "v1" in result["ontology_versions"]
    # Subgraph populated
    assert result["used_ontology_subgraph"]["nodes"], "expected non-empty nodes"


# ---------------------------------------------------------------------------
# Test 3: promote_example skips when embedder unavailable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_promote_example_skips_when_embedder_unavailable():
    pipeline = _make_pipeline(embedder_available=False)

    result = await pipeline.promote_example(
        question="What is revenue?",
        canonical_entities=[],
        dataset_bindings=[],
        decomposition=[],
        intent="metric_lookup",
        domain=None,
        score=1.0,
        promoted_by="user-1",
        trace_id="trace-3",
    )

    assert result["status"] == "skipped_no_embedder"
    assert result["embedded"] is False
    assert result["point_id"] is None
    assert result["trace_id"] == "trace-3"
    # No upsert should have been issued.
    pipeline.qdrant.upsert_example.assert_not_called()


# ---------------------------------------------------------------------------
# Phase F7: Multi-turn clarification dialog
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_translate_with_prior_turns_uses_clarification(monkeypatch):
    """Round 1: ambiguous question (no entity hits) → clarification_needed=True.
    Round 2: passing prior_turns plus the user's reply to the clarifier yields
    concrete bindings (clarification_needed=False)."""

    # Stub raise_or_dedupe so we don't need a live MySQL.
    import app.services.pipeline as pipeline_mod
    monkeypatch.setattr(
        pipeline_mod, "raise_or_dedupe", lambda **kwargs: "test-issue-id"
    )

    # Round 1 — schema RAG returns nothing useful.
    pipeline_round1 = _make_pipeline(
        neo4j_rows_by_query=[
            # Schema RAG: no hits.
            [],
        ],
        llm_responses=[
            # NER+intent
            json.dumps({"intent": "metric_lookup", "spans": ["payments"]}),
        ],
        qdrant_hits=[],
        embedder_available=True,
    )
    r1 = await pipeline_round1.translate(
        question="Show me payments.",
        team_id="t1",
        conversation_id="c-multi",
        trace_id="trace-r1",
    )
    assert r1["clarification_needed"] is True
    assert r1["clarification_question"], "round 1 must ask for clarification"
    assert r1["dataset_bindings"] == []

    # Round 2 — user has clarified "Loan Servicing". Schema RAG NOW
    # returns the matching attribute, bindings come back, clarification
    # is satisfied.
    schema_rag_rows = [
        {
            "span": "loan",
            "entity_hits": [
                {"name": "Loan", "domain": "Servicing", "type": "entity"}
            ],
            "attribute_hits": [
                {
                    "name": "payment_amount",
                    "fq_name": "Servicing.Loan.payment_amount",
                    "entity": "Loan",
                    "domain": "Servicing",
                    "type": "attribute",
                }
            ],
        }
    ]
    binding_rows = [
        {
            "attribute_fq_name": "Servicing.Loan.payment_amount",
            "asset_fq_name": "warehouse.servicing.loans",
            "asset_type": "table",
            "column_name": "pmt_amt",
            "source_uri": "postgres://prod/servicing",
            "map_version": 1,
            "map_confidence": 0.9,
        }
    ]
    pipeline_round2 = _make_pipeline(
        neo4j_rows_by_query=[schema_rag_rows, binding_rows],
        llm_responses=[
            # NER+intent
            json.dumps(
                {"intent": "metric_lookup", "spans": ["loan", "payments"]}
            ),
            # Entity resolution — pick the attribute
            json.dumps(
                {
                    "canonical_entities": [
                        {
                            "name": "payment_amount",
                            "fq_name": "Servicing.Loan.payment_amount",
                            "domain": "Servicing",
                        }
                    ],
                    "relationships": [],
                }
            ),
            # Decomposition
            json.dumps(
                {
                    "domain_subtasks": [
                        "Aggregate pmt_amt from warehouse.servicing.loans"
                    ]
                }
            ),
        ],
        qdrant_hits=[],
        embedder_available=True,
    )
    prior_turns = [
        {"role": "user", "content": "Show me payments."},
        {
            "role": "translator",
            "content": r1["clarification_question"],
        },
    ]
    r2 = await pipeline_round2.translate(
        question="Loan Servicing.",
        team_id="t1",
        conversation_id="c-multi",
        trace_id="trace-r2",
        prior_turns=prior_turns,
    )
    assert r2["clarification_needed"] is False
    assert r2["dataset_bindings"], "round 2 must have concrete bindings"
    assert r2["dataset_bindings"][0]["asset_fq_name"] == (
        "warehouse.servicing.loans"
    )

    # Verify the LLM saw the dialog history. The first complete() call
    # for round 2 was NER+intent and its messages list must contain the
    # clarification question text.
    seen_messages = pipeline_round2.llm.complete.call_args_list[0].kwargs[
        "messages"
    ]
    flat = json.dumps(seen_messages)
    assert "Show me payments." in flat
    assert r1["clarification_question"] in flat


@pytest.mark.asyncio
async def test_translate_caps_at_max_dialog_turns(monkeypatch):
    """When prior_turns has reached MAX_DIALOG_TURNS round-trips the
    translator must NOT keep asking — clarification_needed=False, an
    auditor issue titled 'Multi-turn dialog exhausted' is raised."""

    import app.services.pipeline as pipeline_mod

    issues_raised: list = []

    def _capture_issue(**kwargs):
        issues_raised.append(kwargs)
        return f"issue-{len(issues_raised)}"

    monkeypatch.setattr(pipeline_mod, "raise_or_dedupe", _capture_issue)

    # Schema RAG empty → still ambiguous, would normally clarify.
    pipeline = _make_pipeline(
        neo4j_rows_by_query=[
            [],
        ],
        llm_responses=[
            json.dumps({"intent": "metric_lookup", "spans": ["thing"]}),
        ],
        qdrant_hits=[],
        embedder_available=True,
    )

    # Build prior_turns saturated to the cap. MAX_DIALOG_TURNS round-trips
    # = MAX_DIALOG_TURNS * 2 list entries (user, translator, user, ...).
    prior_turns = []
    for i in range(MAX_DIALOG_TURNS):
        prior_turns.append({"role": "user", "content": f"user reply {i}"})
        prior_turns.append({"role": "translator", "content": f"clarify? {i}"})

    result = await pipeline.translate(
        question="still ambiguous",
        team_id="t1",
        conversation_id="c-cap",
        trace_id="trace-cap",
        prior_turns=prior_turns,
    )

    assert result["clarification_needed"] is False, (
        "must not loop forever — dialog exhausted should return best-guess"
    )
    # Auditor issue should have been raised with the exhaustion title.
    titles = [i.get("title", "") for i in issues_raised]
    assert any(
        "Multi-turn dialog exhausted" in t for t in titles
    ), f"expected exhaustion issue, saw: {titles}"
    assert result["auditor_issue_kind"] == "NO_RESOLUTION"
