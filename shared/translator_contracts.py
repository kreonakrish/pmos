"""Shared contracts for the Translator service.

Imported by the Translator service itself (services/translator/) and by the
orchestrator's pipeline integration so both ends agree on the wire format.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Qdrant collection: translation_examples
# ---------------------------------------------------------------------------
TRANSLATION_EXAMPLES_COLLECTION = "translation_examples"

# Embedding dimension. Kept aligned with the rag service's default. If the
# translator uses a different embedder this must be overridden in its config.
TRANSLATION_EXAMPLES_DIM = 384

# Payload schema (purely descriptive — Qdrant payloads are schemaless):
#   question:           str    — original NL user question
#   canonical_entities: List[str]
#   relationships:      List[str]
#   dataset_bindings:   List[str]      — DataAsset.fq_name list
#   intent:             str
#   domain:             Optional[str]
#   decomposition:      List[str]      — domain sub-task descriptions
#   score:              float          — promotion score (1.0 = promoted)
#   promoted_by:        str            — user id
#   promoted_at:        str            — ISO datetime
#   trace_id:           str
TRANSLATION_EXAMPLE_PAYLOAD_KEYS = (
    "question",
    "canonical_entities",
    "relationships",
    "dataset_bindings",
    "intent",
    "domain",
    "decomposition",
    "score",
    "promoted_by",
    "promoted_at",
    "trace_id",
)


# ---------------------------------------------------------------------------
# HTTP wire format between orchestrator and translator
# ---------------------------------------------------------------------------


class TranslationTurn(TypedDict, total=False):
    """One turn in a multi-turn clarification dialog (Phase F7).

    ``role`` is either ``'user'`` or ``'translator'``. ``content`` is the
    natural-language text. ``trace_id`` and ``timestamp`` are optional
    bookkeeping fields the orchestrator stamps on each turn for replay.
    """
    role: str        # 'user' | 'translator'
    content: str     # NL text
    trace_id: str
    timestamp: str


class TranslationRequest(TypedDict, total=False):
    question: str
    team_id: str
    conversation_id: str
    trace_id: str
    # Phase F7 — multi-turn clarification dialog. Caller appends prior
    # user/translator turns so the pipeline can narrow on each round-trip.
    prior_turns: List[TranslationTurn]


class CanonicalEntity(TypedDict, total=False):
    name: str
    domain: Optional[str]
    fq_name: Optional[str]
    confidence: float


class DatasetBinding(TypedDict, total=False):
    asset_fq_name: str
    columns: List[str]
    source_uri: Optional[str]
    source_type: Optional[str]   # MYSQL, NEO4J, ...
    asset_type: Optional[str]    # TABLE / VIEW / NODE_LABEL / RELATIONSHIP


class ReportDataset(TypedDict, total=False):
    dataset_id: str
    name: str
    command: str          # SQL / MDX / DAX
    command_type: str     # 'SQL' | 'MDX' | 'DAX'
    source_uri: Optional[str]
    source_name: Optional[str]


class MatchedReport(TypedDict, total=False):
    """A deterministic Report (SSRS / Cognos / PowerBI / …) the translator
    decided is a strong match for the user's question. The orchestrator may
    bypass the agent loop and execute the report's command directly when
    confidence is high enough.
    """
    report_id: str
    name: str
    description: str
    system: str           # 'SSRS' | 'COGNOS' | 'POWERBI' | 'TABLEAU' | 'CUSTOM'
    owner_team: Optional[str]
    datasets: List[ReportDataset]
    uses_attributes: List[str]
    score: float          # heuristic 0..N (caller decides threshold)
    why: str              # short rationale shown in the UI


class TranslationResult(TypedDict, total=False):
    intent: str
    domain: Optional[str]
    canonical_entities: List[CanonicalEntity]
    relationships: List[Dict[str, Any]]
    dataset_bindings: List[DatasetBinding]
    domain_subtasks: List[str]
    used_ontology_subgraph: Dict[str, Any]
    ontology_versions: List[str]
    fallback_used: bool
    trace_id: str

    # Phase F4 — clarification / ambiguity gate.
    clarification_needed: bool
    clarification_question: Optional[str]
    ambiguous_options: List[Dict[str, Any]]
    auditor_issue_id: Optional[str]
    auditor_issue_kind: Optional[str]

    # Ext2 — deterministic report resolution. When present and the top
    # match has a high score, the orchestrator can execute its command
    # SQL directly against the bound DataSource without going through the
    # agent bid loop.
    matched_reports: List[MatchedReport]


def empty_translation_result(trace_id: str = "") -> TranslationResult:
    """Default-shaped result used when ontology returns nothing."""
    return TranslationResult(
        intent="unknown",
        domain=None,
        canonical_entities=[],
        relationships=[],
        dataset_bindings=[],
        domain_subtasks=[],
        used_ontology_subgraph={"nodes": [], "edges": []},
        ontology_versions=[],
        fallback_used=True,
        trace_id=trace_id,
        clarification_needed=False,
        clarification_question=None,
        ambiguous_options=[],
        auditor_issue_id=None,
        auditor_issue_kind=None,
        matched_reports=[],
    )
