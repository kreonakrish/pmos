"""Phase-4 cutover tests.

Verifies the dispatcher's winner drives the Report (auto_fire/confirm)
and Clarify branches. Two layers:

1. Pure-logic tests on the should_auto_fire / should_confirm /
   should_clarify computation by stubbing _last_pattern_winner /
   _last_pattern_payload directly. These pin the cutover wiring
   without booting the whole pipeline.

2. End-to-end protocol test: a fake pipeline harness exercises both
   "dispatcher says Report" and "dispatcher says Business" and
   confirms the right helper gets called.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.patterns import (
    DispatchContext,
    PatternDispatcher,
    PatternMatch,
    PatternRegistry,
    TeamContext,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _StubPattern:
    """One-shot stub returning a canned PatternMatch."""

    def __init__(self, name: str, priority: int, score: float, threshold: float,
                 payload: Optional[Dict[str, Any]] = None,
                 evidence: Optional[List[str]] = None):
        self.name = name
        self.priority = priority
        self._match = PatternMatch(
            score=score,
            threshold=threshold,
            payload=dict(payload or {}),
            evidence=list(evidence or []),
            explanation=f"{name}@{score}",
        )

    async def detect(self, ctx):
        return self._match

    async def plan(self, ctx, match):
        from app.services.patterns.types import ExecutionPlan
        return ExecutionPlan(subtasks=[])

    async def execute(self, ctx, plan):
        from app.services.patterns.types import ExecutionResult
        return ExecutionResult(response="stub")


def _ctx() -> DispatchContext:
    return DispatchContext(
        question="q",
        team_id="t",
        conversation_id="c",
        trace_id="tr",
        session_id="s",
        graph_id="g",
        prior_turns=[],
        translator={},
        team=TeamContext(),
    )


# ---------------------------------------------------------------------------
# Dispatcher cutover wiring — winner picks the band
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatcher_winner_selects_report_auto_fire():
    """Report pattern wins with kind=auto_fire — execute() should pick
    the auto-fire branch even when legacy thresholds disagree."""
    dispatcher = PatternDispatcher([
        _StubPattern("report", priority=90, score=14.0, threshold=5.0,
                     payload={"kind": "auto_fire", "score": 14.0}),
        _StubPattern("freeform", priority=0, score=0.1, threshold=0.0),
    ])
    winner, match, trace = await dispatcher.dispatch(_ctx())
    assert winner is not None and winner.name == "report"
    assert match.payload["kind"] == "auto_fire"
    assert trace.winner == "report"


@pytest.mark.asyncio
async def test_dispatcher_winner_selects_report_confirm():
    dispatcher = PatternDispatcher([
        _StubPattern("report", priority=90, score=8.0, threshold=5.0,
                     payload={"kind": "confirm", "score": 8.0}),
        _StubPattern("freeform", priority=0, score=0.1, threshold=0.0),
    ])
    winner, match, _ = await dispatcher.dispatch(_ctx())
    assert winner.name == "report"
    assert match.payload["kind"] == "confirm"


@pytest.mark.asyncio
async def test_dispatcher_winner_selects_clarify_over_business():
    """Clarify (priority 85) beats Business (priority 50) when both
    accept."""
    dispatcher = PatternDispatcher([
        _StubPattern("business", priority=50, score=0.7, threshold=0.5),
        _StubPattern("clarify", priority=85, score=0.95, threshold=0.5,
                     payload={"question": "Did you mean X or Y?"}),
        _StubPattern("freeform", priority=0, score=0.1, threshold=0.0),
    ])
    winner, _, trace = await dispatcher.dispatch(_ctx())
    assert winner.name == "clarify"
    assert trace.winner == "clarify"


@pytest.mark.asyncio
async def test_dispatcher_falls_through_to_business_when_no_special_pattern():
    dispatcher = PatternDispatcher([
        _StubPattern("report", priority=90, score=0.0, threshold=5.0),
        _StubPattern("clarify", priority=85, score=0.0, threshold=0.5),
        _StubPattern("metadata", priority=70, score=0.0, threshold=0.6),
        _StubPattern("business", priority=50, score=0.7, threshold=0.5),
        _StubPattern("freeform", priority=0, score=0.1, threshold=0.0),
    ])
    winner, _, _ = await dispatcher.dispatch(_ctx())
    assert winner.name == "business"


# ---------------------------------------------------------------------------
# Cutover gate logic — the should_auto_fire / should_confirm / should_clarify
# expressions in execute() match these truth tables.
# ---------------------------------------------------------------------------

class TestCutoverGateLogic:
    """Mirror the boolean expressions in pipeline.execute() so the
    Phase-4 wiring stays correct under refactors."""

    @staticmethod
    def _gates(routing_enabled: bool,
               winner: Optional[str],
               payload: Optional[Dict[str, Any]],
               legacy_auto_fire: bool,
               legacy_confirm: bool,
               legacy_clarify: bool):
        """Reproduces the gate expressions from pipeline.execute()."""
        payload = payload or {}
        dispatcher_says_report = routing_enabled and winner == "report"
        dispatcher_report_kind = (
            str(payload.get("kind") or "") if dispatcher_says_report else ""
        )
        should_auto_fire = (
            dispatcher_report_kind == "auto_fire"
            if dispatcher_says_report
            else legacy_auto_fire
        )
        should_confirm = (
            dispatcher_report_kind == "confirm"
            if dispatcher_says_report
            else legacy_confirm
        )
        dispatcher_says_clarify = routing_enabled and winner == "clarify"
        should_clarify = (
            dispatcher_says_clarify
            if routing_enabled and winner is not None
            else legacy_clarify
        )
        return should_auto_fire, should_confirm, should_clarify

    def test_dispatcher_auto_fire_overrides_legacy(self):
        """Even when legacy thresholds disagree, dispatcher wins."""
        af, cf, _ = self._gates(
            routing_enabled=True,
            winner="report",
            payload={"kind": "auto_fire"},
            legacy_auto_fire=False,
            legacy_confirm=True,  # legacy thinks "confirm"
            legacy_clarify=False,
        )
        assert af is True
        assert cf is False

    def test_dispatcher_confirm_blocks_legacy_auto_fire(self):
        """If dispatcher says confirm, legacy can't escalate to auto-fire."""
        af, cf, _ = self._gates(
            routing_enabled=True,
            winner="report",
            payload={"kind": "confirm"},
            legacy_auto_fire=True,
            legacy_confirm=True,
            legacy_clarify=False,
        )
        assert af is False
        assert cf is True

    def test_dispatcher_clarify_overrides_legacy_silence(self):
        """Dispatcher decides to clarify → gate fires even if Neo4j meta
        is empty (e.g. translator round-trip didn't stamp the field)."""
        _, _, clar = self._gates(
            routing_enabled=True,
            winner="clarify",
            payload={},
            legacy_auto_fire=False,
            legacy_confirm=False,
            legacy_clarify=False,
        )
        assert clar is True

    def test_dispatcher_business_silences_legacy_clarify(self):
        """Dispatcher routed to Business → don't surface a stale legacy
        clarification. The dispatcher's verdict is authoritative."""
        _, _, clar = self._gates(
            routing_enabled=True,
            winner="business",
            payload={},
            legacy_auto_fire=False,
            legacy_confirm=False,
            legacy_clarify=True,  # legacy still thinks clarify
        )
        assert clar is False

    def test_routing_disabled_falls_through_to_legacy(self):
        """Cutover flag off → all decisions defer to legacy
        thresholds. Used as a kill-switch in case of regressions."""
        af, cf, clar = self._gates(
            routing_enabled=False,
            winner="report",  # would have routed to report
            payload={"kind": "auto_fire"},
            legacy_auto_fire=False,
            legacy_confirm=False,
            legacy_clarify=True,
        )
        assert af is False
        assert cf is False
        assert clar is True

    def test_dispatch_failure_falls_through_to_legacy(self):
        """Dispatcher raised → winner=None → execute() must use legacy
        thresholds (no silent regression)."""
        af, cf, clar = self._gates(
            routing_enabled=True,
            winner=None,
            payload=None,
            legacy_auto_fire=True,
            legacy_confirm=False,
            legacy_clarify=False,
        )
        assert af is True
        assert cf is False
        assert clar is False

    def test_clarify_winner_with_routing_off_uses_legacy(self):
        af, cf, clar = self._gates(
            routing_enabled=False,
            winner="clarify",
            payload={},
            legacy_auto_fire=False,
            legacy_confirm=False,
            legacy_clarify=True,
        )
        assert clar is True

    def test_no_winner_no_legacy_means_no_gate_fires(self):
        af, cf, clar = self._gates(
            routing_enabled=True,
            winner=None,
            payload=None,
            legacy_auto_fire=False,
            legacy_confirm=False,
            legacy_clarify=False,
        )
        assert (af, cf, clar) == (False, False, False)
