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


class NegotiationResult(BaseModel):
    """Outcome of capability negotiation for a single task."""
    task_id: str
    task_description: str
    winner: Optional[BidResponse] = None
    fallback_chain: List[BidResponse] = Field(default_factory=list)
    all_bids: List[BidResponse] = Field(default_factory=list)
    negotiation_time_ms: int = 0
    trace_id: str = ""
