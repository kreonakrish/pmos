"""Pydantic request/response models for the memory service."""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class MemoryTier(str, Enum):
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"
    REASONING = "reasoning"
    EPISODIC = "episodic"


class MemoryWriteRequest(BaseModel):
    agent_id: int
    tier: MemoryTier
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryWriteResponse(BaseModel):
    memory_id: str
    tier: MemoryTier
    trace_id: str


class MemoryRetrieveResponse(BaseModel):
    results: list[dict[str, Any]]
    tier: MemoryTier
    count: int
    trace_id: str


class PromptAssembleRequest(BaseModel):
    agent_id: int
    context: dict[str, Any] = Field(default_factory=dict)
    tiers: list[MemoryTier] = Field(
        default=[
            MemoryTier.SHORT_TERM,
            MemoryTier.LONG_TERM,
            MemoryTier.REASONING,
            MemoryTier.EPISODIC,
        ]
    )


class PromptSourceCounts(BaseModel):
    short_term_hits: int = 0
    long_term_hits: int = 0
    reasoning_hits: int = 0
    episodic_hits: int = 0


class PromptAssembleResponse(BaseModel):
    system_prompt: str
    sources: PromptSourceCounts
    trace_id: str


class EpisodeData(BaseModel):
    agent_id: int
    task_id: str
    task_description: str
    steps: list[dict[str, Any]] = Field(default_factory=list)
    output: str = ""
    score: float = 0.0
    outcome: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str = "1.0.0"
    checks: dict[str, str] = Field(default_factory=dict)
