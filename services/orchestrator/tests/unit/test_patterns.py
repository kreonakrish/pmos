"""Routing tests for the eight migrated patterns.

Each test asserts what the dispatcher would pick for a representative
question. The fixtures simulate the translator output that would
appear after step 2 (canonical_entities, dataset_bindings,
matched_reports, intent, schema_meta_column, clarification_*).

These tests pin behaviour for the cutover (Phase 4): if a question
that should route to ColumnValuePattern starts winning under a
different pattern, the test fails.
"""

from __future__ import annotations

import pytest

from app.services.patterns import (
    BusinessPattern,
    ClarifyPattern,
    ColumnValuePattern,
    DispatchContext,
    EntityCountPattern,
    FreeFormPattern,
    MetadataPattern,
    PatternDispatcher,
    RAGPattern,
    ReportPattern,
    TeamContext,
    TeamSelfPattern,
    build_default_registry,
)
from app.services.patterns.base import (
    extract_column_name,
    parse_sample_count,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _team(*tool_types_per_agent) -> TeamContext:
    """Build a TeamContext with N agents; each gets the listed tools."""
    agents = []
    for i, tool_types in enumerate(tool_types_per_agent):
        agents.append({
            "agent_id": f"agent-{i}",
            "agent_name": f"Agent{i}",
            "role": "specialist",
            "tools": [{"tool_type": tt} for tt in tool_types],
        })
    return TeamContext(team_id="t-1", name="Test", agents=agents)


def _ctx(question: str, *, translator=None, team=None,
         prior_turns=None) -> DispatchContext:
    return DispatchContext(
        question=question,
        team_id="t-1",
        conversation_id="c-1",
        trace_id="tr-1",
        session_id="s-1",
        graph_id="g-1",
        prior_turns=list(prior_turns or []),
        translator=dict(translator or {}),
        team=team or _team(),
    )


# ---------------------------------------------------------------------------
# base.py helpers
# ---------------------------------------------------------------------------

class TestExtractColumnName:
    def test_quoted(self):
        assert extract_column_name("show me 'loan_id' values") == "loan_id"

    def test_column_named(self):
        assert extract_column_name("the column named borrower_id") == "borrower_id"

    def test_snake_then_field(self):
        assert extract_column_name("how many tables have customer_id columns") == "customer_id"

    def test_value_of_snake(self):
        assert extract_column_name("values of fico_score across tables") == "fico_score"

    def test_skips_stop_tokens(self):
        # "the" is a stop token; should not be returned.
        assert extract_column_name("show me the values") is None

    def test_empty(self):
        assert extract_column_name("") is None
        assert extract_column_name(None) is None


class TestParseSampleCount:
    def test_sample_of_n(self):
        assert parse_sample_count("give me sample of 10 values") == 10

    def test_n_rows(self):
        assert parse_sample_count("show 25 rows from each table") == 25

    def test_top_n(self):
        assert parse_sample_count("show top 50 loan_id values") == 50

    def test_default_when_no_number(self):
        assert parse_sample_count("show me sample values") == 5

    def test_clamps_outsized(self):
        assert parse_sample_count("give me 5000 rows") == 1000


# ---------------------------------------------------------------------------
# Individual pattern detect() behaviour
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_team_self_pattern_fires_on_self_reference():
    ctx = _ctx("hi how many agents do you have in your team", team=_team(["DATABASE"]))
    p = TeamSelfPattern()
    m = await p.detect(ctx)
    assert m.accepted
    assert any("regex" in e for e in m.evidence)


@pytest.mark.asyncio
async def test_team_self_pattern_skips_data_questions():
    ctx = _ctx("how many loans are in pmos_servicing", team=_team(["DATABASE"]))
    p = TeamSelfPattern()
    m = await p.detect(ctx)
    assert not m.accepted


@pytest.mark.asyncio
async def test_report_pattern_auto_fire_band():
    ctx = _ctx(
        "Show me the loan default servicing report for last year",
        translator={"matched_reports": [
            {"report_id": "R1", "name": "Loan Default Report", "score": 14.2},
            {"report_id": "R2", "name": "Loan Pipeline", "score": 11.0},
        ]},
    )
    p = ReportPattern()
    m = await p.detect(ctx)
    assert m.accepted
    assert m.payload["kind"] == "auto_fire"
    assert m.payload["score"] == pytest.approx(14.2)


@pytest.mark.asyncio
async def test_report_pattern_confirm_band():
    ctx = _ctx(
        "Default report",
        translator={"matched_reports": [
            {"report_id": "R1", "name": "Loan Default Report", "score": 8.0},
        ]},
    )
    p = ReportPattern()
    m = await p.detect(ctx)
    assert m.accepted
    assert m.payload["kind"] == "confirm"


@pytest.mark.asyncio
async def test_report_pattern_no_match_below_threshold():
    ctx = _ctx(
        "show me the data",
        translator={"matched_reports": [
            {"report_id": "R1", "name": "Random", "score": 2.5},
        ]},
    )
    p = ReportPattern()
    m = await p.detect(ctx)
    assert not m.accepted


@pytest.mark.asyncio
async def test_report_pattern_when_no_reports():
    ctx = _ctx("how many loans?", translator={"matched_reports": []})
    m = await ReportPattern().detect(ctx)
    assert m.score == 0.0
    assert not m.accepted


@pytest.mark.asyncio
async def test_clarify_pattern_passes_translator_signal():
    ctx = _ctx(
        "loan_id",
        translator={
            "clarification_needed": True,
            "clarification_question": "Did you mean Servicing.Loan or Origination.Loan?",
            "auditor_issue_id": "iss-1",
            "auditor_issue_kind": "SYNONYM_AMBIGUITY",
        },
    )
    m = await ClarifyPattern().detect(ctx)
    assert m.accepted
    assert m.payload["question"].startswith("Did you mean")
    assert m.payload["issue_id"] == "iss-1"


@pytest.mark.asyncio
async def test_clarify_pattern_silent_when_translator_quiet():
    ctx = _ctx("how many loans?", translator={"clarification_needed": False})
    m = await ClarifyPattern().detect(ctx)
    assert not m.accepted


@pytest.mark.asyncio
async def test_rag_pattern_fires_on_filename():
    ctx = _ctx(
        "As per MBA_HomeLending_Market_Report_Q4_2024.docx how is the forecast for loan model?",
    )
    m = await RAGPattern().detect(ctx)
    assert m.accepted
    assert any("docx" in e or ".docx" in e for e in m.evidence)


@pytest.mark.asyncio
async def test_rag_pattern_fires_on_phrase():
    ctx = _ctx("according to the document, what is the forecast?")
    m = await RAGPattern().detect(ctx)
    assert m.accepted


@pytest.mark.asyncio
async def test_rag_pattern_silent_for_data_questions():
    ctx = _ctx("how many loans in pmos_servicing have term_months > 300")
    m = await RAGPattern().detect(ctx)
    assert not m.accepted


@pytest.mark.asyncio
async def test_metadata_pattern_via_translator_intent():
    ctx = _ctx(
        "how many tables have loan_id columns?",
        translator={"intent": "schema_meta_question", "schema_meta_column": "loan_id"},
        team=_team(["DATABASE"], ["DATABASE", "GRAPH"]),
    )
    m = await MetadataPattern().detect(ctx)
    assert m.accepted
    assert m.payload["column"] == "loan_id"
    assert len(m.payload["db_agent_ids"]) == 2


@pytest.mark.asyncio
async def test_metadata_pattern_via_regex_only():
    """If the translator wasn't run, regex still picks it up."""
    ctx = _ctx(
        "in which tables can I find a customer_id column",
        team=_team(["DATABASE"]),
    )
    m = await MetadataPattern().detect(ctx)
    assert m.accepted


@pytest.mark.asyncio
async def test_metadata_pattern_drops_score_when_no_db_agents():
    ctx = _ctx(
        "how many tables have loan_id columns?",
        translator={"intent": "schema_meta_question", "schema_meta_column": "loan_id"},
        team=_team(["GITHUB"], ["PYTHON"]),  # no DB/GRAPH agents
    )
    m = await MetadataPattern().detect(ctx)
    assert not m.accepted, "should fall through to BusinessPattern when no DB agents"


@pytest.mark.asyncio
async def test_column_value_pattern_via_translator_intent():
    ctx = _ctx(
        "what is the value of loan_id across these tables, give me sample of 5 values",
        translator={"intent": "column_value_question", "schema_meta_column": "loan_id"},
        team=_team(["DATABASE"]),
    )
    m = await ColumnValuePattern().detect(ctx)
    assert m.accepted
    assert m.payload["column"] == "loan_id"
    assert m.payload["sample_n"] == 5


@pytest.mark.asyncio
async def test_column_value_pattern_picks_up_sample_count():
    ctx = _ctx(
        "give me 25 sample borrower_id values from each table",
        team=_team(["DATABASE"]),
    )
    m = await ColumnValuePattern().detect(ctx)
    assert m.accepted
    assert m.payload["column"] == "borrower_id"
    assert m.payload["sample_n"] == 25


@pytest.mark.asyncio
async def test_column_value_pattern_skips_single_table_query():
    """No multi-source qualifier → not a broadcast question."""
    ctx = _ctx("show me 5 rows of the loans table", team=_team(["DATABASE"]))
    m = await ColumnValuePattern().detect(ctx)
    assert not m.accepted


@pytest.mark.asyncio
async def test_entity_count_pattern_via_translator_intent():
    """The translator emits intent='entity_count_question' with the
    entity token in schema_meta_column. EntityCountPattern picks it up."""
    ctx = _ctx(
        "how many total loans are there in the system",
        translator={"intent": "entity_count_question",
                    "schema_meta_column": "loans"},
        team=_team(["DATABASE"], ["GRAPH"]),
    )
    m = await EntityCountPattern().detect(ctx)
    assert m.accepted
    assert m.payload["entity"] == "loans"
    assert len(m.payload["db_agent_ids"]) == 2
    assert m.payload["aggregation"] == "python_reduce"


@pytest.mark.asyncio
async def test_entity_count_pattern_via_regex_only():
    """Regex carries the decision when translator wasn't run."""
    ctx = _ctx(
        "how many borrowers do we have",
        team=_team(["DATABASE"]),
    )
    m = await EntityCountPattern().detect(ctx)
    assert m.accepted
    assert m.payload["entity"] == "borrowers"


@pytest.mark.asyncio
async def test_entity_count_pattern_skips_when_table_token_present():
    """When the user mentions 'tables' or 'columns', let MetadataPattern
    or ColumnValuePattern take over — EntityCountPattern is for pure
    counts only."""
    ctx = _ctx(
        "how many tables have loan_id columns",
        team=_team(["DATABASE"]),
    )
    m = await EntityCountPattern().detect(ctx)
    assert not m.accepted


@pytest.mark.asyncio
async def test_entity_count_pattern_skips_when_predicate_present():
    """A WHERE-clause-like predicate ('term_months > 300') makes this a
    BusinessPattern question, not an entity-count broadcast."""
    ctx = _ctx(
        "how many loans in pmos_servicing.loans have term_months > 300",
        team=_team(["DATABASE"]),
    )
    m = await EntityCountPattern().detect(ctx)
    assert not m.accepted


@pytest.mark.asyncio
async def test_entity_count_pattern_skips_aggregator_questions():
    """'average loan amount' / 'sum of payments' aren't entity counts;
    BusinessPattern handles them."""
    ctx = _ctx(
        "what is the average loan amount across all servicing tables",
        team=_team(["DATABASE"]),
    )
    m = await EntityCountPattern().detect(ctx)
    assert not m.accepted


@pytest.mark.asyncio
async def test_entity_count_pattern_drops_score_when_no_db_agents():
    ctx = _ctx(
        "how many loans are there",
        team=_team(["GITHUB"]),  # no DATABASE/GRAPH agents
    )
    m = await EntityCountPattern().detect(ctx)
    assert not m.accepted, "should fall through when no DB/GRAPH agents on team"


@pytest.mark.asyncio
async def test_business_pattern_when_translator_bound_entities():
    ctx = _ctx(
        "how many loans in pmos_servicing have term_months > 300",
        translator={
            "canonical_entities": [{"name": "Loan"}],
            "dataset_bindings": [{"asset_fq_name": "pmos_servicing.loans"}],
            "domain_subtasks": ["count loans with term_months > 300"],
            "intent": "metric_lookup",
        },
        team=_team(["DATABASE"]),
    )
    m = await BusinessPattern().detect(ctx)
    assert m.accepted
    assert m.payload["canonical_count"] == 1
    assert m.payload["binding_count"] == 1


@pytest.mark.asyncio
async def test_business_pattern_silent_when_no_ontology():
    ctx = _ctx("hi", translator={})
    m = await BusinessPattern().detect(ctx)
    assert not m.accepted


@pytest.mark.asyncio
async def test_freeform_pattern_always_matches():
    """FreeForm is the catch-all — accepts any question, score=0.1."""
    ctx = _ctx("anything")
    m = await FreeFormPattern().detect(ctx)
    assert m.accepted  # threshold is 0.0
    assert m.score == pytest.approx(0.1)


# ---------------------------------------------------------------------------
# End-to-end routing — the 10 sample questions from the design doc
# ---------------------------------------------------------------------------

def _full_dispatcher() -> PatternDispatcher:
    return PatternDispatcher(build_default_registry().all())


@pytest.mark.asyncio
async def test_route_loan_default_servicing_report():
    """Question 1: 'Show me the loan default servicing report for last year'"""
    disp = _full_dispatcher()
    ctx = _ctx(
        "Show me the loan default servicing report for last year",
        translator={"matched_reports": [
            {"report_id": "R1", "name": "Loan Default Servicing Report",
             "score": 14.5},
            {"report_id": "R2", "name": "Loan Pipeline", "score": 6.0},
        ]},
        team=_team(["DATABASE"], ["GRAPH"]),
    )
    winner, _, trace = await disp.dispatch(ctx)
    assert trace.winner == "report"
    assert winner is not None and winner.name == "report"


@pytest.mark.asyncio
async def test_route_loan_status_in_specific_table():
    """Question 2: 'What is the status of the loan L0009 in pmos_servicing
    from foreclosures table?'"""
    disp = _full_dispatcher()
    ctx = _ctx(
        "What is the status of the loan L0009 in pmos_servicing from foreclosures table?",
        translator={
            "canonical_entities": [{"name": "Loan", "fq_name": "Servicing.Loan"}],
            "dataset_bindings": [{"asset_fq_name": "pmos_servicing.foreclosures"}],
            "domain_subtasks": ["look up loan L0009 status in foreclosures"],
            "intent": "metric_lookup",
        },
        team=_team(["DATABASE"]),
    )
    _, _, trace = await disp.dispatch(ctx)
    assert trace.winner == "business"


@pytest.mark.asyncio
async def test_route_loan_count_in_servicing():
    """Question 3: 'How many loans we have in pmos_servicing system?'"""
    disp = _full_dispatcher()
    ctx = _ctx(
        "How many loans we have in pmos_servicing system?",
        translator={
            "canonical_entities": [{"name": "Loan"}],
            "dataset_bindings": [{"asset_fq_name": "pmos_servicing.loans"}],
            "domain_subtasks": ["count loans"],
            "intent": "metric_lookup",
        },
        team=_team(["DATABASE"]),
    )
    _, _, trace = await disp.dispatch(ctx)
    assert trace.winner == "business"


@pytest.mark.asyncio
async def test_route_pure_entity_count_beats_clarify():
    """The user's actual failing case: 'how many total loans are there
    in the system'. Translator's synonym detector mis-fires on
    'total_*_amount' BAs and emits a clarification — EntityCountPattern
    (priority 86) must override Clarify (priority 85) and win the
    dispatch so the broadcast count + python_reduce path fires."""
    disp = _full_dispatcher()
    ctx = _ctx(
        "how many total loans are there in the system",
        translator={
            "intent": "entity_count_question",
            "schema_meta_column": "loans",
            # Even if the translator ALSO surfaced a stale clarification,
            # EntityCount must still win.
            "clarification_needed": True,
            "clarification_question": "Did you mean total_loan_amount or total_payment_amount?",
        },
        team=_team(
            ["DATABASE"],   # SakilaAnalyst-shaped
            ["DATABASE", "GRAPH"],  # HomeLendingAnalyst-shaped
            ["PYTHON"],     # PythonAnalyst — used by python_reduce
        ),
    )
    _, _, trace = await disp.dispatch(ctx)
    assert trace.winner == "entity_count"
    # And the trace should record entity_count as accepted with the
    # entity token and python_reduce flag in evidence/payload.
    cand = next(c for c in trace.candidates if c.name == "entity_count")
    assert cand.accepted
    assert "loans" in cand.explanation


@pytest.mark.asyncio
async def test_route_filtered_count_stays_on_business():
    """'how many loans where term_months > 300' is a filtered count,
    not a pure entity count — BusinessPattern handles it (predicates
    need the agent loop)."""
    disp = _full_dispatcher()
    ctx = _ctx(
        "how many loans in pmos_servicing.loans have term_months > 300",
        translator={
            "canonical_entities": [{"name": "Loan"}],
            "dataset_bindings": [{"asset_fq_name": "pmos_servicing.loans"}],
            "domain_subtasks": ["count loans with term_months > 300"],
            "intent": "metric_lookup",
        },
        team=_team(["DATABASE"]),
    )
    _, _, trace = await disp.dispatch(ctx)
    assert trace.winner == "business"


@pytest.mark.asyncio
async def test_route_docx_reference():
    """Question 4: 'As per MBA_HomeLending_Market_Report_Q4_2024.docx how is
    the forecast for loan model?'"""
    disp = _full_dispatcher()
    ctx = _ctx(
        "As per MBA_HomeLending_Market_Report_Q4_2024.docx how is the forecast for loan model?",
        team=_team(["DATABASE"]),
    )
    _, _, trace = await disp.dispatch(ctx)
    assert trace.winner == "rag"


@pytest.mark.asyncio
async def test_route_cross_source_business_question():
    """Question 5: 'How many BridgeLoan and HomeEquityLoan records do we
    have, and what borrower segments are in the home lending graph?'"""
    disp = _full_dispatcher()
    ctx = _ctx(
        "How many BridgeLoan and HomeEquityLoan records do we have, and what borrower segments are in the home lending graph?",
        translator={
            "canonical_entities": [
                {"name": "BridgeLoan"}, {"name": "HomeEquityLoan"}, {"name": "Borrower"},
            ],
            "dataset_bindings": [
                {"asset_fq_name": "Servicing.BridgeLoan"},
                {"asset_fq_name": "HomeLendingGraph.Borrower"},
            ],
            "domain_subtasks": ["count BridgeLoan/HomeEquityLoan", "summarize borrower segments"],
            "intent": "comparison",
        },
        team=_team(["DATABASE"], ["GRAPH"]),
    )
    _, _, trace = await disp.dispatch(ctx)
    assert trace.winner == "business"


@pytest.mark.asyncio
async def test_route_column_value_sampling():
    """Question 6: 'what is the value of loan_id across these tables, give
    me sample of 5 values from each of these tables.'"""
    disp = _full_dispatcher()
    ctx = _ctx(
        "what is the value of loan_id across these tables, give me sample of 5 values from each of these tables.",
        translator={"intent": "column_value_question", "schema_meta_column": "loan_id"},
        team=_team(["DATABASE"], ["DATABASE", "GRAPH"]),
    )
    _, _, trace = await disp.dispatch(ctx)
    assert trace.winner == "column_value"


@pytest.mark.asyncio
async def test_route_metadata_question():
    """Question 7: 'how many tables have loan_id columns?'"""
    disp = _full_dispatcher()
    ctx = _ctx(
        "how many tables have loan_id columns?",
        translator={"intent": "schema_meta_question", "schema_meta_column": "loan_id"},
        team=_team(["DATABASE"]),
    )
    _, _, trace = await disp.dispatch(ctx)
    assert trace.winner == "metadata"


@pytest.mark.asyncio
async def test_route_specific_table_predicate():
    """Question 8: 'how many loans in the servicing table pmos_servicing.loans
    have term months > 300'"""
    disp = _full_dispatcher()
    ctx = _ctx(
        "how many loans in the servicing table pmos_servicing.loans have term months > 300",
        translator={
            "canonical_entities": [{"name": "Loan"}],
            "dataset_bindings": [{"asset_fq_name": "pmos_servicing.loans"}],
            "domain_subtasks": ["count loans with term_months > 300"],
            "intent": "metric_lookup",
        },
        team=_team(["DATABASE"]),
    )
    _, _, trace = await disp.dispatch(ctx)
    assert trace.winner == "business"


@pytest.mark.asyncio
async def test_route_team_self_question():
    """Question 9: 'hi how many agents do you have in your team with access
    to which tools'"""
    disp = _full_dispatcher()
    ctx = _ctx(
        "hi how many agents do you have in your team with access to which tools",
        team=_team(["DATABASE"], ["GRAPH"], ["GITHUB"]),
    )
    _, _, trace = await disp.dispatch(ctx)
    assert trace.winner == "team_self"


@pytest.mark.asyncio
async def test_route_explicit_neo4j_business_query():
    """Question 10: 'Using the Neo4j Home Lending Graph DB, query the graph
    to find all borrowers for mortgage loan LOAN001…'"""
    disp = _full_dispatcher()
    ctx = _ctx(
        "Using the Neo4j Home Lending Graph DB, query the graph to find all borrowers for mortgage loan LOAN001, the property that secures it, the interest rate, and list all payments made on this loan. Use Cypher queries against the Neo4j graph database.",
        translator={
            "canonical_entities": [
                {"name": "MortgageLoan"}, {"name": "Borrower"}, {"name": "Property"},
            ],
            "dataset_bindings": [{"asset_fq_name": "HomeLendingGraph.MortgageLoan"}],
            "domain_subtasks": ["find borrowers, property, payments for LOAN001"],
            "intent": "lineage",
        },
        team=_team(["GRAPH"], ["DATABASE"]),
    )
    _, _, trace = await disp.dispatch(ctx)
    assert trace.winner == "business"


# ---------------------------------------------------------------------------
# Tie-breaks — the priority order is enforced
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_clarify_beats_business_when_both_fire():
    """Translator surfaces a clarification AND has canonical entities —
    we must ask the user, not run the agent loop."""
    disp = _full_dispatcher()
    ctx = _ctx(
        "show me loan",
        translator={
            "clarification_needed": True,
            "clarification_question": "Did you mean BridgeLoan or HomeEquityLoan?",
            "canonical_entities": [{"name": "Loan"}],
            "dataset_bindings": [{"asset_fq_name": "Servicing.Loan"}],
        },
        team=_team(["DATABASE"]),
    )
    _, _, trace = await disp.dispatch(ctx)
    assert trace.winner == "clarify"


@pytest.mark.asyncio
async def test_freeform_wins_only_when_nothing_else_does():
    """A bare 'hi' with no team-self phrasing should land on freeform."""
    disp = _full_dispatcher()
    ctx = _ctx("hi", translator={"intent": "freeform_qna"})
    _, _, trace = await disp.dispatch(ctx)
    assert trace.winner == "freeform"


@pytest.mark.asyncio
async def test_rag_beats_metadata_when_doc_extension_present():
    """Edge case: user mentions a docx but also says 'tables / columns'.
    RAG (priority 80) must win over Metadata (priority 70)."""
    disp = _full_dispatcher()
    ctx = _ctx(
        "what tables have loan_id columns according to schema.pdf",
        translator={"intent": "schema_meta_question", "schema_meta_column": "loan_id"},
        team=_team(["DATABASE"]),
    )
    _, _, trace = await disp.dispatch(ctx)
    assert trace.winner == "rag"
