"""Pydantic models for translator HTTP I/O.

These mirror the TypedDicts in ``shared/translator_contracts.py`` but with
runtime validation. Keep field names aligned with the contracts module so the
orchestrator can deserialize translator responses directly.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Translate request / response
# ---------------------------------------------------------------------------


class TranslationRequest(BaseModel):
    question: str = Field(..., min_length=1)
    team_id: Optional[str] = None
    conversation_id: Optional[str] = None
    trace_id: Optional[str] = None
    # Phase F7 — multi-turn clarification dialog. Each entry is a dict with
    # at least ``role`` ('user'|'translator') and ``content``. The pipeline
    # truncates to MAX_DIALOG_TURNS internally before LLM use.
    prior_turns: List[Dict[str, Any]] = Field(default_factory=list)


class CanonicalEntity(BaseModel):
    name: str
    domain: Optional[str] = None
    fq_name: Optional[str] = None
    confidence: float = 0.0


class DatasetBinding(BaseModel):
    asset_fq_name: str
    columns: List[str] = Field(default_factory=list)
    source_uri: Optional[str] = None
    source_type: Optional[str] = None  # MYSQL, NEO4J, ... lets the orchestrator pick the right query language
    asset_type: Optional[str] = None   # TABLE / VIEW / NODE_LABEL / RELATIONSHIP


class OntologySubgraph(BaseModel):
    nodes: List[Dict[str, Any]] = Field(default_factory=list)
    edges: List[Dict[str, Any]] = Field(default_factory=list)


class TranslationResponse(BaseModel):
    intent: str = "unknown"
    domain: Optional[str] = None
    canonical_entities: List[CanonicalEntity] = Field(default_factory=list)
    relationships: List[Dict[str, Any]] = Field(default_factory=list)
    dataset_bindings: List[DatasetBinding] = Field(default_factory=list)
    domain_subtasks: List[str] = Field(default_factory=list)
    used_ontology_subgraph: OntologySubgraph = Field(default_factory=OntologySubgraph)
    ontology_versions: List[str] = Field(default_factory=list)
    fallback_used: bool = True
    trace_id: str = ""

    # Phase F4 — clarification + ambiguity gate
    clarification_needed: bool = False
    clarification_question: Optional[str] = None
    ambiguous_options: List[Dict[str, Any]] = Field(default_factory=list)
    auditor_issue_id: Optional[str] = None
    auditor_issue_kind: Optional[str] = None

    # Ext2 — Report resolution. List of {report_id, name, description,
    # system, owner_team, datasets:[{dataset_id, name, command, command_type,
    # source_uri, source_name}], uses_attributes, score, why}.
    matched_reports: List[Dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Promote example request
# ---------------------------------------------------------------------------


class PromoteExampleRequest(BaseModel):
    question: str = Field(..., min_length=1)
    canonical_entities: List[Dict[str, Any]] = Field(default_factory=list)
    dataset_bindings: List[Dict[str, Any]] = Field(default_factory=list)
    decomposition: List[str] = Field(default_factory=list)
    intent: str = "unknown"
    domain: Optional[str] = None
    score: float = 1.0
    promoted_by: str
    trace_id: Optional[str] = None


class PromoteExampleResponse(BaseModel):
    status: str
    point_id: Optional[str] = None
    embedded: bool = False
    trace_id: str = ""


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str
    service: str = "translator"
    neo4j: bool = False
    qdrant: bool = False
    llm: bool = False
