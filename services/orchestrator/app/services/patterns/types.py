"""Type definitions for the question-pattern dispatcher.

These types are deliberately simple dataclasses — no behaviour, no
Pydantic. The dispatcher's invariants are enforced by the pattern
implementations and the dispatcher itself, not by the data shapes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

@dataclass
class TeamContext:
    """Lazy bundle of team-level facts every pattern may need.

    Fields are populated on first access by the dispatcher (one HTTP call
    to agent-mgmt amortised across every pattern that asks). Patterns
    never call agent-mgmt directly during ``detect()``.
    """
    team_id: str = ""
    name: str = ""
    # Agents on the team — list of dicts with at least ``agent_id``,
    # ``agent_name``, ``role``. Each dict may have a ``tools`` key
    # populated by the dispatcher.
    agents: List[Dict[str, Any]] = field(default_factory=list)
    # Pre-formatted text for system prompts (today's _load_team_hierarchy
    # output). Patterns paste this verbatim into agent prompts when they
    # don't need structured access.
    text: str = ""

    def agents_with_tool_type(self, *types: str) -> List[Dict[str, Any]]:
        """Filter agents by tool type — convenient for broadcast plans."""
        wanted = {t.upper() for t in types}
        out: List[Dict[str, Any]] = []
        for a in self.agents:
            tools = a.get("tools") or []
            if any(str(t.get("tool_type") or "").upper() in wanted for t in tools):
                out.append(a)
        return out


@dataclass
class DispatchContext:
    """Everything a pattern needs to make a routing decision.

    The same ``DispatchContext`` is handed to every pattern's
    ``detect()`` and is passed forward to ``plan()`` and ``execute()``
    on the winner. Patterns may read fields freely but must NOT mutate
    them — the dispatcher hands the same object to every detector and
    cross-talk via shared state would defeat the audit trail.
    """
    question: str
    team_id: str
    conversation_id: str
    trace_id: str
    session_id: str
    graph_id: str = ""
    # Prior user/translator turns from the same conversation (newest last).
    prior_turns: List[Dict[str, Any]] = field(default_factory=list)
    # Cached translator output. Empty dict when translator wasn't run
    # (e.g. unit tests). Patterns should treat missing keys as ``None``
    # rather than crash.
    translator: Dict[str, Any] = field(default_factory=dict)
    # Lazy team facts. Populated by the dispatcher BEFORE detect() runs.
    team: TeamContext = field(default_factory=TeamContext)
    # Free-form bag for hooks/middleware (e.g. pending_report_confirm).
    # Patterns should generally not read this.
    extras: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Pattern result types
# ---------------------------------------------------------------------------

@dataclass
class PatternMatch:
    """What ``detect()`` returns. Pure data — no side effects.

    A pattern is *accepted* when ``score >= threshold``. Among accepted
    patterns the dispatcher picks by priority (higher first); ties
    within priority resolve to the pattern declared earlier in the
    registry.
    """
    score: float = 0.0
    threshold: float = 1.0
    # Concrete signals that fired. Each is a one-liner the UI can show
    # verbatim, e.g. "regex 'how many tables have X' matched on 'loan_id'".
    evidence: List[str] = field(default_factory=list)
    # Carried through to ``plan()`` — pattern's private payload. The
    # dispatcher does not interpret these fields.
    payload: Dict[str, Any] = field(default_factory=dict)
    # Single-line "why" string surfaced in the decision trace.
    explanation: str = ""

    @property
    def accepted(self) -> bool:
        return self.score >= self.threshold


@dataclass
class Subtask:
    """One executable unit of work, post-decomposition."""
    description: str
    # Optional pre-assigned agent_id. When set, the dispatcher skips
    # capability negotiation for this subtask.
    agent_id: Optional[str] = None
    # Optional override for the score-band check. ``True`` means the
    # subtask succeeds regardless of score (used by broadcast patterns
    # where partial coverage is the correct answer).
    force_proceed: bool = False
    # Per-subtask metadata for telemetry / aggregation.
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionPlan:
    """Concrete plan emitted by ``plan()`` and consumed by ``execute()``.

    Aggregation strategies:
      * ``"default"`` — step-8 LLM synthesis of node results.
      * ``"report_passthrough"`` — ``response`` is the final answer; no
        agent loop ran (Report path).
      * ``"broadcast_merge"`` — same as default but tagged for the UI.
      * ``"rag_synthesis"`` — RAG retrieval + LLM synthesis, no agents.
      * ``"clarify"`` — surface ``response`` as a clarification question.
    """
    subtasks: List[Subtask] = field(default_factory=list)
    aggregation: str = "default"
    # Set when the pattern has a final response that bypasses execution
    # (Report passthrough, clarify prompt, ...).
    response: Optional[str] = None
    # Set when ``plan()`` wants to surface a clarification question.
    clarification_needed: bool = False
    clarification_question: Optional[str] = None
    clarification_kind: Optional[str] = None
    # Per-pattern bag for execute() to consume.
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionResult:
    """What ``execute()`` returns to the orchestrator entrypoint.

    Mirrors the existing ``execute()`` return shape so the cutover can
    be in-place.
    """
    response: str
    score: Optional[float] = None
    visualizations: List[Dict[str, Any]] = field(default_factory=list)
    clarification_needed: bool = False
    clarification_question: Optional[str] = None
    clarification_kind: Optional[str] = None
    auditor_issue_id: Optional[str] = None
    auditor_issue_kind: Optional[str] = None
    pending_report_id: Optional[str] = None
    matched_report_id: Optional[str] = None
    # Per-node results (for debugging / future RL signals).
    node_results: List[Dict[str, Any]] = field(default_factory=list)
    extras: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Decision trace (what the UI shows)
# ---------------------------------------------------------------------------

@dataclass
class CandidateScore:
    """One row in the decision-trace table."""
    name: str
    priority: int
    score: float
    threshold: float
    accepted: bool
    evidence: List[str] = field(default_factory=list)
    explanation: str = ""
    # Set when ``detect()`` raised — the dispatcher records but never
    # propagates pattern bugs.
    error: Optional[str] = None
    duration_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "priority": self.priority,
            "score": round(self.score, 4),
            "threshold": round(self.threshold, 4),
            "accepted": self.accepted,
            "evidence": list(self.evidence),
            "explanation": self.explanation,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


@dataclass
class DecisionTrace:
    """Full record of one dispatch decision. Stamped on the TaskGraph
    so the Pipeline-Jobs UI can render the candidate table without
    re-running anything."""
    candidates: List[CandidateScore] = field(default_factory=list)
    winner: Optional[str] = None
    duration_ms: int = 0
    # Lightweight summary of the translator state at decision time.
    translator_summary: Dict[str, Any] = field(default_factory=dict)
    # Set when this is the shadow trace recorded alongside the legacy
    # routing — useful while we migrate.
    shadow: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidates": [c.to_dict() for c in self.candidates],
            "winner": self.winner,
            "duration_ms": self.duration_ms,
            "translator_summary": self.translator_summary,
            "shadow": self.shadow,
        }


# ---------------------------------------------------------------------------
# Pattern Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class QuestionPattern(Protocol):
    """Contract for every routable pattern.

    Patterns are stateless — the same instance handles every request.
    Mutable state (counters, caches) belongs on the dispatcher or in
    the database, not on the pattern.
    """

    name: str
    priority: int

    async def detect(self, ctx: DispatchContext) -> PatternMatch:
        """Score the request. Pure: no side effects, no LLM calls
        unless caching is solid. Should return quickly (≪ 50ms typical)
        because every pattern's ``detect()`` runs on every request."""
        ...

    async def plan(self, ctx: DispatchContext, match: PatternMatch) -> ExecutionPlan:
        """Build the concrete plan from a winning match. May call
        agent-mgmt / Neo4j / etc. — runs only on the winner."""
        ...

    async def execute(self, ctx: DispatchContext, plan: ExecutionPlan) -> ExecutionResult:
        """Execute the plan. Most patterns delegate to a shared
        agent-loop runner; some (Report passthrough, RAG-only, clarify)
        bypass it entirely."""
        ...


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def now_ms() -> float:
    return time.monotonic() * 1000.0
