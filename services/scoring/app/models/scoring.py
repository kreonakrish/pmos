"""
Pydantic data models for the scoring service HTTP API.
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ── Enumerations ──────────────────────────────────────────────────────────────

class FeedbackSource(str, Enum):
    AUTOMATED = "AUTOMATED"
    USER = "USER"
    INTER_AGENT = "INTER_AGENT"
    ORCHESTRATOR = "ORCHESTRATOR"


class FeedbackType(str, Enum):
    SCORE = "SCORE"
    CORRECTION = "CORRECTION"
    BAND_ADJUST = "BAND_ADJUST"
    RETRY = "RETRY"
    FALLBACK = "FALLBACK"
    AUTOCORRECT = "AUTOCORRECT"


class Recommendation(str, Enum):
    PROCEED = "proceed"
    COURSE_CORRECT = "course_correct"
    ESCALATE = "escalate"
    HALT = "halt"


# ── Request / Response models ─────────────────────────────────────────────────

class ScoreFactors(BaseModel):
    """The six scoring dimensions. Each value is clamped to [0.0, 1.0]."""

    relevance: float = Field(..., ge=0.0, le=1.0)
    accuracy: float = Field(..., ge=0.0, le=1.0)
    tool_success: float = Field(..., ge=0.0, le=1.0)
    latency_penalty: float = Field(..., ge=0.0, le=1.0)
    memory_utilization: float = Field(..., ge=0.0, le=1.0)
    validation_pass: float = Field(..., ge=0.0, le=1.0)


class EvaluateRequest(BaseModel):
    agent_id: int
    task_id: str
    context_type: str
    response_text: str
    used_knowledge: bool = False
    latency_ms: int = 0
    tool_calls: List[str] = Field(default_factory=list)
    # Optional: caller can supply pre-computed factors; if absent the service
    # derives them from the other fields.
    factors: Optional[ScoreFactors] = None


class BandResult(BaseModel):
    low: float
    high: float
    mean: float
    std: float
    n: int


class EvaluateResponse(BaseModel):
    score: float
    band: BandResult
    recommendation: Recommendation
    factors: Dict[str, float]
    weights_used: Dict[str, float]
    trace_id: str


class BandRequest(BaseModel):
    agent_id: int
    context_type: str


class FeedbackRequest(BaseModel):
    agent_id: int
    task_id: str
    session_id: str
    feedback_source: FeedbackSource
    feedback_type: FeedbackType
    score: float
    reward_signal: float
    context_type: str


class FeedbackResponse(BaseModel):
    accepted: bool
    trace_id: str


class WeightsResponse(BaseModel):
    agent_id: int
    weights: Dict[str, float]
    context_types: List[str]
