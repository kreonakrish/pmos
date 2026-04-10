"""Pydantic models for TaskNode and TaskGraph."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class NodeStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    CORRECTING = "CORRECTING"


class NodeType(str, Enum):
    ROOT = "ROOT"
    SUBTASK = "SUBTASK"
    VALIDATION = "VALIDATION"
    AGGREGATION = "AGGREGATION"
    CORRECTION = "CORRECTION"


class Criticality(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class GraphStatus(str, Enum):
    CONSTRUCTING = "CONSTRUCTING"
    EXECUTING = "EXECUTING"
    CORRECTING = "CORRECTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class TaskNode(BaseModel):
    node_id: str
    graph_id: str
    parent_id: Optional[str] = None
    description: str
    node_type: NodeType = NodeType.SUBTASK
    status: NodeStatus = NodeStatus.PENDING
    assigned_agent_id: Optional[str] = None
    fallback_agent_ids: List[str] = Field(default_factory=list)
    score: Optional[float] = None
    score_band_low: Optional[float] = None
    score_band_high: Optional[float] = None
    retry_count: int = 0
    max_retries: int = 3
    criticality: Criticality = Criticality.MEDIUM
    execution_time_ms: Optional[int] = None
    iteration: int = 0
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[str] = None


class TaskGraph(BaseModel):
    graph_id: str
    session_id: str
    user_request: str
    current_iteration: int = 0
    status: GraphStatus = GraphStatus.CONSTRUCTING
    nodes: List[TaskNode] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
