"""Pydantic models for capability negotiation bids."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class BidRequest(BaseModel):
    """Broadcast to each agent in a team for capability negotiation."""
    task_id: str
    task_description: str
    task_type: str = "general"
    graph_id: str = ""
    required_capabilities: List[str] = Field(default_factory=list)
    context: Dict[str, Any] = Field(default_factory=dict)
    trace_id: str = ""

    # Dataset bindings stamped on the TaskNode by the Translator (Phase C3).
    # When non-empty, capability negotiation requires each candidate agent to
    # have at least one tool that ACCESSES a DataSource owning at least one
    # of these DataAssets — agents that can't reach the data are dropped
    # before ranking.
    dataset_bindings: List[str] = Field(default_factory=list)


class BidPlanStep(BaseModel):
    """A single step in the agent's commitment plan.

    The agent's bid promises to run roughly this query against this tool;
    execution carries the plan forward as the system prompt's commitment
    contract. Reality may differ; the plan is a sketch, not a literal SQL.
    """
    tool: str = ""                       # tool name the step targets
    kind: str = "sql"                    # "sql" | "cypher" | "api" | "python"
    sketch: str = ""                     # SQL/Cypher template the agent intends to run
    expected_columns: List[str] = Field(default_factory=list)
    purpose: str = ""                    # which part of the question this step addresses


class BidCoverage(BaseModel):
    """Agent's self-assessment of which question parts it can/can't answer.

    Used by coverage-aware ranking (single-winner) and complementary-winner
    selection (multi-winner set cover). ``answerable`` is the contract:
    if the agent wins, it owes results for these parts.
    """
    answerable: List[str] = Field(default_factory=list)
    not_answerable: List[str] = Field(default_factory=list)
    reason_missing: str = ""

    def ratio(self) -> float:
        total = len(self.answerable) + len(self.not_answerable)
        if total == 0:
            return 0.0
        return len(self.answerable) / total


class BidResponse(BaseModel):
    """An individual agent's bid for a task."""
    agent_id: str
    agent_name: str = ""
    confidence: float = 0.0          # 0.0-1.0, self-assessed capability match
    memory_relevance: float = 0.0    # 0.0-1.0, how much relevant memory was found
    estimated_latency_ms: int = 0    # self-estimated execution time
    tools_available: List[str] = Field(default_factory=list)
    tool_ids: List[str] = Field(default_factory=list)
    reasoning: str = ""              # LLM explanation of why this agent is a good fit
    eligible: bool = True            # False if agent cannot handle the task at all
    foundation_model: str = ""
    provider: str = ""
    error: Optional[str] = None      # Set if the bid request itself failed

    # Phase 21 — set by the dataset-binding filter when ``BidRequest`` carries
    # bindings. ``dataset_access_verified`` is False when the agent's tools
    # can't reach any of the required assets; such bids are excluded from
    # ranking. ``accessible_assets`` is the subset of ``BidRequest.dataset_bindings``
    # this agent's tools can actually reach.
    dataset_access_verified: bool = True
    accessible_assets: List[str] = Field(default_factory=list)

    # Phase 22 — bid as capability contract. ``coverage`` is the agent's
    # self-declared answerable/not-answerable split; ``plan`` is the SQL/
    # Cypher/Python sketch it commits to running. Both are produced by the
    # bid LLM with grounded schema/sample context. When the bid LLM returns
    # the legacy {confidence, reasoning, eligible} shape (or fails parsing
    # the new shape), these stay empty and ranking falls back to legacy.
    coverage: Optional[BidCoverage] = None
    plan: List[BidPlanStep] = Field(default_factory=list)
    plan_format: str = "structured"  # "structured" | "legacy"


class NegotiationResult(BaseModel):
    """Outcome of capability negotiation for a single task."""
    task_id: str
    task_description: str
    winner: Optional[BidResponse] = None
    fallback_chain: List[BidResponse] = Field(default_factory=list)
    all_bids: List[BidResponse] = Field(default_factory=list)
    negotiation_time_ms: int = 0
    trace_id: str = ""

    # Phase 22 — when no single bid covers the question, the orchestrator
    # picks a complementary cover (multiple winners, each owning a slice).
    # ``complementary_winners`` is the chosen set in execution order.
    # ``uncovered_parts`` are question parts no bid claimed; step-9
    # synthesis surfaces these as "we don't have data for X."
    complementary_winners: List[BidResponse] = Field(default_factory=list)
    uncovered_parts: List[str] = Field(default_factory=list)
