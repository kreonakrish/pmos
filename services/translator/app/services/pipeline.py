"""Translator pipeline (Phase C2).

Converts a natural-language user question into a structured business-domain
decomposition by walking an ontology Neo4j graph. The orchestrator calls this
before its own task decomposition step so subtasks are grounded in real
canonical entities and dataset bindings.

Stages (sequential, all soft-failing):
  1. NER + intent classification (single LLM call).
  2. Schema RAG over the ontology graph for candidate
     BusinessEntity / BusinessAttribute nodes.
  3. Entity Resolution: LLM picks the relevant subset.
  4. Dataset binding lookup: BusinessAttribute -> DataColumn -> DataAsset.
  5. Few-shot retrieval over Qdrant ``translation_examples``.
  6. Decomposition: LLM produces 1-5 business-domain subtasks.
  7. Used ontology subgraph assembly (for UI display).
  8. Ontology version collection.
  9. Result assembly with ``fallback_used`` derived from canonical-entity count.

Every LLM call is wrapped in try/except + asyncio.wait_for so the route layer
ALWAYS gets a TranslationResult — never an exception.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from shared.audit import get_audit
from shared.auditor_issues import raise_or_dedupe
from shared.translator_contracts import (
    TRANSLATION_EXAMPLE_PAYLOAD_KEYS,
    TranslationResult,
    empty_translation_result,
)

from app.adapters.embedder import Embedder
from app.adapters.llm_adapter import LLMAdapter
from app.adapters.neo4j_adapter import OntologyNeo4jAdapter
from app.adapters.qdrant_adapter import QdrantAdapter
from app.config import settings
from app.utils.logger import logger


# Lazy module-level audit singleton — translator's MySQL config is identical
# to the orchestrator's so we get audit_events writes from any service that
# imports shared.audit.
_audit = get_audit(settings)


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

# Soft timeout per LLM call. The wrapping LLMAdapter has its own httpx timeout
# of 60-120s; this is an additional asyncio-level guard so a stuck provider
# can't wedge a translate() call.
LLM_SOFT_TIMEOUT_SEC: float = 20.0

# Cap the number of ontology candidates we feed back to the LLM. Keeps the
# resolution prompt within budget when a span matches lots of nodes.
MAX_CANDIDATES: int = 30

# Few-shot retrieval knobs.
FEWSHOT_K: int = 3
FEWSHOT_SCORE_THRESHOLD: float = 0.7

# Phase F7 — multi-turn clarification dialog.
# Hard cap on dialog turns we accept before forcing a non-clarifying answer.
# When prior_turns reaches this length the pipeline returns its best guess
# with ``clarification_needed=False`` and raises a NO_RESOLUTION auditor
# issue titled "Multi-turn dialog exhausted" so a steward can intervene.
MAX_DIALOG_TURNS: int = 4

# Cap how many prior turns we feed the LLM in any single prompt. Prevents
# token-budget explosions on long dialogs while still preserving recent
# context. Older turns get truncated; the most recent N stay.
MAX_PRIOR_TURNS_IN_PROMPT: int = 6

# Allowed intents from the NER+intent step. Anything outside this collapses
# to ``freeform_qna`` so downstream consumers see a stable enum.
_VALID_INTENTS = {
    "metric_lookup",
    "trend_analysis",
    "comparison",
    "lineage",
    "freeform_qna",
}


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


def _safe_parse_json(raw: str) -> Optional[Any]:
    """Try hard to parse a JSON value out of an LLM response.

    Many providers wrap JSON in ```json fences``` or pad it with prose. We try
    a strict parse first, then fall back to extracting the largest object/array
    region. Returns None on total failure — callers must handle that.
    """
    if not raw:
        return None
    raw = raw.strip()
    # Strip code fences if present.
    if raw.startswith("```"):
        # remove first fence line
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        if raw.endswith("```"):
            raw = raw[: -3]
        raw = raw.strip()
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        pass
    # Try object then array.
    for pattern in (_JSON_OBJECT_RE, _JSON_ARRAY_RE):
        m = pattern.search(raw)
        if m:
            try:
                return json.loads(m.group(0))
            except (json.JSONDecodeError, ValueError):
                continue
    return None


# ---------------------------------------------------------------------------
# Phase F7 — dialog helpers
# ---------------------------------------------------------------------------


def _truncate_prior_turns(
    prior_turns: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Return at most the last MAX_PRIOR_TURNS_IN_PROMPT turns. Defensive about
    None and bad shapes — entries missing ``role`` or ``content`` are dropped.
    """
    if not prior_turns:
        return []
    cleaned: List[Dict[str, Any]] = []
    for t in prior_turns:
        if not isinstance(t, dict):
            continue
        role = str(t.get("role") or "").strip().lower()
        content = str(t.get("content") or "").strip()
        if not role or not content:
            continue
        if role not in ("user", "translator"):
            # Coerce unknown speakers — treat anything assistant-shaped as
            # translator, anything else as user, so prompts stay coherent.
            role = "translator" if role in ("assistant", "system", "bot") else "user"
        cleaned.append({"role": role, "content": content})
    # Keep only the most recent N — a dialog can blow past the budget.
    if len(cleaned) > MAX_PRIOR_TURNS_IN_PROMPT:
        cleaned = cleaned[-MAX_PRIOR_TURNS_IN_PROMPT:]
    return cleaned


def _dialog_chat_messages(prior_turns: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Render prior_turns as alternating user/assistant messages plus a
    leading system message. Used as a prefix to the per-step LLM prompt so
    the model sees the clarification context exactly once.
    """
    if not prior_turns:
        return []
    out: List[Dict[str, str]] = [
        {
            "role": "system",
            "content": (
                "Earlier in this dialog the user clarified their question. "
                "Use these prior turns to disambiguate and narrow your answer."
            ),
        }
    ]
    for t in prior_turns:
        role = "assistant" if t.get("role") == "translator" else "user"
        out.append({"role": role, "content": str(t.get("content") or "")})
    return out


def _flatten_user_clarifications(prior_turns: List[Dict[str, Any]]) -> str:
    """Concatenate every ``role='user'`` content into one string. Used by
    schema-RAG span expansion — clarifying tokens the user mentioned (e.g.
    'origination subdomain') should feed Schema RAG too."""
    parts: List[str] = []
    for t in prior_turns:
        if (t.get("role") or "").lower() == "user":
            c = str(t.get("content") or "").strip()
            if c:
                parts.append(c)
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class TranslatorPipeline:
    """Coordinates ontology lookup, vector recall, LLM grounding, and result assembly."""

    def __init__(
        self,
        neo4j: OntologyNeo4jAdapter,
        qdrant: QdrantAdapter,
        llm: LLMAdapter,
        embedder: Embedder,
    ) -> None:
        self.neo4j = neo4j
        self.qdrant = qdrant
        self.llm = llm
        self.embedder = embedder

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def translate(
        self,
        question: str,
        team_id: str = "",
        conversation_id: str = "",
        trace_id: str = "",
        prior_turns: Optional[List[Dict[str, Any]]] = None,
    ) -> TranslationResult:
        """Run the full translator pipeline. Never raises.

        Phase F7: ``prior_turns`` carries earlier user/translator clarification
        round-trips. The pipeline uses them to (a) disambiguate the LLM steps
        (NER+intent, entity-resolution, decomposition) and (b) compute
        ``dialog_turn`` for logs/audits. After ``MAX_DIALOG_TURNS`` rounds the
        pipeline forces a non-clarifying answer with an auditor issue.
        """
        # ``dialog_turn`` is 1-indexed: the FIRST request the user sends has
        # zero prior turns and is dialog_turn=1; each clarification reply
        # increments it. Two-entries (user-q + translator-clar) form one
        # round-trip, so dialog_turn = 1 + (n_prior_turns // 2). We compute
        # this against the ORIGINAL (untruncated) prior_turns length so the
        # cap is determined by the actual dialog length rather than the
        # prompt-budget truncation.
        n_raw_prior = len(prior_turns or [])
        prior_turns = _truncate_prior_turns(prior_turns)
        dialog_turn = 1 + (n_raw_prior // 2)
        # Dialog exhausted when the user has already used MAX_DIALOG_TURNS
        # round-trips (i.e. >= MAX_DIALOG_TURNS*2 turn entries) — this turn
        # must produce an answer instead of yet another clarification.
        dialog_exhausted = (
            dialog_turn > MAX_DIALOG_TURNS
            or n_raw_prior >= MAX_DIALOG_TURNS * 2
        )

        logger.info(
            "Translate started",
            layer="service",
            trace_id=trace_id,
            team_id=team_id,
            conversation_id=conversation_id,
            question_len=len(question),
            dialog_turn=dialog_turn,
            n_prior_turns=len(prior_turns),
        )

        # Audit: translate start
        try:
            await _audit.write(
                trace_id=trace_id,
                actor="translator",
                actor_type="SERVICE",
                action="translator.start",
                resource_type="Conversation",
                resource_id=conversation_id or None,
                payload={
                    "team_id": team_id,
                    "question_len": len(question or ""),
                    "dialog_turn": dialog_turn,
                    "n_prior_turns": len(prior_turns),
                },
            )
        except Exception:
            pass

        if not question or not question.strip():
            logger.warning(
                "Empty question — returning fallback",
                layer="service",
                trace_id=trace_id,
            )
            empty_res = empty_translation_result(trace_id=trace_id)
            try:
                await _audit.write(
                    trace_id=trace_id,
                    actor="translator",
                    actor_type="SERVICE",
                    action="translator.done",
                    resource_type="Conversation",
                    resource_id=conversation_id or None,
                    payload={
                        "intent": empty_res.get("intent"),
                        "canonical_entity_count": 0,
                        "fallback_used": True,
                        "reason": "empty_question",
                    },
                )
            except Exception:
                pass
            return empty_res

        # Catalog/column broadcast short-circuit. Two related question
        # patterns must skip the ontology pipeline:
        #   * "how many tables have loan_id columns"  (catalog SHAPE)
        #   * "value of loan_id across these tables"  (data SAMPLING)
        # Both fail the same way under the ontology path: span "loan_id"
        # tokenises to "loan", every `Servicing.Loan.*` BA matches, the
        # synonym detector clusters by suffix, and the user gets a
        # confused clarification while the DB/GRAPH agents — the only
        # ones who can introspect or sample real catalogs — never run.
        # Hand off to the orchestrator's broadcast path with the right
        # intent so it can pick the matching SQL/Cypher plan.
        column_kind, schema_meta_column = self._detect_column_question(question)
        if column_kind:
            broadcast_intent = f"{column_kind}_question"  # schema_meta_question | column_value_question
            logger.info(
                "Broadcast question detected — short-circuiting ontology pipeline",
                layer="service",
                trace_id=trace_id,
                kind=column_kind,
                column=schema_meta_column,
                question_len=len(question),
            )
            sm_res = empty_translation_result(trace_id=trace_id)
            sm_res["intent"] = broadcast_intent
            sm_res["fallback_used"] = True
            sm_res["clarification_needed"] = False
            sm_res["clarification_question"] = None
            sm_res["schema_meta_column"] = schema_meta_column or ""
            sm_res["schema_meta_question"] = question
            try:
                await _audit.write(
                    trace_id=trace_id,
                    actor="translator",
                    actor_type="SERVICE",
                    action="translator.done",
                    resource_type="Conversation",
                    resource_id=conversation_id or None,
                    payload={
                        "intent": broadcast_intent,
                        "schema_meta_column": schema_meta_column,
                        "fallback_used": True,
                        "reason": f"{column_kind}_short_circuit",
                        "dialog_turn": dialog_turn,
                    },
                )
            except Exception:
                pass
            return sm_res

        # 1. NER + Intent — prior_turns prepended as dialog history.
        intent, spans = await self._step1_ner_intent(
            question, trace_id=trace_id, prior_turns=prior_turns
        )

        # F7 — fold any noun-y tokens the user mentioned in clarifications
        # into the span list so Schema-RAG matches them too. We append the
        # clarification text as one extra "span" — _expand_spans_to_tokens
        # tokenizes/dedupes downstream.
        clar_text = _flatten_user_clarifications(prior_turns)
        rag_spans = list(spans)
        if clar_text:
            rag_spans.append(clar_text)

        # 2. Schema RAG over ontology
        try:
            candidate_entities, candidate_attributes = await self._step2_schema_rag(
                rag_spans, trace_id=trace_id
            )
        except Exception as exc:
            logger.error(
                "Schema RAG failed — returning fallback",
                layer="service",
                trace_id=trace_id,
                error=str(exc),
            )
            try:
                await _audit.write(
                    trace_id=trace_id,
                    actor="translator",
                    actor_type="SERVICE",
                    action="translator.error",
                    severity="ERROR",
                    resource_type="Conversation",
                    resource_id=conversation_id or None,
                    payload={"error": str(exc)[:500], "stage": "schema_rag"},
                )
            except Exception:
                pass
            fb = self._fallback_result(intent=intent, trace_id=trace_id)
            try:
                await _audit.write(
                    trace_id=trace_id,
                    actor="translator",
                    actor_type="SERVICE",
                    action="translator.done",
                    resource_type="Conversation",
                    resource_id=conversation_id or None,
                    payload={
                        "intent": fb.get("intent"),
                        "canonical_entity_count": 0,
                        "fallback_used": True,
                        "reason": "schema_rag_failed",
                    },
                )
            except Exception:
                pass
            return fb

        candidates = self._merge_candidates(candidate_entities, candidate_attributes)

        if not candidates:
            logger.info(
                "No ontology candidates matched — returning clarification fallback",
                layer="service",
                trace_id=trace_id,
                intent=intent,
                spans=spans,
                dialog_turn=dialog_turn,
            )
            fb = self._fallback_result(intent=intent, trace_id=trace_id)
            # F7 — multi-turn gate. If we've exhausted the dialog, surrender
            # quietly with an auditor issue. Otherwise ask a narrowing
            # clarification question and let the caller continue the loop.
            if dialog_exhausted:
                exhausted_id = raise_or_dedupe(
                    kind="NO_RESOLUTION",
                    title="Multi-turn dialog exhausted",
                    description=(
                        f"The translator ran the full {MAX_DIALOG_TURNS}-turn "
                        "clarification dialog without matching any ontology "
                        "concept. A Data Steward should review the user's "
                        "intent and either rephrase the question with the "
                        "user or extend the ontology / synonym graph."
                    ),
                    severity="WARN",
                    resource_type="UserQuestion",
                    resource_id=(question or "")[:255],
                    payload={
                        "question": question,
                        "intent": intent,
                        "spans": spans,
                        "prior_turns": prior_turns,
                        "dialog_turn": dialog_turn,
                    },
                    raised_by="translator",
                    raised_trace=trace_id,
                    settings=settings,
                )
                fb["clarification_needed"] = False
                fb["clarification_question"] = None
                fb["auditor_issue_id"] = exhausted_id
                fb["auditor_issue_kind"] = "NO_RESOLUTION"
            else:
                clar_q = self._build_narrowing_question(
                    prior_turns=prior_turns,
                    canonical_entities=[],
                    synonym_clusters=[],
                    dialog_turn=dialog_turn,
                )
                no_res_id = raise_or_dedupe(
                    kind="NO_RESOLUTION",
                    title=f"Could not resolve question: {question[:120]}",
                    description=(
                        "The translator could not match the user's question "
                        "to any ontology concept."
                    ),
                    severity="WARN",
                    resource_type="UserQuestion",
                    resource_id=(question or "")[:255],
                    payload={
                        "question": question,
                        "intent": intent,
                        "spans": spans,
                        "dialog_turn": dialog_turn,
                        "n_prior_turns": len(prior_turns),
                    },
                    raised_by="translator",
                    raised_trace=trace_id,
                    settings=settings,
                )
                fb["clarification_needed"] = True
                fb["clarification_question"] = clar_q
                fb["auditor_issue_id"] = no_res_id
                fb["auditor_issue_kind"] = "NO_RESOLUTION"

            try:
                await _audit.write(
                    trace_id=trace_id,
                    actor="translator",
                    actor_type="SERVICE",
                    action="translator.done",
                    resource_type="Conversation",
                    resource_id=conversation_id or None,
                    payload={
                        "intent": fb.get("intent"),
                        "canonical_entity_count": 0,
                        "fallback_used": True,
                        "reason": "no_candidates",
                        "dialog_turn": dialog_turn,
                        "n_prior_turns": len(prior_turns),
                        "clarification_needed": fb.get("clarification_needed"),
                    },
                )
            except Exception:
                pass
            return fb

        # 3. Entity Resolution
        canonical_entities, relationships = await self._step3_entity_resolution(
            question=question,
            candidates=candidates,
            trace_id=trace_id,
            prior_turns=prior_turns,
        )

        # 3b. F2 — augment canonical_entities with any attribute-level
        # candidates from the schema-RAG that the resolver didn't explicitly
        # pick. The LLM resolver favors entity-level matches, but direct
        # attribute hits (e.g. "income" → `borrower_annual_income`) carry the
        # most specific binding info and should never be silently dropped.
        already_in = {
            (str(ce.get("name") or ""), str(ce.get("fq_name") or ""))
            for ce in canonical_entities
        }
        passthrough_count = 0
        for ac in candidate_attributes:
            fq = ac.get("fq_name")
            if not fq:
                continue
            key = (str(ac.get("name") or ""), str(fq))
            if key in already_in:
                continue
            canonical_entities.append({
                "name": ac.get("name"),
                "domain": ac.get("domain"),
                "fq_name": fq,
                "confidence": 0.7,  # implied (not LLM-picked, RAG hit)
                "source": "schema_rag_passthrough",
            })
            already_in.add(key)
            passthrough_count += 1
        if passthrough_count:
            logger.info(
                "Attribute-level RAG passthrough",
                layer="service",
                trace_id=trace_id,
                passthrough=passthrough_count,
                total_canonical=len(canonical_entities),
            )

        # 4. Dataset bindings
        dataset_bindings, ontology_versions, binding_rows = await self._step4_dataset_bindings(
            canonical_entities=canonical_entities,
            trace_id=trace_id,
        )

        # 5. Few-shot retrieval
        fewshot_examples = await self._step5_fewshot(question, trace_id=trace_id)

        # 6. Decomposition
        domain = self._best_domain(canonical_entities)
        domain_subtasks = await self._step6_decomposition(
            question=question,
            intent=intent,
            domain=domain,
            canonical_entities=canonical_entities,
            dataset_bindings=dataset_bindings,
            fewshot_examples=fewshot_examples,
            trace_id=trace_id,
            prior_turns=prior_turns,
        )

        # F8 — explicit routing hints. When the user names a file (.docx,
        # .pdf, ...), a specific table ("foreclosures table"), the graph
        # explicitly ("home lending graph", "neo4j"), or a record id (L0009),
        # the question is precise enough that the report-match and
        # synonym-narrowing short-circuits do more harm than good — they
        # bounce the user through clarification loops while a capable agent
        # never gets to run. Bypass both gates so the agent loop runs and
        # picks the right tool from the team's catalog.
        routing_hints = self._detect_explicit_routing_hints(question)

        # Ext2 — Report resolution. Walk the (:Report) nodes in the ontology
        # graph, score each against the question + canonical entities + any
        # team mention. The orchestrator decides whether to run the command
        # directly (high-confidence single match) or just surface as context.
        if routing_hints:
            matched_reports = []
            logger.info(
                "Skipping report resolution due to explicit routing hints",
                layer="service",
                trace_id=trace_id,
                hints=routing_hints,
            )
        else:
            matched_reports = await self._step6b_report_resolution(
                question=question,
                spans=spans,
                canonical_entities=canonical_entities,
                prior_turns=prior_turns,
                trace_id=trace_id,
            )

        # 7. Used ontology subgraph
        used_subgraph = self._step7_used_subgraph(
            canonical_entities=canonical_entities,
            binding_rows=binding_rows,
        )

        fallback_used = len(canonical_entities) == 0

        # F4 — synonym detection / clarification gate.
        clarification_needed = False
        clarification_question: Optional[str] = None
        ambiguous_options: List[Dict[str, Any]] = []
        auditor_issue_id: Optional[str] = None
        auditor_issue_kind: Optional[str] = None

        synonym_clusters = self._detect_synonym_clusters(canonical_entities)
        if synonym_clusters:
            # Surface to auditor for review; do NOT block the user — both
            # synonyms can answer the question, just not as a single canonical
            # binding. Idempotent: same cluster surfacing repeatedly dedupes
            # against the OPEN issue.
            cluster_strs = [", ".join(c) for c in synonym_clusters]
            title = f"Synonym candidates: {cluster_strs[0][:200]}"
            auditor_issue_id = raise_or_dedupe(
                kind="SYNONYM_AMBIGUITY",
                title=title,
                description=(
                    "The translator surfaced multiple BusinessAttributes that "
                    "appear to mean the same thing. A Data Steward should "
                    "review and merge them via the Synonym Review tab."
                ),
                severity="WARN",
                resource_type="BusinessAttributeCluster",
                resource_id=cluster_strs[0][:255],
                payload={
                    "clusters": synonym_clusters,
                    "question": question,
                    "intent": intent,
                    "domain": domain,
                },
                raised_by="translator",
                raised_trace=trace_id,
                settings=settings,
            )
            auditor_issue_kind = "SYNONYM_AMBIGUITY"
            ambiguous_options = [{"cluster": c} for c in synonym_clusters]

        # F7 — multi-turn ambiguity gate. The pipeline is "still ambiguous"
        # when EITHER (a) we couldn't bind to physical columns OR (b) we
        # surfaced multiple SYNONYM clusters. In those cases we try to
        # generate a NARROWER clarification question (using prior_turns and
        # any concrete options/clusters we found this round) — unless the
        # dialog has run out of turns, in which case we surrender, return
        # the best-guess result with clarification_needed=False, and raise
        # an auditor issue titled "Multi-turn dialog exhausted".
        still_ambiguous = (not dataset_bindings) or bool(synonym_clusters)

        if still_ambiguous and dialog_exhausted:
            exhausted_id = raise_or_dedupe(
                kind="NO_RESOLUTION",
                title="Multi-turn dialog exhausted",
                description=(
                    f"The translator ran the full {MAX_DIALOG_TURNS}-turn "
                    "clarification dialog without resolving the question to "
                    "concrete physical bindings. A Data Steward should review "
                    "the conversation and either map the missing concepts or "
                    "extend the synonym graph."
                ),
                severity="WARN",
                resource_type="UserQuestion",
                resource_id=(question or "")[:255],
                payload={
                    "question": question,
                    "intent": intent,
                    "domain": domain,
                    "canonical_entities": canonical_entities,
                    "spans": spans,
                    "prior_turns": prior_turns,
                    "dialog_turn": dialog_turn,
                },
                raised_by="translator",
                raised_trace=trace_id,
                settings=settings,
            )
            auditor_issue_id = exhausted_id
            auditor_issue_kind = "NO_RESOLUTION"
            clarification_needed = False
            clarification_question = None
            logger.info(
                "Multi-turn dialog exhausted — returning best-guess",
                layer="service",
                trace_id=trace_id,
                dialog_turn=dialog_turn,
                auditor_issue_id=auditor_issue_id,
            )

        elif not dataset_bindings:
            # NO_RESOLUTION — either the user asked about something the
            # ontology can't see, or matched entities have no MAPS_TO yet.
            # Ask the user for help and raise an issue for the auditor.
            issue_kind = "NO_RESOLUTION"
            if canonical_entities:
                title = (
                    f"No physical bindings: "
                    f"{', '.join(str(c.get('name') or c.get('fq_name')) for c in canonical_entities[:3])}"
                )
                description = (
                    "The translator matched ontology concepts but none of "
                    "them have live MAPS_TO edges to physical columns. "
                    "Likely a Data Steward hasn't mapped these yet."
                )
                clarification_question = None  # System gap, not user gap.
            else:
                title = f"Could not resolve question: {question[:120]}"
                description = (
                    "The translator could not match the user's question to "
                    "any ontology concept."
                )
                # If the user gave explicit hints (a table, file, graph
                # mention, or record id), let the agent loop run instead of
                # asking the user to rephrase — the agent has direct tool
                # access and the hint is already actionable.
                if routing_hints:
                    clarification_question = None
                    clarification_needed = False
                else:
                    clarification_question = self._build_narrowing_question(
                        prior_turns=prior_turns,
                        canonical_entities=canonical_entities,
                        synonym_clusters=synonym_clusters,
                        dialog_turn=dialog_turn,
                    )
                    clarification_needed = True

            no_res_id = raise_or_dedupe(
                kind=issue_kind,
                title=title,
                description=description,
                severity="WARN",
                resource_type="UserQuestion",
                resource_id=(question or "")[:255],
                payload={
                    "question": question,
                    "intent": intent,
                    "domain": domain,
                    "canonical_entities": canonical_entities,
                    "spans": spans,
                    "dialog_turn": dialog_turn,
                    "n_prior_turns": len(prior_turns),
                },
                raised_by="translator",
                raised_trace=trace_id,
                settings=settings,
            )
            # If we already raised a SYNONYM_AMBIGUITY above, prefer the
            # NO_RESOLUTION id since it's the one blocking the user — but
            # only when there are zero entities matched (fully stuck).
            if not auditor_issue_id or not canonical_entities:
                auditor_issue_id = no_res_id
                auditor_issue_kind = issue_kind

        elif synonym_clusters:
            # We have bindings AND multiple synonym clusters. Ask once;
            # after the user has acknowledged (named a member OR said
            # "both"/"compare"/"either"), stop asking and let the answer
            # flow with both bindings — the auditor issue stays OPEN for
            # the steward to merge.
            user_text = " ".join(
                str(t.get("content") or "")
                for t in (prior_turns or [])
                if (t.get("role") or "").lower() == "user"
            ).lower()
            ack_keywords = (" both ", "side by side", "compare", "either",
                            " all ", " every ")
            user_acked = any(k in f" {user_text} " for k in ack_keywords)
            if not user_acked:
                for member in synonym_clusters[0]:
                    ml = member.lower()
                    if ml in user_text or ml.rsplit(".", 1)[-1] in user_text:
                        user_acked = True
                        break
            # Explicit routing hints (a specific table, file, graph mention,
            # or record id) over-ride synonym narrowing — the user's question
            # is precise; bouncing them through "Among ... which one?" just
            # blocks the agent loop. Auditor issue stays raised above.
            if routing_hints:
                clarification_needed = False
                clarification_question = None
            elif user_acked:
                clarification_needed = False
                clarification_question = None
            else:
                clarification_question = self._build_narrowing_question(
                    prior_turns=prior_turns,
                    canonical_entities=canonical_entities,
                    synonym_clusters=synonym_clusters,
                    dialog_turn=dialog_turn,
                )
                clarification_needed = bool(clarification_question)

        result: TranslationResult = TranslationResult(
            intent=intent,
            domain=domain,
            canonical_entities=canonical_entities,
            relationships=relationships,
            dataset_bindings=dataset_bindings,
            domain_subtasks=domain_subtasks,
            used_ontology_subgraph=used_subgraph,
            ontology_versions=ontology_versions,
            fallback_used=fallback_used,
            trace_id=trace_id,
            clarification_needed=clarification_needed,
            clarification_question=clarification_question,
            ambiguous_options=ambiguous_options,
            auditor_issue_id=auditor_issue_id,
            auditor_issue_kind=auditor_issue_kind,
            matched_reports=matched_reports,
        )

        logger.info(
            "Translate completed",
            layer="service",
            trace_id=trace_id,
            intent=intent,
            domain=domain,
            n_canonical=len(canonical_entities),
            n_bindings=len(dataset_bindings),
            n_subtasks=len(domain_subtasks),
            fallback_used=fallback_used,
            clarification_needed=clarification_needed,
            auditor_issue_id=auditor_issue_id,
            dialog_turn=dialog_turn,
            n_prior_turns=len(prior_turns),
        )

        # Audit: translate done
        try:
            await _audit.write(
                trace_id=trace_id,
                actor="translator",
                actor_type="SERVICE",
                action="translator.done",
                resource_type="Conversation",
                resource_id=conversation_id or None,
                payload={
                    "intent": intent,
                    "canonical_entity_count": len(canonical_entities),
                    "fallback_used": fallback_used,
                    "domain": domain,
                    "n_dataset_bindings": len(dataset_bindings),
                    "n_subtasks": len(domain_subtasks),
                    "dialog_turn": dialog_turn,
                    "n_prior_turns": len(prior_turns),
                    "clarification_needed": clarification_needed,
                },
            )
        except Exception:
            pass

        return result

    # ------------------------------------------------------------------
    # promote_example (pipeline-level)
    # ------------------------------------------------------------------

    async def promote_example(
        self,
        question: str,
        canonical_entities: list,
        dataset_bindings: list,
        decomposition: list,
        intent: str,
        domain: Optional[str],
        score: float,
        promoted_by: str,
        trace_id: str = "",
    ) -> Dict[str, Any]:
        """Embed the question, build a payload, and upsert to Qdrant.

        Returns a status dict — never raises. If the embedder is unavailable
        the upsert is skipped and the response carries
        ``status="skipped_no_embedder"``.
        """
        logger.info(
            "Promote example started",
            layer="service",
            trace_id=trace_id,
            promoted_by=promoted_by,
            intent=intent,
            domain=domain,
        )

        # Audit: promote_example
        try:
            await _audit.write(
                trace_id=trace_id,
                actor=promoted_by or "system",
                actor_type="USER" if promoted_by else "SYSTEM",
                action="translator.promote_example",
                payload={
                    "intent": intent,
                    "domain": domain,
                    "score": score,
                    "n_canonical_entities": len(canonical_entities or []),
                    "n_dataset_bindings": len(dataset_bindings or []),
                },
            )
        except Exception:
            pass

        if not self.embedder.available():
            logger.warning(
                "Embedder unavailable — skipping promote_example upsert",
                layer="service",
                trace_id=trace_id,
            )
            return {
                "status": "skipped_no_embedder",
                "point_id": None,
                "embedded": False,
                "trace_id": trace_id,
            }

        full_payload = {
            "question": question,
            "canonical_entities": canonical_entities,
            "relationships": [],
            "dataset_bindings": dataset_bindings,
            "intent": intent,
            "domain": domain,
            "decomposition": decomposition,
            "score": score,
            "promoted_by": promoted_by,
            "promoted_at": datetime.now(timezone.utc).isoformat(),
            "trace_id": trace_id,
        }
        # Constrain the upsert payload to declared keys so accidental extra
        # fields don't sneak into the vector store.
        payload = {k: full_payload[k] for k in TRANSLATION_EXAMPLE_PAYLOAD_KEYS if k in full_payload}

        point_id = str(uuid.uuid4())
        try:
            vector = await self.embedder.embed(question)
            await self.qdrant.upsert_example(
                point_id=point_id,
                vector=vector,
                payload=payload,
                trace_id=trace_id,
            )
        except Exception as exc:
            logger.error(
                "Promote example upsert failed",
                layer="service",
                trace_id=trace_id,
                error=str(exc),
            )
            return {
                "status": "error",
                "point_id": None,
                "embedded": False,
                "trace_id": trace_id,
                "error": str(exc),
            }

        logger.info(
            "Promote example upserted",
            layer="service",
            trace_id=trace_id,
            point_id=point_id,
        )
        return {
            "status": "ok",
            "point_id": point_id,
            "embedded": True,
            "trace_id": trace_id,
        }

    # ------------------------------------------------------------------
    # Step 1: NER + Intent
    # ------------------------------------------------------------------

    async def _step1_ner_intent(
        self,
        question: str,
        trace_id: str,
        prior_turns: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[str, List[str]]:
        """One LLM call returns both intent and entity spans.

        On any failure we fall back to ``intent='freeform_qna'`` and naive
        whitespace-split spans so the rest of the pipeline still has something
        to work with.

        Phase F7: ``prior_turns`` (truncated to MAX_PRIOR_TURNS_IN_PROMPT) are
        prepended as alternating user/assistant messages so the model can see
        the dialog history when extracting spans / picking intent.
        """
        prior_turns = prior_turns or []
        system = (
            "You are extracting entities and classifying the intent of a user's "
            "natural-language question about a business domain. Return strict JSON."
        )
        user_template = (
            "Question: {q}\n\n"
            "Return JSON of the form:\n"
            '  {{"intent": "metric_lookup|trend_analysis|comparison|lineage|freeform_qna", '
            '"spans": ["..."]}}\n\n'
            "Spans should be the noun phrases / time references / metric names / "
            "qualifiers that a downstream system should look up. No prose, JSON only."
        ).format(q=question)

        # Build messages: optional dialog prefix → system → user.
        messages: List[Dict[str, str]] = list(_dialog_chat_messages(prior_turns))
        messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user_template})

        try:
            raw = await asyncio.wait_for(
                self.llm.complete(
                    messages=messages,
                    trace_id=trace_id,
                ),
                timeout=LLM_SOFT_TIMEOUT_SEC,
            )
            parsed = _safe_parse_json(raw)
            if isinstance(parsed, dict):
                intent_raw = str(parsed.get("intent") or "freeform_qna").strip().lower()
                intent = intent_raw if intent_raw in _VALID_INTENTS else "freeform_qna"
                spans_raw = parsed.get("spans") or []
                spans = [str(s).strip() for s in spans_raw if str(s).strip()]
                if not spans:
                    spans = question.split()
                logger.info(
                    "NER+intent parsed",
                    layer="service",
                    trace_id=trace_id,
                    intent=intent,
                    n_spans=len(spans),
                )
                return intent, spans
            logger.warning(
                "NER+intent JSON unparseable — using fallback",
                layer="service",
                trace_id=trace_id,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "NER+intent LLM call timed out — using fallback",
                layer="service",
                trace_id=trace_id,
            )
        except Exception as exc:
            logger.warning(
                "NER+intent LLM call failed — using fallback",
                layer="service",
                trace_id=trace_id,
                error=str(exc),
            )
        return "freeform_qna", question.split()

    # ------------------------------------------------------------------
    # Step 2: Schema RAG over the ontology
    # ------------------------------------------------------------------

    # F4 — token expansion for schema-RAG. Substring matching on full spans
    # misses physical names with underscores (`annual_household_income`)
    # because the NL phrase "household income" doesn't substring-match the
    # underscored form. We expand each span into its individual tokens and
    # match those too. Stop tokens are dropped to keep noise out.
    _RAG_STOP_TOKENS = frozenset({
        "a", "an", "the", "of", "for", "to", "in", "on", "by", "and", "or",
        "is", "was", "are", "be", "been", "vs", "across", "with",
        "what", "how", "why", "when", "where", "which",
        "show", "me", "give", "find", "list", "get",
        "average", "yearly", "annual",
    })

    @classmethod
    def _expand_spans_to_tokens(cls, spans: List[str]) -> List[str]:
        """Return the original spans plus every meaningful single-word token
        within them (deduplicated, lowercased). Used to broaden RAG match
        coverage without losing the verbatim phrase signal."""
        out: List[str] = []
        seen: set = set()
        for s in spans:
            if not s:
                continue
            for piece in [s] + re.split(r"[\s_\.\-]+", s):
                t = piece.strip().lower()
                if not t or len(t) < 3 or t in cls._RAG_STOP_TOKENS:
                    continue
                if t in seen:
                    continue
                seen.add(t)
                out.append(t)
        return out

    async def _step2_schema_rag(
        self, spans: List[str], trace_id: str
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Run the candidate-lookup query for the spans.

        Returns ``(entity_candidates, attribute_candidates)`` deduplicated.
        """
        if not spans:
            return [], []
        spans = self._expand_spans_to_tokens(spans)
        if not spans:
            return [], []

        # Match in BOTH directions — the LLM may emit a short token ("loan")
        # or a long phrase ("loans currently in default"). Either the entity
        # name is contained in the span (phrase case) or the span is in the
        # entity name (substring case).
        #
        # F1 hygiene: only return BusinessEntity nodes that actually have at
        # least one HAS_ATTRIBUTE outgoing edge. Orphan entities (no
        # attributes) would otherwise win a span match by name alone and
        # produce zero bindings downstream.
        cypher = (
            "UNWIND $spans AS span "
            "OPTIONAL MATCH (e:BusinessEntity) "
            "WHERE (toLower(span) CONTAINS toLower(e.name) "
            "       OR toLower(e.name) CONTAINS toLower(span)) "
            "  AND exists((e)-[:HAS_ATTRIBUTE]->()) "
            "OPTIONAL MATCH (ba:BusinessAttribute) "
            "WHERE toLower(span) CONTAINS toLower(ba.name) "
            "   OR toLower(ba.name) CONTAINS toLower(span) "
            "   OR toLower(ba.fq_name) CONTAINS toLower(span) "
            "OPTIONAL MATCH (d:BusinessDomain)-[:HAS_ENTITY]->(e) "
            "OPTIONAL MATCH (e2:BusinessEntity)-[:HAS_ATTRIBUTE]->(ba) "
            "OPTIONAL MATCH (d2:BusinessDomain)-[:HAS_ENTITY]->(e2) "
            "RETURN span, "
            "       collect(DISTINCT {name: e.name, domain: d.name, type: 'entity'}) AS entity_hits, "
            "       collect(DISTINCT {name: ba.name, fq_name: ba.fq_name, "
            "                          entity: e2.name, domain: d2.name, type: 'attribute'}) AS attribute_hits"
        )

        rows = await self.neo4j.run_query(
            cypher,
            parameters={"spans": spans},
            trace_id=trace_id,
        )

        entity_candidates: List[Dict[str, Any]] = []
        attribute_candidates: List[Dict[str, Any]] = []
        seen_entities: set = set()
        seen_attributes: set = set()

        for row in rows:
            for hit in row.get("entity_hits") or []:
                name = (hit or {}).get("name")
                if not name:
                    continue
                key = ("entity", name, (hit.get("domain") or ""))
                if key in seen_entities:
                    continue
                seen_entities.add(key)
                entity_candidates.append(
                    {
                        "name": name,
                        "domain": hit.get("domain"),
                        "type": "entity",
                    }
                )
            for hit in row.get("attribute_hits") or []:
                name = (hit or {}).get("name")
                fq = (hit or {}).get("fq_name")
                if not name and not fq:
                    continue
                key = ("attribute", name or "", fq or "")
                if key in seen_attributes:
                    continue
                seen_attributes.add(key)
                attribute_candidates.append(
                    {
                        "name": name,
                        "fq_name": fq,
                        "entity": hit.get("entity"),
                        "domain": hit.get("domain"),
                        "type": "attribute",
                    }
                )

        logger.info(
            "Schema RAG results",
            layer="service",
            trace_id=trace_id,
            n_entities=len(entity_candidates),
            n_attributes=len(attribute_candidates),
        )
        return entity_candidates, attribute_candidates

    @staticmethod
    def _merge_candidates(
        entities: List[Dict[str, Any]], attributes: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        merged = list(entities) + list(attributes)
        return merged[:MAX_CANDIDATES]

    # ------------------------------------------------------------------
    # F4 — synonym detection (heuristic; F5 ships an LLM-cluster job)
    # ------------------------------------------------------------------

    # Salient tokens that, when shared between two BAs in the same domain,
    # strongly suggest synonymy. Auditors can extend this list later via
    # config; for now it covers the most common mortgage/origination concepts
    # we expect to encounter.
    _SALIENT_CONCEPT_TOKENS = frozenset({
        "income", "household", "earnings", "salary",
        "balance", "amount", "principal", "interest", "escrow",
        "rate", "ratio", "score", "fico",
        "ssn", "social", "tin", "tax",
        "dob", "birth",
        "address", "property", "zip",
        "loan", "mortgage", "borrower", "applicant", "customer",
        "date", "timestamp",
    })

    # Generic tokens that aren't useful for clustering (would over-match).
    _STOP_TOKENS = frozenset({
        "a", "an", "the", "of", "for", "to", "in", "on", "by", "and", "or",
        "id", "identifier", "ref", "reference", "number", "no", "nbr",
        "type", "status", "code", "value", "field",
        "annual", "yearly", "monthly", "daily",
        "borrower", "applicant",  # too common — keep ONLY when paired with concept token
    })

    @classmethod
    def _tokenize_attr_name(cls, name: str) -> set:
        if not name:
            return set()
        tokens = re.split(r"[_\.\s]+", name.lower())
        return {t for t in tokens if t and t not in cls._STOP_TOKENS}

    # Suffix tokens that mark "kind" rather than concept — when two attribute
    # names end in the same TYPE_MARKER they're the same KIND (both ratios,
    # both identifiers, etc.) but not necessarily synonyms; when they end in
    # DIFFERENT type markers they're definitely not synonyms even if they
    # share the same root concept. Used to suppress false positives like
    # ``debt_to_income_ratio`` vs ``annual_household_income`` (both contain
    # "income" but one is a ratio, the other is a measured amount).
    _TYPE_MARKERS = frozenset({
        "ratio", "identifier", "id", "status", "code", "type",
        "count", "pct", "percentage", "tier", "rank", "level",
        "rate",  # interest_rate vs annual_household_income — different kinds
        "score",
        "date", "timestamp", "ts",
        "name", "address",
        "flag", "indicator",
    })

    @classmethod
    def _last_token(cls, name: str) -> str:
        if not name:
            return ""
        return re.split(r"[_\.\s]+", name.lower())[-1]

    @classmethod
    def _detect_synonym_clusters(
        cls, canonical_entities: List[Dict[str, Any]]
    ) -> List[List[str]]:
        """Group canonical attributes that look like synonyms in the same domain.

        Two BAs are clustered when:
          * same domain, different fq_names, AND
          * their **last name token** is identical AND that last token is a
            salient concept word (e.g. both end in ``_income``, ``_balance``,
            ``_amount``).

        This catches ``borrower_annual_income`` vs ``annual_household_income``
        (last token ``income``, salient) and ``original_balance`` vs
        ``current_balance`` if both surface — without false-positiving
        ``debt_to_income_ratio`` against either (last token ``ratio``).
        """
        attrs = [
            ce for ce in canonical_entities
            if ce.get("fq_name") and ce.get("name")
        ]
        if len(attrs) < 2:
            return []

        tokenized = []
        for a in attrs:
            last = cls._last_token(a.get("name") or "")
            tokenized.append({
                "fq_name": a["fq_name"],
                "name": a["name"],
                "domain": a.get("domain") or "",
                "last": last,
                "is_salient_last": last in cls._SALIENT_CONCEPT_TOKENS
                                   and last not in cls._TYPE_MARKERS,
            })

        n = len(tokenized)
        parent = list(range(n))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        def union(i, j):
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[ri] = rj

        for i in range(n):
            for j in range(i + 1, n):
                a, b = tokenized[i], tokenized[j]
                if a["domain"] != b["domain"]:
                    continue
                if a["fq_name"] == b["fq_name"]:
                    continue
                if not a["is_salient_last"] or not b["is_salient_last"]:
                    continue
                if a["last"] != b["last"]:
                    continue
                union(i, j)

        clusters_map: Dict[int, List[str]] = {}
        for i, item in enumerate(tokenized):
            root = find(i)
            clusters_map.setdefault(root, []).append(item["fq_name"])

        return [sorted(set(grp)) for grp in clusters_map.values() if len(grp) >= 2]

    # ------------------------------------------------------------------
    # Step 3: Entity Resolution
    # ------------------------------------------------------------------

    async def _step3_entity_resolution(
        self,
        question: str,
        candidates: List[Dict[str, Any]],
        trace_id: str,
        prior_turns: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Ask the LLM to pick the relevant subset of ontology nodes.

        Phase F7: prior dialog turns are prepended so the resolver can use the
        user's clarifications to disambiguate competing candidates.
        """
        if not candidates:
            return [], []

        prior_turns = prior_turns or []
        # Truncate just to be safe; _merge_candidates already caps but be defensive.
        capped = candidates[:MAX_CANDIDATES]

        system = (
            "Given the user's question and the candidate ontology nodes below, "
            "pick only those that are clearly relevant. Return JSON of the form: "
            '{"canonical_entities": [...], "relationships": [...]}. '
            "Each canonical_entities item must be one of the supplied candidates "
            "(copy its name / fq_name / domain verbatim). Do not invent names. "
            "If none are relevant, return empty arrays. "
            "If prior dialog turns are present, prefer candidates that match the "
            "user's most recent clarification."
        )
        user = (
            f"Question: {question}\n\n"
            f"Candidates (JSON): {json.dumps(capped)}\n\n"
            "Respond with JSON only."
        )

        messages: List[Dict[str, str]] = list(_dialog_chat_messages(prior_turns))
        messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})

        try:
            raw = await asyncio.wait_for(
                self.llm.complete(
                    messages=messages,
                    trace_id=trace_id,
                ),
                timeout=LLM_SOFT_TIMEOUT_SEC,
            )
            parsed = _safe_parse_json(raw)
            if isinstance(parsed, dict):
                canonical = self._normalize_canonical(
                    parsed.get("canonical_entities") or [], capped
                )
                relationships = parsed.get("relationships") or []
                if not isinstance(relationships, list):
                    relationships = []
                logger.info(
                    "Entity resolution parsed",
                    layer="service",
                    trace_id=trace_id,
                    n_canonical=len(canonical),
                    n_relationships=len(relationships),
                )
                return canonical, relationships
            logger.warning(
                "Entity resolution JSON unparseable — using top-5 candidates",
                layer="service",
                trace_id=trace_id,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Entity resolution timed out — using top-5 candidates",
                layer="service",
                trace_id=trace_id,
            )
        except Exception as exc:
            logger.warning(
                "Entity resolution failed — using top-5 candidates",
                layer="service",
                trace_id=trace_id,
                error=str(exc),
            )

        return self._normalize_canonical(capped[:5], capped), []

    @staticmethod
    def _normalize_canonical(
        picked: List[Any], candidates: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Coerce LLM-picked entities into the CanonicalEntity TypedDict shape.

        We anchor on the candidates list — a picked item that doesn't match a
        candidate (by name/fq_name) is dropped to enforce "no invented names".
        """
        # Build a lookup keyed by name and fq_name for fast verification.
        by_key: Dict[str, Dict[str, Any]] = {}
        for c in candidates:
            for k in (c.get("name"), c.get("fq_name")):
                if k:
                    by_key[str(k).lower()] = c

        out: List[Dict[str, Any]] = []
        for item in picked:
            if isinstance(item, str):
                key = item.lower()
                cand = by_key.get(key)
                if cand:
                    out.append(
                        {
                            "name": cand.get("name") or item,
                            "domain": cand.get("domain"),
                            "fq_name": cand.get("fq_name"),
                            "confidence": 1.0,
                        }
                    )
                continue
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            fq = item.get("fq_name")
            lookup_key = (fq or name or "").lower()
            cand = by_key.get(lookup_key)
            if not cand:
                # Skip unknown — enforces "do not invent names".
                continue
            out.append(
                {
                    "name": cand.get("name") or name,
                    "domain": cand.get("domain") or item.get("domain"),
                    "fq_name": cand.get("fq_name") or fq,
                    "confidence": float(item.get("confidence") or 1.0),
                }
            )
        return out

    # ------------------------------------------------------------------
    # Step 4: Dataset binding lookup
    # ------------------------------------------------------------------

    async def _step4_dataset_bindings(
        self,
        canonical_entities: List[Dict[str, Any]],
        trace_id: str,
    ) -> Tuple[List[Dict[str, Any]], List[str], List[Dict[str, Any]]]:
        """For each chosen attribute (or each entity's attributes when no
        attribute-level fq_names were resolved), walk MAPS_TO -> DataColumn ->
        DataAsset."""
        attribute_fq_names = [
            ce.get("fq_name") for ce in canonical_entities if ce.get("fq_name")
        ]
        attribute_fq_names = [a for a in attribute_fq_names if a]

        # Entity expansion: when the resolver only returned entity-level
        # matches (no fq_name on canonical entities), pull every attribute of
        # each entity via HAS_ATTRIBUTE so we still get a binding set. Without
        # this, NL questions like "show me Loan activity" produce empty
        # bindings even when the ontology has a fully-mapped Loan entity.
        if not attribute_fq_names:
            entity_names = [ce.get("name") for ce in canonical_entities if ce.get("name")]
            entity_names = [n for n in entity_names if n]
            if entity_names:
                try:
                    rows = await self.neo4j.run_query(
                        (
                            "UNWIND $entity_names AS ename "
                            "MATCH (e:BusinessEntity {name: ename})"
                            "      -[:HAS_ATTRIBUTE]->(ba:BusinessAttribute) "
                            "RETURN DISTINCT ba.fq_name AS fq_name"
                        ),
                        parameters={"entity_names": entity_names},
                        trace_id=trace_id,
                    )
                    expanded = [r.get("fq_name") for r in rows if r.get("fq_name")]
                    attribute_fq_names = expanded
                    logger.info(
                        "Entity→attribute expansion",
                        layer="service",
                        trace_id=trace_id,
                        entities=entity_names,
                        n_attributes=len(expanded),
                    )
                except Exception as exc:
                    logger.warning(
                        "Entity→attribute expansion failed (non-fatal)",
                        layer="service",
                        trace_id=trace_id,
                        error=str(exc),
                    )

        if not attribute_fq_names:
            return [], [], []

        # Phase E4 — only follow live edges (effective_until IS NULL). The
        # ``map.version`` returned per match is aggregated into
        # ``ontology_versions`` as ``v{n}`` strings so the orchestrator can
        # stamp them onto each TaskNode for replay/audit.
        cypher = (
            "UNWIND $attribute_fq_names AS afq "
            "MATCH (ba:BusinessAttribute {fq_name: afq})-[map:MAPS_TO]->(col:DataColumn) "
            "WHERE map.effective_until IS NULL "
            "OPTIONAL MATCH (a:DataAsset)-[:HAS_COLUMN]->(col) "
            "OPTIONAL MATCH (ds:DataSource)-[:HAS_ASSET]->(a) "
            "RETURN afq AS attribute_fq_name, "
            "       a.fq_name AS asset_fq_name, "
            "       a.asset_type AS asset_type, "
            "       col.name AS column_name, "
            "       ds.source_uri AS source_uri, "
            "       ds.source_type AS source_type, "
            "       map.version AS map_version, "
            "       map.confidence AS map_confidence"
        )

        try:
            rows = await self.neo4j.run_query(
                cypher,
                parameters={"attribute_fq_names": attribute_fq_names},
                trace_id=trace_id,
            )
        except Exception as exc:
            logger.warning(
                "Dataset binding lookup failed (non-fatal)",
                layer="service",
                trace_id=trace_id,
                error=str(exc),
            )
            return [], [], []

        # Group by asset_fq_name -> DatasetBinding. Aggregate distinct
        # ``map.version`` values across all bindings as ``v{n}`` strings so
        # the orchestrator can stamp them onto each TaskNode for replay/audit
        # ("explain why this answer was generated").
        bindings_by_asset: Dict[str, Dict[str, Any]] = {}
        seen_versions: set = set()

        for row in rows:
            asset = row.get("asset_fq_name")
            if not asset:
                # Skip rows where the column has no parent asset.
                continue
            col = row.get("column_name")
            entry = bindings_by_asset.setdefault(
                asset,
                {
                    "asset_fq_name": asset,
                    "columns": [],
                    "source_uri": row.get("source_uri"),
                    "source_type": row.get("source_type"),
                    "asset_type": row.get("asset_type"),
                },
            )
            if col and col not in entry["columns"]:
                entry["columns"].append(col)
            if not entry.get("source_uri") and row.get("source_uri"):
                entry["source_uri"] = row.get("source_uri")
            if not entry.get("source_type") and row.get("source_type"):
                entry["source_type"] = row.get("source_type")
            if not entry.get("asset_type") and row.get("asset_type"):
                entry["asset_type"] = row.get("asset_type")

            ver = row.get("map_version")
            if ver is not None:
                try:
                    seen_versions.add(int(ver))
                except (TypeError, ValueError):
                    pass

        versions: List[str] = [f"v{n}" for n in sorted(seen_versions)]
        bindings = list(bindings_by_asset.values())

        logger.info(
            "Dataset bindings resolved",
            layer="service",
            trace_id=trace_id,
            n_bindings=len(bindings),
            n_versions=len(versions),
        )
        return bindings, versions, rows

    # ------------------------------------------------------------------
    # Step 5: Few-shot retrieval
    # ------------------------------------------------------------------

    async def _step5_fewshot(
        self, question: str, trace_id: str
    ) -> List[Dict[str, Any]]:
        """Retrieve up to FEWSHOT_K matching translation_examples from Qdrant.

        Returns a pruned list with just ``question`` and ``decomposition`` so
        the decomposition prompt stays small.
        """
        if not self.embedder.available():
            logger.info(
                "Embedder unavailable — skipping few-shot retrieval",
                layer="service",
                trace_id=trace_id,
            )
            return []

        try:
            vec = await self.embedder.embed(question)
        except Exception as exc:
            logger.warning(
                "Few-shot embed failed (non-fatal)",
                layer="service",
                trace_id=trace_id,
                error=str(exc),
            )
            return []

        try:
            hits = await self.qdrant.search(query_vector=vec, k=FEWSHOT_K)
        except Exception as exc:
            logger.warning(
                "Few-shot Qdrant search failed (non-fatal)",
                layer="service",
                trace_id=trace_id,
                error=str(exc),
            )
            return []

        pruned: List[Dict[str, Any]] = []
        for h in hits or []:
            score = float(h.get("score") or 0.0)
            if score < FEWSHOT_SCORE_THRESHOLD:
                continue
            payload = h.get("payload") or {}
            pruned.append(
                {
                    "question": payload.get("question", ""),
                    "decomposition": payload.get("decomposition", []),
                }
            )

        logger.info(
            "Few-shot retrieval done",
            layer="service",
            trace_id=trace_id,
            n_hits=len(pruned),
        )
        return pruned

    # ------------------------------------------------------------------
    # Step 6b: Deterministic Report resolution (Ext2)
    # ------------------------------------------------------------------

    async def _step6b_report_resolution(
        self,
        question: str,
        spans: List[str],
        canonical_entities: List[Dict[str, Any]],
        prior_turns: List[Dict[str, Any]],
        trace_id: str,
    ) -> List[Dict[str, Any]]:
        """Search ``(:Report)`` nodes for matches to the user's question.

        Score = name/desc/team token-overlap with question spans  ×3
              + ``USES_ATTRIBUTE`` overlap with canonical attributes  ×2
              + owner_team token in question text                    ×1
        Returns at most the top 3 matches with score > 0, sorted desc.
        """
        # Build a scoring vocabulary from question + spans + dialog history.
        text = " ".join(
            [question]
            + (spans or [])
            + [
                str(t.get("content") or "")
                for t in (prior_turns or [])
                if (t.get("role") or "").lower() == "user"
            ]
        ).lower()
        question_tokens = {t for t in re.split(r"[\s,.\?\!\(\)\[\]\-\_/]+", text) if t and len(t) >= 3}
        ce_fqs = [
            str(ce.get("fq_name")) for ce in canonical_entities if ce.get("fq_name")
        ]

        try:
            rows = await self.neo4j.run_query(
                """
                MATCH (r:Report)
                OPTIONAL MATCH (r)-[:USES_ATTRIBUTE]->(ba:BusinessAttribute)
                OPTIONAL MATCH (r)-[:HAS_DATASET]->(rd:ReportDataset)
                OPTIONAL MATCH (rd)-[:RUNS_ON]->(ds:DataSource)
                RETURN r.report_id AS report_id,
                       r.name      AS name,
                       r.description AS description,
                       r.system    AS system,
                       r.owner_team AS owner_team,
                       collect(DISTINCT {
                         dataset_id: rd.dataset_id,
                         name: rd.name,
                         command: rd.command,
                         command_type: rd.command_type,
                         source_uri: ds.source_uri,
                         source_name: ds.source_name
                       }) AS datasets,
                       collect(DISTINCT ba.fq_name) AS uses_attributes
                """,
                {},
                trace_id=trace_id,
            )
        except Exception as exc:
            logger.warning(
                "Report resolution query failed (non-fatal)",
                layer="service", trace_id=trace_id, error=str(exc),
            )
            return []

        # Stop-words that contribute noise rather than signal — appear in
        # almost any English sentence, give false matches against descriptions
        # and report names.
        REPORT_STOP_WORDS = {
            "and", "are", "the", "for", "our", "with", "from", "into", "over",
            "that", "this", "what", "any", "all", "not", "but", "use", "used",
            "show", "list", "find", "get", "give", "tell", "want", "need",
            "have", "has", "had", "you", "your", "new", "old", "via",
        }
        # Score weights — name-only matching, higher per-match weight than the
        # old surface-area approach. Description/owner_team/system are dropped
        # entirely from text scoring (they were noise channels — long English
        # filler that produced accidental matches).
        NAME_TOKEN_WEIGHT = 4.0
        ATTR_MATCH_WEIGHT = 2.0
        # Require name-token overlap to clear this minimum before counting —
        # single-token matches like "payment" against "Monthly Payment Trends"
        # are not enough on their own.
        MIN_NAME_OVERLAP = 2
        # Attribute-overlap is gated by precision: matched / |question_attrs|.
        # If the resolver over-pulled (e.g. 168 candidates from "balloon_payment")
        # and only 2 hit the report's USES_ATTRIBUTE, that is 1.2% — noise, not
        # signal. Below this fraction, attr_score is zeroed.
        MIN_ATTR_PRECISION = 0.10

        question_tokens_clean = question_tokens - REPORT_STOP_WORDS
        question_lower = text  # already lower-cased above

        scored: List[Dict[str, Any]] = []
        for row in rows or []:
            name_only = (row.get("name") or "").lower()
            name_tokens = {
                t for t in re.split(r"[\s,.\?\!\-\_]+", name_only)
                if t and len(t) >= 3 and t not in REPORT_STOP_WORDS
            }
            text_overlap = question_tokens_clean & name_tokens

            # Phrase-substring escape hatch: if the report's full name appears
            # verbatim in the question, count it as a strong match even when
            # multi-token gate would otherwise reject (e.g., a single-word
            # report name like "Forecast" mentioned by the user).
            phrase_hit = bool(name_only) and name_only in question_lower

            if not phrase_hit and len(text_overlap) < MIN_NAME_OVERLAP:
                # Below the multi-token gate — name signal is too weak.
                text_score = 0.0
            else:
                text_score = len(text_overlap) * NAME_TOKEN_WEIGHT
                if phrase_hit:
                    # Bonus for full-name substring match.
                    text_score += NAME_TOKEN_WEIGHT

            ba_list = [a for a in (row.get("uses_attributes") or []) if a]
            attr_overlap = set(ce_fqs) & set(ba_list)
            attr_match_count = len(attr_overlap)
            denom = max(1, len(ce_fqs))
            attr_precision = attr_match_count / denom
            if attr_precision < MIN_ATTR_PRECISION:
                attr_score = 0.0
            else:
                attr_score = attr_match_count * ATTR_MATCH_WEIGHT

            score = text_score + attr_score
            if score <= 0:
                continue

            datasets = [
                d for d in (row.get("datasets") or [])
                if d and d.get("dataset_id")
            ]

            why_bits = []
            if phrase_hit:
                why_bits.append(f"name phrase matched")
            if text_overlap:
                why_bits.append(f"name tokens: {sorted(text_overlap)[:5]}")
            if attr_overlap and attr_score > 0:
                why_bits.append(
                    f"uses {attr_match_count} of {len(ce_fqs)} canonical attrs "
                    f"(precision {attr_precision:.2f})"
                )
            why = "; ".join(why_bits) or "weak signal"

            scored.append({
                "report_id": row.get("report_id"),
                "name": row.get("name"),
                "description": row.get("description"),
                "system": row.get("system"),
                "owner_team": row.get("owner_team"),
                "datasets": datasets,
                "uses_attributes": ba_list,
                "score": float(score),
                "why": why,
            })

        scored.sort(key=lambda x: x["score"], reverse=True)
        top = scored[:3]
        if top:
            logger.info(
                "Report resolution matches",
                layer="service",
                trace_id=trace_id,
                top_name=top[0]["name"],
                top_score=top[0]["score"],
                n_matches=len(top),
            )
        return top

    # ------------------------------------------------------------------
    # Step 6: Decomposition
    # ------------------------------------------------------------------

    async def _step6_decomposition(
        self,
        question: str,
        intent: str,
        domain: Optional[str],
        canonical_entities: List[Dict[str, Any]],
        dataset_bindings: List[Dict[str, Any]],
        fewshot_examples: List[Dict[str, Any]],
        trace_id: str,
        prior_turns: Optional[List[Dict[str, Any]]] = None,
    ) -> List[str]:
        """Produce 1-5 business-domain subtasks tagged with canonical entities.

        Phase F7: prior_turns are prepended so the decomposer reflects any
        clarifications the user made in earlier rounds.
        """
        # Per spec: if there are no dataset bindings, return [].
        if not dataset_bindings:
            logger.info(
                "No dataset bindings — skipping decomposition",
                layer="service",
                trace_id=trace_id,
            )
            return []

        prior_turns = prior_turns or []

        system = (
            "You are decomposing a user's natural-language business question into "
            "1-5 concrete, executable sub-tasks. Use the canonical business "
            "entities and dataset bindings provided. Each sub-task must reference "
            "at least one dataset binding. Return JSON: "
            '{"domain_subtasks": ["...", "..."]}. '
            "If you have no dataset bindings, return an empty list. "
            "If prior dialog turns are present, treat the user's most recent "
            "clarification as the authoritative scope for the decomposition."
        )

        user_parts: List[str] = [
            f"Question: {question}",
            f"Intent: {intent}",
            f"Domain: {domain or 'unknown'}",
            f"Canonical entities: {json.dumps(canonical_entities)}",
            f"Dataset bindings: {json.dumps(dataset_bindings)}",
        ]
        if fewshot_examples:
            user_parts.append(
                "Few-shot examples (each is a question + its decomposition):\n"
                + json.dumps(fewshot_examples)
            )
        user_parts.append("Respond with JSON only.")
        user = "\n\n".join(user_parts)

        messages: List[Dict[str, str]] = list(_dialog_chat_messages(prior_turns))
        messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})

        try:
            raw = await asyncio.wait_for(
                self.llm.complete(
                    messages=messages,
                    trace_id=trace_id,
                ),
                timeout=LLM_SOFT_TIMEOUT_SEC,
            )
            parsed = _safe_parse_json(raw)
            subtasks: List[str] = []
            if isinstance(parsed, dict):
                arr = parsed.get("domain_subtasks") or []
                if isinstance(arr, list):
                    subtasks = [str(s).strip() for s in arr if str(s).strip()]
            elif isinstance(parsed, list):
                subtasks = [str(s).strip() for s in parsed if str(s).strip()]

            if subtasks:
                # Cap at 5 per the spec.
                return subtasks[:5]

            logger.warning(
                "Decomposition produced no subtasks — using fallback",
                layer="service",
                trace_id=trace_id,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Decomposition timed out — using fallback",
                layer="service",
                trace_id=trace_id,
            )
        except Exception as exc:
            logger.warning(
                "Decomposition failed — using fallback",
                layer="service",
                trace_id=trace_id,
                error=str(exc),
            )
        return [question]

    # ------------------------------------------------------------------
    # Step 7: Used ontology subgraph
    # ------------------------------------------------------------------

    @staticmethod
    def _step7_used_subgraph(
        canonical_entities: List[Dict[str, Any]],
        binding_rows: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Assemble {nodes, edges} from what we touched."""
        nodes: List[Dict[str, Any]] = []
        edges: List[Dict[str, Any]] = []
        seen_nodes: set = set()

        def add_node(node_id: str, label: str, **props: Any) -> None:
            if not node_id or node_id in seen_nodes:
                return
            seen_nodes.add(node_id)
            n = {"id": node_id, "label": label}
            n.update({k: v for k, v in props.items() if v is not None})
            nodes.append(n)

        def add_edge(src: str, dst: str, rel: str) -> None:
            if not src or not dst:
                return
            edges.append({"source": src, "target": dst, "type": rel})

        for ce in canonical_entities:
            name = ce.get("name") or ce.get("fq_name") or ""
            label = "BusinessAttribute" if ce.get("fq_name") else "BusinessEntity"
            add_node(name, label, domain=ce.get("domain"), fq_name=ce.get("fq_name"))
            domain = ce.get("domain")
            if domain:
                add_node(domain, "BusinessDomain")
                add_edge(domain, name, "HAS_ENTITY" if label == "BusinessEntity" else "HAS_ATTRIBUTE")

        for row in binding_rows or []:
            attr = row.get("attribute_fq_name")
            asset = row.get("asset_fq_name")
            col = row.get("column_name")
            if attr:
                add_node(attr, "BusinessAttribute", fq_name=attr)
            if asset:
                add_node(
                    asset,
                    "DataAsset",
                    asset_type=row.get("asset_type"),
                    source_uri=row.get("source_uri"),
                )
            if col:
                col_id = f"{asset}.{col}" if asset else col
                add_node(col_id, "DataColumn", column=col)
                if asset:
                    add_edge(asset, col_id, "HAS_COLUMN")
                if attr:
                    add_edge(attr, col_id, "MAPS_TO")

        return {"nodes": nodes, "edges": edges}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    # File extensions that imply the user is asking about a document and
    # therefore wants RAG retrieval, not a saved-report/SQL match.
    _DOCUMENT_EXTENSIONS = (
        "docx", "doc", "pdf", "xlsx", "xls", "csv", "txt", "md",
        "pptx", "ppt", "html", "htm", "rtf",
    )

    # Phrase fragments that signal the user is asking about the live graph
    # (Neo4j ontology / home-lending knowledge graph) — should bypass the
    # SQL-leaning report match and route to the graph tool via the agent.
    _GRAPH_PHRASES = (
        "knowledge graph",
        "home lending graph",
        "lending graph",
        "ontology graph",
        "graph database",
        "in the graph",
        "from the graph",
        "neo4j",
        "cypher",
    )

    @classmethod
    def _detect_explicit_routing_hints(cls, question: str) -> Dict[str, Any]:
        """Detect signals that make the question precise enough to bypass
        the report-match and synonym-narrowing short-circuits.

        Returns a dict with any of:
          ``document``    — file-extension mention (.docx, .pdf, ...)
          ``graph``       — graph/Neo4j/ontology phrase
          ``tables``      — list of "<name> table" mentions (lowercased)
          ``record_ids``  — list of capitalized-prefix record ids (e.g. L0009)

        Empty dict means no explicit signal — the existing pipeline behavior
        applies.
        """
        if not question:
            return {}
        q_lower = question.lower()
        out: Dict[str, Any] = {}

        # Document references — file extension after a token.
        ext_pattern = r"\.(?:" + "|".join(cls._DOCUMENT_EXTENSIONS) + r")\b"
        if re.search(ext_pattern, q_lower):
            out["document"] = True

        # Graph references — any phrase from the allow-list.
        for phrase in cls._GRAPH_PHRASES:
            if phrase in q_lower:
                out["graph"] = True
                break

        # Explicit "<name> table" references — capture the noun before "table".
        tables = re.findall(r"\b([a-z][a-z0-9_]{2,})\s+table\b", q_lower)
        if tables:
            out["tables"] = tables

        # Record-id pattern — short alpha prefix + 3+ digits, e.g. L0009, FC123.
        # Use the original-case question so we only catch obviously-id-shaped
        # tokens, not regular words.
        record_ids = re.findall(r"\b[A-Z]{1,3}\d{3,}\b", question)
        if record_ids:
            out["record_ids"] = record_ids

        return out

    # Phrases that strongly suggest the question is about catalog SHAPE
    # (which tables / databases / schemas have a column named X) rather
    # than the values stored in those columns. The ontology pipeline
    # handles the latter; the former needs information_schema / db.schema
    # introspection on the actual datasources, which only the agent loop
    # can run.
    _SCHEMA_META_OBJECT_TOKENS = r"(?:tables?|databases?|schemas?|datasets?|systems?|catalogs?|stores?)"
    _SCHEMA_META_FIELD_TOKENS = r"(?:columns?|fields?|attributes?|properties)"
    _SCHEMA_META_VERBS = r"(?:have|has|contain|contains|with|where|use|uses|reference|references|expose|exposes)"

    # Identifier shapes we accept as "the column the user is asking about".
    # Order matters: snake_case / quoted forms beat bare lowercase tokens
    # so we prefer "loan_id" over "loan" / "id".
    _SCHEMA_META_COLUMN_PATTERNS = (
        # quoted: "loan_id", `loan_id`, 'loan_id'
        r"['\"`]([a-zA-Z][a-zA-Z0-9_]*)['\"`]",
        # column/field <name> or column named/called <name>
        r"\b(?:column|columns|field|fields|attribute|attributes)\s+(?:named\s+|called\s+)?([a-zA-Z][a-zA-Z0-9_]*)\b",
        # <snake_case_name> column / field — stronger signal than bare word.
        r"\b([a-zA-Z][a-zA-Z0-9_]*?_[a-zA-Z][a-zA-Z0-9_]*)\s+(?:columns?|fields?|attributes?)\b",
        # bare <name> column / field — last resort, weakest pattern.
        r"\b([a-zA-Z][a-zA-Z0-9_]*)\s+(?:columns?|fields?|attributes?)\b",
    )

    # Tokens that look identifier-shaped but are filler words. Skip them
    # when extracting the column name so we don't grab "the" out of
    # "the loan_id column".
    _SCHEMA_META_STOP_TOKENS = frozenset({
        "the", "a", "an", "any", "every", "all", "some", "many", "more",
        "this", "that", "these", "those", "your", "their", "such", "same",
        "primary", "foreign", "unique", "common", "shared", "related",
        "named", "called", "specific", "particular", "given",
    })

    @classmethod
    def _detect_schema_meta_question(cls, question: str) -> Tuple[bool, Optional[str]]:
        """Detect catalog meta-questions ("how many tables have <col>",
        "where does <col> exist", "which databases contain <col> column").

        Returns ``(is_schema_meta, column_name_or_None)``. When the
        question is a schema-meta question we always return ``True`` —
        even if we couldn't extract a column name — because the
        translator should still skip the ontology pipeline and let the
        agents see the original wording.
        """
        if not question:
            return False, None
        q = question.strip()
        q_lower = q.lower()

        # Pattern 1: "<verb-of-having>" + catalog-object + field-token.
        # Examples: "tables that have a loan_id column",
        #           "databases with X field",
        #           "which schemas use a borrower_id column".
        catalog_field_re = re.compile(
            rf"\b{cls._SCHEMA_META_OBJECT_TOKENS}\b[\s\w]{{0,80}}?\b{cls._SCHEMA_META_FIELD_TOKENS}\b"
            rf"|\b{cls._SCHEMA_META_FIELD_TOKENS}\b[\s\w]{{0,80}}?\b{cls._SCHEMA_META_OBJECT_TOKENS}\b",
            re.IGNORECASE,
        )
        # Pattern 2: explicit existence verbs about a column/field —
        # "where does <col> exist", "is there a <col> column", "in which
        # tables can I find <col>".
        existence_re = re.compile(
            r"\b(?:where\s+(?:is|does|do|are|can\s+(?:i|we)\s+find)"
            r"|in\s+which\s+(?:tables?|databases?|schemas?|datasets?)"
            r"|is\s+(?:there|the)\s+(?:a\s+)?(?:column|field|attribute)"
            r"|does\s+(?:any|the)\s+(?:table|database|schema|dataset)"
            r"|which\s+(?:tables?|databases?|schemas?|datasets?)\s+(?:have|contain|with|has))\b",
            re.IGNORECASE,
        )

        is_meta = bool(catalog_field_re.search(q_lower)) or bool(existence_re.search(q_lower))
        if not is_meta:
            return False, None

        # Try each column-extraction pattern in priority order; pick the
        # first non-stop, non-object/-field-token candidate.
        skip = cls._SCHEMA_META_STOP_TOKENS
        skip_extra = {"table", "tables", "database", "databases", "schema",
                      "schemas", "dataset", "datasets", "system", "systems",
                      "catalog", "catalogs", "store", "stores",
                      "column", "columns", "field", "fields",
                      "attribute", "attributes", "property", "properties",
                      "name", "id"}
        for pat in cls._SCHEMA_META_COLUMN_PATTERNS:
            for m in re.finditer(pat, q):
                cand = (m.group(1) or "").strip()
                cand_l = cand.lower()
                if not cand or cand_l in skip or cand_l in skip_extra:
                    continue
                if len(cand_l) < 2:
                    continue
                return True, cand
        return True, None

    # ------------------------------------------------------------------
    # Column-value broadcast detection
    # ------------------------------------------------------------------
    # "what is the value of loan_id across these tables", "give me sample
    # of 5 values from each of these tables" — same root cause as
    # schema-meta: span "loan_id" tokenises to "loan", matches every
    # `Servicing.Loan.*_balance` BA in the ontology, the synonym detector
    # clusters them by `_balance` suffix, and the user gets the same
    # nonsense clarification while the agents (which CAN sample the
    # actual rows) never run. Treat these as a sibling broadcast intent:
    # bypass the ontology gate, hand each DB/GRAPH agent a "list tables
    # with column X, then SELECT a sample from each" plan.
    _COLUMN_VALUE_VERBS = (
        r"(?:value|values|sample|samples|sampling|rows?|records?|"
        r"data|observations?|examples?|entries|instances?)"
    )
    _COLUMN_VALUE_SCOPE = (
        # Multi-source qualifier — at least one of these must be present
        # to confirm the user wants cross-table coverage. A single-table
        # data question ("show me 5 rows of loans") shouldn't broadcast.
        r"(?:across|in\s+each|from\s+each|from\s+all|from\s+the|"
        r"from\s+these|from\s+those|every\s+(?:table|database|source)|"
        r"\btables\b|\bdatabases\b|data\s*sources?|"
        r"\bdatasets\b|\btools\b)"
    )
    _COLUMN_VALUE_COLUMN_PATTERNS = (
        # quoted name
        r"['\"`]([a-zA-Z][a-zA-Z0-9_]*)['\"`]",
        # "value(s)/sample/rows of <col>" or "for/from <col>"
        r"\b(?:value|values|sample|samples|sampling|rows?|records?|data|"
        r"examples?)\s+(?:of|for|from|in)\s+(?:the\s+|each\s+|every\s+)?"
        r"([a-zA-Z][a-zA-Z0-9_]*?_[a-zA-Z][a-zA-Z0-9_]*)\b",
        # "<col> value(s)/sample/rows"
        r"\b([a-zA-Z][a-zA-Z0-9_]*?_[a-zA-Z][a-zA-Z0-9_]*)\s+"
        r"(?:value|values|sample|samples|rows?|records?|data)\b",
        # column/field <name>
        r"\b(?:column|columns|field|fields|attribute|attributes)\s+"
        r"(?:named\s+|called\s+)?([a-zA-Z][a-zA-Z0-9_]*)\b",
        # bare snake-case identifier near a value verb (last resort)
        r"\b([a-zA-Z][a-zA-Z0-9_]*?_[a-zA-Z][a-zA-Z0-9_]*)\b",
    )

    @classmethod
    def _detect_column_value_question(cls, question: str) -> Tuple[bool, Optional[str]]:
        """Detect cross-source data-sampling questions for a specific
        column ("value of loan_id across these tables", "sample 5 rows of
        loan_id from each table"). Returns ``(is_value_q, column)``.

        Conservative on purpose — we only return True when we see BOTH a
        value/sample verb AND a multi-source qualifier (across / each /
        plural tables / from these). A single-source data question
        ("show me 5 rows of the loans table") shouldn't broadcast.
        """
        if not question:
            return False, None
        q = question.strip()
        q_lower = q.lower()

        verb_re = re.compile(rf"\b{cls._COLUMN_VALUE_VERBS}\b", re.IGNORECASE)
        scope_re = re.compile(rf"\b{cls._COLUMN_VALUE_SCOPE}\b", re.IGNORECASE)
        if not (verb_re.search(q_lower) and scope_re.search(q_lower)):
            return False, None

        skip = cls._SCHEMA_META_STOP_TOKENS
        skip_extra = {
            "table", "tables", "database", "databases", "schema", "schemas",
            "dataset", "datasets", "system", "systems",
            "catalog", "catalogs", "store", "stores",
            "column", "columns", "field", "fields",
            "attribute", "attributes", "property", "properties",
            "value", "values", "sample", "samples", "row", "rows",
            "record", "records", "data", "name", "id",
        }
        for pat in cls._COLUMN_VALUE_COLUMN_PATTERNS:
            for m in re.finditer(pat, q):
                cand = (m.group(1) or "").strip()
                cand_l = cand.lower()
                if not cand or cand_l in skip or cand_l in skip_extra:
                    continue
                if len(cand_l) < 2:
                    continue
                return True, cand
        return True, None

    # ------------------------------------------------------------------
    # Entity-count broadcast detection
    # ------------------------------------------------------------------
    # "how many loans are there", "count of borrowers", "total number of
    # mortgages" — pure count of a business entity, no specific column.
    # Same trap as the other broadcasts: token-tokenisation matches every
    # `total_*_amount` BA in the ontology, the LLM resolver picks
    # attributes when the user wanted the entity, and the synonym
    # detector clusters the attributes by `_amount` suffix. Bypass the
    # whole ontology path; let the agents count the canonical entity in
    # their own datasources and the python_reduce step total the
    # numbers (no double-counting parent + subtype).
    _ENTITY_COUNT_VERB_RE = re.compile(
        r"\b(?:how\s+many|number\s+of|count\s+of|total(?:\s+number)?\s+of?|"
        r"how\s+much|"
        r"total\s+(?=[a-z]))\b",  # "total loans" matches via lookahead
        re.IGNORECASE,
    )
    # When any of these appear we hand off to MetadataPattern,
    # ColumnValuePattern, or BusinessPattern instead. These are the
    # signals that say "this isn't a pure entity-count question".
    # Two compiled forms — word-bounded keywords and the operator
    # alternation — because ``\b<\b`` won't fire on ``" > "`` (no word
    # boundary on either side of the operator).
    _ENTITY_COUNT_DISQUALIFIERS_RE = re.compile(
        r"\b(?:tables?|columns?|fields?|attributes?|databases?|schemas?|"
        r"datasets?|catalogs?|"
        r"sample|samples|rows?|records?|values?|"
        r"average|sum|max|min|median|"
        r"where\s+|having\s+|group\s+by)\b",
        re.IGNORECASE,
    )
    # Predicate operators with a numeric / quoted RHS — strong signal
    # the user wants a filtered count, which BusinessPattern handles.
    _ENTITY_COUNT_PREDICATE_RE = re.compile(
        r"[<>=!]=?\s*['\"\d]"
    )
    # Phase 9B — multi-attribute disqualifiers. A question that LEADS with
    # "how many X" but layers on additional attribute requests ("when did
    # they …, how long …, current status …, from CODE…") is a multi-
    # attribute cross-schema question owned by BusinessPattern. We count
    # signals; ≥2 = demote so we never stamp intent='entity_count_question'
    # on this shape. Mirrors the orchestrator-side check in entity_count.py.
    _ENTITY_COUNT_EXTRA_SIGNALS = (
        # Text continues after a "?" — second sentence territory.
        re.compile(r"\?\s*[A-Za-z]"),
        # ", when …" / ", how long …" / ", and what is …" — comma-chained
        # WH clauses asking for additional attributes.
        re.compile(
            r",\s*(?:and\s+)?\b(?:when|how\s+long|what\s+is|what\s+are|"
            r"what\s+was|where|why)\b",
            re.IGNORECASE,
        ),
        # "current status" / "current state" — categorical attribute ask.
        re.compile(
            r"\b(?:current|currently)\s+(?:status|state|condition|standing)\b",
            re.IGNORECASE,
        ),
        # "their status" / "their current balance" — possessive attribute ask.
        re.compile(
            r"\btheir\s+(?:current\s+)?"
            r"(?:status|state|condition|standing|score|balance|tenure)\b",
            re.IGNORECASE,
        ),
        # "how long" — duration request.
        re.compile(r"\bhow\s+long\b", re.IGNORECASE),
        # "since when" / "since 2020" / "since the cutover".
        re.compile(r"\bsince\s+(?:when|then|the|[A-Z0-9])", re.IGNORECASE),
        # Filter on identifier-shaped code: "from C0005" / "for CAMP-42".
        # The all-caps lookahead keeps "from california" out.
        re.compile(r"\b(?:from|under|for)\s+(?:the\s+)?[A-Z][A-Z0-9_-]{2,}\b"),
    )
    # Filler adjectives the user often layers in. Strip them when
    # extracting the entity noun so we get "loans" out of
    # "how many total active outstanding loans".
    _ENTITY_COUNT_FILLERS_RE = (
        r"(?:total|active|inactive|pending|outstanding|closed|open|"
        r"new|the|all|currently|"
        r"distinct|unique)"
    )

    @classmethod
    def _detect_entity_count_question(
        cls, question: str
    ) -> Tuple[bool, Optional[str]]:
        """Detect "how many <plural-noun>" / "count of <noun>" / "total
        <noun>" — a pure entity-count question with no attribute or
        predicate reference. Returns ``(is_count_q, entity_token)``.

        Conservative: defers to MetadataPattern / ColumnValuePattern /
        BusinessPattern when their disqualifier tokens appear (table /
        column / sample / value / predicate / aggregator).
        """
        if not question:
            return False, None
        q = question.strip()
        q_l = q.lower()

        if not cls._ENTITY_COUNT_VERB_RE.search(q_l):
            return False, None
        if cls._ENTITY_COUNT_DISQUALIFIERS_RE.search(q_l):
            return False, None
        if cls._ENTITY_COUNT_PREDICATE_RE.search(q_l):
            return False, None

        # Phase 9B — multi-attribute disqualifier. When the question piles
        # on additional attribute requests beyond the leading count,
        # BusinessPattern owns it. Count distinct signals; ≥2 → defer.
        n_extra = sum(
            1 for rx in cls._ENTITY_COUNT_EXTRA_SIGNALS if rx.search(q)
        )
        if n_extra >= 2:
            return False, None

        # Extract the noun after the count verb. Strip filler words.
        m = re.search(
            rf"\b(?:how\s+many|number\s+of|count\s+of|total(?:\s+number)?\s+of?"
            rf"|how\s+much|total)\s+"
            rf"(?:{cls._ENTITY_COUNT_FILLERS_RE}\s+)*"
            rf"([a-zA-Z][a-zA-Z0-9_]*)\b",
            q, re.IGNORECASE,
        )
        if not m:
            return True, None  # phrasing matched but couldn't pull a noun
        cand = (m.group(1) or "").strip()
        cl = cand.lower()
        # Reject filler-tokens that slipped through (regex backtracking can
        # still capture them when there's no following noun).
        if (cl in cls._SCHEMA_META_STOP_TOKENS
                or cl in {"total", "active", "inactive", "pending",
                          "outstanding", "closed", "open", "new",
                          "distinct", "unique", "currently", "are", "is",
                          "do", "does", "have", "has"}):
            return True, None
        if len(cl) < 2:
            return True, None
        return True, cand

    @classmethod
    def _detect_column_question(
        cls, question: str
    ) -> Tuple[str, Optional[str]]:
        """Unified detector for the three broadcast intents.

        Returns ``(kind, token)`` where ``kind`` is one of:
          ``"schema_meta"``  — catalog-shape question (column → ``token``)
          ``"column_value"`` — cross-source data-sampling for a column
          ``"entity_count"`` — pure count of a business entity
                              (entity-noun → ``token``)
          ``""``             — none of the above; let the normal ontology
                              pipeline handle it.

        Order matters: schema_meta and column_value detectors fire on
        more specific phrasings; entity_count is broader and runs last
        so its disqualifier set doesn't have to enumerate every shape
        the others catch.
        """
        is_meta, col = cls._detect_schema_meta_question(question)
        if is_meta:
            return "schema_meta", col
        is_val, col = cls._detect_column_value_question(question)
        if is_val:
            return "column_value", col
        is_count, entity = cls._detect_entity_count_question(question)
        if is_count:
            return "entity_count", entity
        return "", None

    @staticmethod
    def _best_domain(canonical_entities: List[Dict[str, Any]]) -> Optional[str]:
        for ce in canonical_entities:
            d = ce.get("domain")
            if d:
                return str(d)
        return None

    @staticmethod
    def _build_narrowing_question(
        prior_turns: List[Dict[str, Any]],
        canonical_entities: List[Dict[str, Any]],
        synonym_clusters: List[List[str]],
        dialog_turn: int,
    ) -> Optional[str]:
        """Construct a clarification question that's *narrower* than the
        previous turn. Strategy:

        1. If we found synonym clusters AND the user hasn't already
           addressed them in a prior turn, ask them to pick among them.
        2. Else if we matched canonical entities but no bindings, list the
           entity names so the user can confirm which one they meant.
        3. Else (no entities, dialog is mid-flight) ask for a stronger
           rephrase, referencing the user's prior reply if any.
        Returns None when no useful narrowing question can be built — caller
        should treat that as "leave clarification_question alone".
        """
        # 1. Synonym cluster narrowing — but only when the user hasn't
        # already responded to the same cluster. We treat the cluster as
        # acknowledged if any prior user turn contains a member's name
        # (full or last-token) OR signals they want all members ("both",
        # "side by side", "compare", "all", "either").
        if synonym_clusters:
            cluster = synonym_clusters[0]
            if len(cluster) >= 2:
                user_text = " ".join(
                    str(t.get("content") or "")
                    for t in (prior_turns or [])
                    if (t.get("role") or "").lower() == "user"
                ).lower()

                ack_keywords = (" both ", "side by side", "compare", "either",
                                " all ", " every ")
                user_acknowledged = any(k in f" {user_text} " for k in ack_keywords)

                # Mention check: user named a cluster member or its last token.
                if not user_acknowledged:
                    for member in cluster:
                        member_l = member.lower()
                        last_tok = member_l.rsplit(".", 1)[-1]  # tail of fq_name
                        if member_l in user_text or last_tok in user_text:
                            user_acknowledged = True
                            break

                if not user_acknowledged:
                    listed = ", ".join(cluster[:-1]) + f" and {cluster[-1]}"
                    return (
                        f"Among {listed}, which one do you mean? "
                        "Reply with the most specific one, or say "
                        "\"both\" if you want a comparison."
                    )
                # User addressed the cluster — fall through to entity / generic
                # narrowing logic. If the rest is fine, the caller will set
                # clarification_needed=False on its own.

        # 2. Entity-only narrowing — entities exist but no bindings.
        names = [
            str(ce.get("name") or ce.get("fq_name"))
            for ce in canonical_entities
            if (ce.get("name") or ce.get("fq_name"))
        ]
        names = [n for n in names if n]
        if names:
            top = names[:3]
            joined = ", ".join(top)
            return (
                f"I found these candidates: {joined}. Which one (or which "
                "subdomain) is the closest match to what you're asking about?"
            )

        # 3. Generic rephrase — use the most-recent user turn if present so
        # the question feels conversational rather than restarting from zero.
        last_user = ""
        for t in reversed(prior_turns):
            if (t.get("role") or "").lower() == "user":
                last_user = str(t.get("content") or "")
                break
        if last_user:
            short = last_user[:80] + ("…" if len(last_user) > 80 else "")
            return (
                f"I still couldn't match \"{short}\" to a known business "
                "concept. Could you name a specific dataset, attribute, or "
                "subdomain (e.g. loan servicing, origination, payments)?"
            )
        return (
            "I couldn't find a business concept matching your question. "
            "Could you rephrase it using domain terms (loan, borrower, "
            "payment, income, application, etc.)?"
        )

    @staticmethod
    def _fallback_result(intent: str, trace_id: str) -> TranslationResult:
        result = empty_translation_result(trace_id=trace_id)
        result["intent"] = intent or "unknown"
        return result
