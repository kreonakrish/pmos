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

        # Ext2 — Report resolution. Walk the (:Report) nodes in the ontology
        # graph, score each against the question + canonical entities + any
        # team mention. The orchestrator decides whether to run the command
        # directly (high-confidence single match) or just surface as context.
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
            if user_acked:
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
                },
            )
            if col and col not in entry["columns"]:
                entry["columns"].append(col)
            if not entry.get("source_uri") and row.get("source_uri"):
                entry["source_uri"] = row.get("source_uri")

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

        scored: List[Dict[str, Any]] = []
        for row in rows or []:
            name_text = " ".join(
                str(x or "")
                for x in (
                    row.get("name"),
                    row.get("description"),
                    row.get("owner_team"),
                    row.get("system"),
                )
            ).lower()
            name_tokens = {t for t in re.split(r"[\s,.\?\!\-\_]+", name_text) if t and len(t) >= 3}

            text_overlap = question_tokens & name_tokens
            text_score = len(text_overlap) * 3.0

            ba_list = [a for a in (row.get("uses_attributes") or []) if a]
            attr_overlap = set(ce_fqs) & set(ba_list)
            attr_score = len(attr_overlap) * 2.0

            team = (row.get("owner_team") or "").lower()
            team_score = 0.0
            if team and (team in text or team.replace("_", " ") in text):
                team_score = 1.0

            score = text_score + attr_score + team_score
            if score <= 0:
                continue

            datasets = [
                d for d in (row.get("datasets") or [])
                if d and d.get("dataset_id")
            ]

            why_bits = []
            if text_overlap:
                why_bits.append(f"name/desc tokens: {sorted(text_overlap)[:5]}")
            if attr_overlap:
                why_bits.append(f"uses {len(attr_overlap)} of {len(ce_fqs)} canonical attrs")
            if team_score:
                why_bits.append(f"owner_team={team}")
            why = "; ".join(why_bits)

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
