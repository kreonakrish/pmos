"""Pydantic models for pipeline request/response."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    conversation_id: str
    message: str
    team_id: str
    stream: bool = False
    agent_id: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    session_id: str
    conversation_id: str
    response: str
    graph_id: str
    score: Optional[float] = None
    trace_id: str
    steps: List[Dict[str, Any]] = Field(default_factory=list)

    # Phase F4 — clarification surface. When the translator flagged
    # ambiguity or zero-resolution, the chat response carries the follow-up
    # question and/or the auditor issue id for stewardship.
    clarification_needed: bool = False
    clarification_question: Optional[str] = None
    auditor_issue_id: Optional[str] = None
    auditor_issue_kind: Optional[str] = None

    # Charts (Ext2 + viz add-on) — populated when a deterministic Report
    # short-circuit fires. Each entry matches ``shared.visualization``'s
    # Visualization shape: {type, title, description, x_field, y_fields,
    # data, inferred_from, truncated_from}. Frontend renders these as
    # bar/line/pie/area/table cards under the markdown body.
    visualizations: List[Dict[str, Any]] = Field(default_factory=list)


class StreamChunk(BaseModel):
    type: str  # step | tool_call | score | course_correct | complete | error
    agent_name: str
    content: str
    score: Optional[float] = None
    trace_id: str
    timestamp: str


class SessionResponse(BaseModel):
    session_id: str
    graph_id: str
    status: str
    nodes: List[Dict[str, Any]] = Field(default_factory=list)
    trace_id: str


class HealthResponse(BaseModel):
    status: str
    neo4j: bool
    redis: bool
    service: str = "orchestrator"
