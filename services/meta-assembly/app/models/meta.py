from typing import Any, Optional
from pydantic import BaseModel, Field


# ── Request / Response models ────────────────────────────────────────────────

class TaskContext(BaseModel):
    task_id: str
    task_type: str
    required_tools: list[str] = Field(default_factory=list)


class DetectGapRequest(BaseModel):
    task_context: TaskContext
    failed_agents: list[int] = Field(default_factory=list)
    failure_reasons: list[str] = Field(default_factory=list)


class DetectGapResponse(BaseModel):
    gap_description: str
    suggested_capability_type: str  # TOOL | SKILL | AGENT
    confidence: float
    trace_id: str


class GenerateSpecRequest(BaseModel):
    gap_description: str
    capability_type: str  # TOOL | SKILL | AGENT
    max_attempts: int = 3


class ValidationResult(BaseModel):
    syntax: bool
    dependencies: bool
    safety: bool


class GenerateSpecResponse(BaseModel):
    spec: dict[str, Any]
    validation_result: ValidationResult
    validation_score: float
    trace_id: str


class RegisterRequest(BaseModel):
    spec: dict[str, Any]
    gap_id: str
    validation_score: float


class RegisterResponse(BaseModel):
    capability_id: str
    capability_type: str
    registered: bool
    trace_id: str


# ── Internal domain models ───────────────────────────────────────────────────

class GapAnalysis(BaseModel):
    gap_description: str
    suggested_capability_type: str
    confidence: float


class CapabilitySpec(BaseModel):
    capability_type: str
    name: str
    description: str
    spec_json: dict[str, Any]


class SandboxResult(BaseModel):
    success: bool
    output: Optional[Any] = None
    error: Optional[str] = None
    duration_ms: int
