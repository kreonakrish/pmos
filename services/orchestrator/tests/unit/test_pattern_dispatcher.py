"""Unit tests for the question-pattern dispatcher.

The dispatcher is dependency-free at the type level — these tests
build fake patterns inline rather than importing the migrated
production patterns (which arrive in Phase 3).
"""

from __future__ import annotations

import pytest

from app.services.patterns import (
    DispatchContext,
    PatternDispatcher,
    PatternMatch,
    QuestionPattern,
    TeamContext,
    build_default_registry,
)
from app.services.patterns.types import ExecutionPlan, ExecutionResult


# ---------------------------------------------------------------------------
# Fake patterns
# ---------------------------------------------------------------------------

class FakePattern:
    """Minimal pattern implementation for dispatcher tests."""

    def __init__(
        self,
        name: str,
        priority: int = 50,
        score: float = 0.0,
        threshold: float = 0.5,
        evidence: list = None,
        explanation: str = "",
        raise_on_detect: bool = False,
    ):
        self.name = name
        self.priority = priority
        self._score = score
        self._threshold = threshold
        self._evidence = list(evidence or [])
        self._explanation = explanation
        self._raise = raise_on_detect

    async def detect(self, ctx: DispatchContext) -> PatternMatch:
        if self._raise:
            raise RuntimeError(f"{self.name} blew up")
        return PatternMatch(
            score=self._score,
            threshold=self._threshold,
            evidence=self._evidence,
            explanation=self._explanation,
            payload={"name": self.name},
        )

    async def plan(self, ctx, match) -> ExecutionPlan:
        return ExecutionPlan(subtasks=[], aggregation="default")

    async def execute(self, ctx, plan) -> ExecutionResult:
        return ExecutionResult(response=f"{self.name} executed")


def make_ctx(**overrides) -> DispatchContext:
    base = dict(
        question="how many tables have loan_id columns?",
        team_id="team-x",
        conversation_id="conv-x",
        trace_id="trace-x",
        session_id="sess-x",
        graph_id="graph-x",
        prior_turns=[],
        translator={"intent": "schema_meta_question",
                    "fallback_used": True,
                    "schema_meta_column": "loan_id"},
        team=TeamContext(team_id="team-x", name="Test", agents=[]),
        extras={},
    )
    base.update(overrides)
    return DispatchContext(**base)


# ---------------------------------------------------------------------------
# QuestionPattern protocol
# ---------------------------------------------------------------------------

def test_fake_pattern_satisfies_protocol():
    """Sanity: FakePattern is callable through the QuestionPattern Protocol."""
    p = FakePattern("noop")
    assert isinstance(p, QuestionPattern)


# ---------------------------------------------------------------------------
# Dispatcher behavior
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_with_no_patterns_returns_no_winner():
    disp = PatternDispatcher([])
    ctx = make_ctx()

    winner, match, trace = await disp.dispatch(ctx)

    assert winner is None
    assert match is None
    assert trace.winner is None
    assert trace.candidates == []


@pytest.mark.asyncio
async def test_dispatch_picks_highest_priority_among_accepted():
    high = FakePattern("high_pri", priority=90, score=0.9, threshold=0.5)
    low = FakePattern("low_pri", priority=10, score=0.99, threshold=0.5)
    disp = PatternDispatcher([low, high])  # registry order: low first

    winner, match, trace = await disp.dispatch(ctx=make_ctx())

    assert winner is high
    assert match is not None
    assert match.payload == {"name": "high_pri"}
    assert trace.winner == "high_pri"
    # Both candidates are accepted but priority breaks the tie.
    accepted = [c for c in trace.candidates if c.accepted]
    assert {c.name for c in accepted} == {"high_pri", "low_pri"}


@pytest.mark.asyncio
async def test_dispatch_skips_rejected_patterns():
    rejected = FakePattern("reject", priority=99, score=0.1, threshold=0.5)
    accepted = FakePattern("accept", priority=10, score=0.6, threshold=0.5)
    disp = PatternDispatcher([rejected, accepted])

    winner, _, trace = await disp.dispatch(make_ctx())

    assert winner is accepted
    assert trace.winner == "accept"
    rej_row = next(c for c in trace.candidates if c.name == "reject")
    assert rej_row.accepted is False
    assert rej_row.score == pytest.approx(0.1)


@pytest.mark.asyncio
async def test_dispatch_records_every_candidate():
    patterns = [
        FakePattern("a", priority=80, score=0.0, threshold=0.5),
        FakePattern("b", priority=70, score=0.7, threshold=0.5,
                    evidence=["regex matched", "intent=schema_meta_question"],
                    explanation="catalog phrasing detected"),
        FakePattern("c", priority=60, score=0.99, threshold=0.5),
    ]
    disp = PatternDispatcher(patterns)

    _, _, trace = await disp.dispatch(make_ctx())

    names = [c.name for c in trace.candidates]
    assert names == ["a", "b", "c"]
    b_row = next(c for c in trace.candidates if c.name == "b")
    assert b_row.evidence == ["regex matched", "intent=schema_meta_question"]
    assert b_row.explanation == "catalog phrasing detected"
    assert b_row.duration_ms >= 0


@pytest.mark.asyncio
async def test_dispatch_swallows_pattern_exceptions():
    """A single broken pattern must not crash the dispatcher."""
    boom = FakePattern("boom", priority=99, raise_on_detect=True)
    ok = FakePattern("ok", priority=10, score=0.7, threshold=0.5)
    disp = PatternDispatcher([boom, ok])

    winner, _, trace = await disp.dispatch(make_ctx())

    assert winner is ok
    boom_row = next(c for c in trace.candidates if c.name == "boom")
    assert boom_row.accepted is False
    assert boom_row.error is not None
    assert "blew up" in boom_row.error


@pytest.mark.asyncio
async def test_dispatch_preserves_registry_order_within_priority():
    a = FakePattern("first", priority=50, score=0.7, threshold=0.5)
    b = FakePattern("second", priority=50, score=0.7, threshold=0.5)
    disp = PatternDispatcher([a, b])

    winner, _, trace = await disp.dispatch(make_ctx())

    # Same priority + both accepted → registry order wins.
    assert winner is a
    assert trace.winner == "first"


@pytest.mark.asyncio
async def test_dispatch_summarises_translator_state():
    disp = PatternDispatcher([FakePattern("p", score=0.0)])
    ctx = make_ctx(translator={
        "intent": "schema_meta_question",
        "fallback_used": True,
        "domain": "Servicing",
        "canonical_entities": [{"name": "Loan"}, {"name": "Borrower"}],
        "dataset_bindings": [{"asset_fq_name": "Servicing.Loan"}],
        "matched_reports": [],
        "schema_meta_column": "loan_id",
    })

    _, _, trace = await disp.dispatch(ctx)

    assert trace.translator_summary["intent"] == "schema_meta_question"
    assert trace.translator_summary["domain"] == "Servicing"
    assert trace.translator_summary["n_canonical_entities"] == 2
    assert trace.translator_summary["n_dataset_bindings"] == 1
    assert trace.translator_summary["n_matched_reports"] == 0
    assert trace.translator_summary["schema_meta_column"] == "loan_id"


@pytest.mark.asyncio
async def test_dispatch_marks_shadow_flag():
    disp = PatternDispatcher([FakePattern("p")])
    _, _, shadow_trace = await disp.dispatch(make_ctx(), shadow=True)
    _, _, live_trace = await disp.dispatch(make_ctx(), shadow=False)
    assert shadow_trace.shadow is True
    assert live_trace.shadow is False


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def test_default_registry_is_empty_during_phase_one():
    """Phase 1 ships an empty registry — patterns are added in Phase 3."""
    reg = build_default_registry()
    assert list(reg) == []


def test_registry_preserves_insertion_order():
    from app.services.patterns import PatternRegistry
    a = FakePattern("a")
    b = FakePattern("b")
    c = FakePattern("c")
    reg = PatternRegistry([a, b])
    reg.add(c)
    assert [p.name for p in reg] == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# DecisionTrace serialisation (UI consumes this JSON in Phase 2)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_decision_trace_to_dict_is_jsonable():
    import json
    p = FakePattern("p", score=0.6, threshold=0.5,
                    evidence=["regex /tables/ matched"],
                    explanation="catalog phrasing")
    disp = PatternDispatcher([p])

    _, _, trace = await disp.dispatch(make_ctx())

    payload = trace.to_dict()
    # Round-trip through json — Phase 2's API serialises this.
    serialized = json.dumps(payload)
    restored = json.loads(serialized)
    assert restored["winner"] == "p"
    assert restored["candidates"][0]["evidence"] == ["regex /tables/ matched"]
    assert restored["candidates"][0]["explanation"] == "catalog phrasing"
    assert restored["shadow"] is False


# ---------------------------------------------------------------------------
# TeamContext helpers
# ---------------------------------------------------------------------------

def test_team_context_filters_by_tool_type():
    tc = TeamContext(
        team_id="t",
        agents=[
            {"agent_name": "DBAgent", "tools": [{"tool_type": "DATABASE"}]},
            {"agent_name": "GraphAgent", "tools": [{"tool_type": "GRAPH"}]},
            {"agent_name": "GitHubAgent", "tools": [{"tool_type": "GITHUB"}]},
            {"agent_name": "MultiTool", "tools": [{"tool_type": "DATABASE"},
                                                   {"tool_type": "PYTHON"}]},
            {"agent_name": "ToollessAgent", "tools": []},
        ],
    )
    db_agents = tc.agents_with_tool_type("DATABASE")
    names = [a["agent_name"] for a in db_agents]
    assert names == ["DBAgent", "MultiTool"]

    db_or_graph = tc.agents_with_tool_type("DATABASE", "GRAPH")
    names = [a["agent_name"] for a in db_or_graph]
    assert names == ["DBAgent", "GraphAgent", "MultiTool"]


def test_team_context_handles_missing_tools_key():
    tc = TeamContext(team_id="t", agents=[{"agent_name": "x"}])
    assert tc.agents_with_tool_type("DATABASE") == []
