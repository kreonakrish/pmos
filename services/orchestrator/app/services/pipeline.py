"""9-step orchestration pipeline (ARCHITECTURE.md §9).

Steps:
  1  REQUEST INTAKE      — session/correlation IDs, SOP lookup
  2  GRAPH CONSTRUCTION  — LLM decomposes intent into TaskNodes
  3  PRE-EXECUTION VALIDATION — tool health, agent availability
  4  EXECUTION           — per node: memory → prompt → agent → score → band
  5  COURSE CORRECTION   — orchestrator-mediated (LOW/MEDIUM failures)
  6  AUTO-CORRECTION     — local immediate (HIGH/CRITICAL failures)
  7  INTERMEDIATE EXPANSION — complex responses spawn new TaskNodes
  8  AGGREGATION         — synthesise node results
  9  RESPONSE & LEARNING — persist, update memory/scoring
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional, Set, Tuple

import httpx
import mysql.connector

from app.adapters.agent_mgmt_adapter import AgentMgmtAdapter
from app.adapters.llm_adapter import LLMAdapter
from app.adapters.memory_adapter import MemoryAdapter
from app.adapters.meta_adapter import MetaAdapter
from app.adapters.neo4j_adapter import Neo4jAdapter
from app.adapters.rag_adapter import RAGAdapter
from app.adapters.redis_adapter import RedisAdapter
from app.adapters.scoring_adapter import ScoringAdapter
from app.adapters.translator_adapter import TranslatorAdapter
from app.config import settings
from app.models.bid import BidRequest, BidResponse, NegotiationResult
from app.models.task import Criticality, NodeType, TaskGraph
from app.services.agent_selector import Agent, AgentSelector
from app.services.bandit_selector import BanditDecision, BanditSelector
from app.services.capability_negotiation import CapabilityNegotiationService
from app.services.learned_scorer import LearnedScorer
from app.services.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError
from app.services.course_corrector import CourseAction, CourseCorrector
from app.services.graph_manager import GraphManager
from app.services.interaction_logger import InteractionLogger
from app.services.patterns import (
    DispatchContext,
    PatternDispatcher,
    TeamContext,
    build_default_registry,
)
from app.utils.audit import audit
from app.utils.logger import logger
from app.utils.telemetry import REQUEST_TOTAL


class PipelineService:
    """Coordinates the full 9-step execution pipeline."""

    def __init__(
        self,
        neo4j: Neo4jAdapter,
        redis: RedisAdapter,
        llm: LLMAdapter,
        memory: MemoryAdapter,
        scoring: ScoringAdapter,
        rag: RAGAdapter,
        meta: MetaAdapter,
        agent_mgmt: Optional[AgentMgmtAdapter] = None,
        translator: Optional[TranslatorAdapter] = None,
    ) -> None:
        self._neo4j = neo4j
        self._redis = redis
        self._llm = llm
        self._memory = memory
        self._scoring = scoring
        self._rag = rag
        self._meta = meta
        self._agent_mgmt = agent_mgmt or AgentMgmtAdapter()
        self._translator = translator or TranslatorAdapter()

        self._graph_mgr = GraphManager(neo4j)
        self._agent_sel = AgentSelector(neo4j)
        self._corrector = CourseCorrector(neo4j, redis)

        # Per-downstream circuit breakers
        self._cb_memory = CircuitBreaker("memory")
        self._cb_scoring = CircuitBreaker("scoring")
        self._cb_rag = CircuitBreaker("rag")
        self._cb_meta = CircuitBreaker("meta")
        self._cb_agent_mgmt = CircuitBreaker("agent_mgmt")

        # Cache of UUID → MySQL agents.id lookups (populated lazily by _resolve_agent_db_id).
        self._agent_db_id_cache: Dict[str, int] = {}

        # Capability negotiation service
        self._negotiation = CapabilityNegotiationService(
            neo4j=neo4j,
            llm=llm,
            memory=memory,
            agent_mgmt=self._agent_mgmt,
            cb_memory=self._cb_memory,
            cb_agent_mgmt=self._cb_agent_mgmt,
        )

        # Interaction logger (fire-and-forget)
        self._interaction_logger = InteractionLogger(neo4j)

        # Contextual bandit agent selector (shadow mode — logs decisions,
        # does not yet override _step3_negotiate's winner).
        self._bandit = BanditSelector()

        # Shadow learned-quality scorer (1B). Loads the active model if any
        # exists under /app/models. Predictions are logged but do NOT influence
        # the live score until w7_learned_quality > 0 in scoring_weights.
        self._learned_scorer = LearnedScorer()
        try:
            self._learned_scorer.load_active()
        except Exception as exc:
            logger.warning(
                "LearnedScorer load_active failed at startup",
                layer="service",
                error=str(exc),
            )

        # Question-pattern dispatcher. ``_pattern_routing_enabled`` is
        # the cutover flag flipped in Phase 4: when True, the
        # dispatcher's winner drives routing for the Report (auto-fire +
        # confirm) and Clarify branches. The other patterns
        # (TeamSelf, RAG-only, Metadata, ColumnValue, Business,
        # FreeForm) keep flowing through the existing helpers — their
        # decisions are recorded on the trace but execution is
        # unchanged from today.
        self._pattern_registry = build_default_registry()
        self._pattern_dispatcher = PatternDispatcher(self._pattern_registry.all())
        self._pattern_routing_enabled = True
        # Per-request scratch for the dispatcher. Reset at the top of
        # execute(); read by _run_pattern_dispatch() between step 2 and
        # the legacy gates so the gates can defer to the winner.
        self._last_translation: Dict[str, Any] = {}
        self._last_team_context: TeamContext = TeamContext()
        self._last_pattern_winner: Optional[str] = None
        self._last_pattern_payload: Dict[str, Any] = {}
        # Step-8 aggregation strategy. ``"default"`` runs the LLM
        # synthesis path. ``"python_reduce"`` hands per-source node
        # results to the team's PYTHON-tool agent so deterministic
        # reductions (counts, sums, averages, dedup) happen in code,
        # not in an LLM. Set by patterns/helpers that build broadcast
        # subtasks; falls back to ``"default"`` when no PYTHON agent
        # is on the team.
        self._current_aggregation_strategy: str = "default"
        self._current_aggregation_instructions: str = ""

    # ------------------------------------------------------------------
    # Agent DB-ID resolver
    # ------------------------------------------------------------------
    def _resolve_agent_db_id(self, agent: Optional[Agent]) -> Optional[int]:
        """Return the MySQL integer agents.id for the given Agent.

        Agent.agent_id is a UUID string; memory/scoring rows require the integer
        primary key. Looks it up from MySQL and caches on the Agent instance and
        in the per-pipeline cache. Returns None when unresolvable — callers must
        SKIP writes rather than fall back to a phantom id.
        """
        if agent is None:
            return None
        if agent.db_id is not None:
            return agent.db_id
        if agent.agent_id and agent.agent_id.isdigit():
            agent.db_id = int(agent.agent_id)
            return agent.db_id
        cached = self._agent_db_id_cache.get(agent.agent_id or "")
        if cached is not None:
            agent.db_id = cached
            return cached
        uuid_or_name = agent.agent_id or agent.name
        if not uuid_or_name:
            return None
        try:
            conn = mysql.connector.connect(
                host=settings.mysql_host,
                port=settings.mysql_port,
                user=settings.mysql_user,
                password=settings.mysql_password,
                database=settings.mysql_db,
                connection_timeout=3,
            )
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT id FROM agents WHERE agent_id = %s OR name = %s LIMIT 1",
                    (uuid_or_name, agent.name or uuid_or_name),
                )
                row = cur.fetchone()
                cur.close()
                if row:
                    db_id = int(row[0])
                    agent.db_id = db_id
                    self._agent_db_id_cache[agent.agent_id or ""] = db_id
                    return db_id
            finally:
                conn.close()
        except Exception as exc:
            logger.warning(
                "agent_db_id_lookup_failed",
                layer="service",
                agent_id=agent.agent_id,
                agent_name=agent.name,
                error=str(exc),
            )
        return None

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def execute(
        self,
        conversation_id: str,
        message: str,
        team_id: str,
        trace_id: str = "",
    ) -> Dict[str, Any]:
        """Run the full pipeline and return the assembled result."""
        session_id = str(uuid.uuid4())
        trace_id = trace_id or str(uuid.uuid4())
        start_time = time.monotonic()

        # Store context for sub-agent spawning
        self._current_team_id = team_id
        self._current_conversation_id = conversation_id
        # Reset schema-meta override so stale state from a prior turn on
        # this pipeline instance can't leak into bidding.
        self._current_schema_meta_assignments = {}
        self._current_schema_meta_descriptions: set = set()
        # Reset dispatcher scratch — see __init__.
        self._last_translation = {}
        self._last_team_context = TeamContext()
        self._last_pattern_winner = None
        self._last_pattern_payload = {}
        self._current_aggregation_strategy = "default"
        self._current_aggregation_instructions = ""

        logger.info(
            "Pipeline execution started",
            layer="service",
            session_id=session_id,
            conversation_id=conversation_id,
            trace_id=trace_id,
        )

        # Audit: pipeline intake
        try:
            await audit.write(
                trace_id=trace_id,
                actor="orchestrator",
                actor_type="SERVICE",
                action="pipeline.intake",
                resource_type="Conversation",
                resource_id=conversation_id,
                payload={
                    "session_id": session_id,
                    "team_id": team_id,
                    "message_len": len(message or ""),
                },
            )
        except Exception:
            pass

        # ── Pending-report-confirm short-circuit ─────────────────────────
        # If the previous turn asked the user to confirm a Report match, the
        # current turn's reply ("yes" / "data" / refinement) determines the
        # action here. Always clear the pending state so we do not loop.
        # ``skip_report_match`` is a one-shot guard so a "no" reply does not
        # re-trigger the same confirm prompt on the same turn.
        skip_report_match = False
        pending = self._get_pending_report_confirm(conversation_id)
        if pending and pending.get("report_id"):
            self._clear_pending_report_confirm(conversation_id)
            reply_kind = self._classify_confirm_reply(message)
            logger.info(
                "Pending report-confirm reply",
                layer="service",
                conversation_id=conversation_id,
                report_id=pending.get("report_id"),
                reply_kind=reply_kind,
                trace_id=trace_id,
            )
            if reply_kind == "yes":
                # Re-fetch the matched-report record from Neo4j so we have
                # the full datasets / commands needed by _execute_matched_report.
                try:
                    rows = await self._neo4j.run_query(
                        """
                        MATCH (r:Report {report_id: $report_id})
                        OPTIONAL MATCH (r)-[:HAS_DATASET]->(rd:ReportDataset)
                        OPTIONAL MATCH (rd)-[:RUNS_ON]->(ds:DataSource)
                        RETURN r.report_id   AS report_id,
                               r.name        AS name,
                               r.description AS description,
                               r.system      AS system,
                               r.owner_team  AS owner_team,
                               collect(DISTINCT {
                                 dataset_id: rd.dataset_id,
                                 name: rd.name,
                                 command: rd.command,
                                 command_type: rd.command_type,
                                 source_uri: ds.source_uri,
                                 source_name: ds.source_name
                               }) AS datasets
                        """,
                        {"report_id": pending["report_id"]},
                        trace_id=trace_id,
                    )
                except Exception as exc:
                    rows = []
                    logger.warning(
                        "Failed to load confirmed report",
                        layer="service", error=str(exc), trace_id=trace_id,
                    )
                if rows:
                    report = rows[0]
                    report["datasets"] = [
                        d for d in (report.get("datasets") or [])
                        if d and d.get("dataset_id")
                    ]
                    report_response, report_visualizations = (
                        await self._execute_matched_report(report, trace_id=trace_id)
                    )
                    try:
                        await audit.write(
                            trace_id=trace_id,
                            actor="orchestrator",
                            actor_type="SERVICE",
                            action="report.executed",
                            resource_type="Report",
                            resource_id=pending["report_id"],
                            payload={
                                "session_id": session_id,
                                "via": "user_confirm",
                                "score": pending.get("score"),
                            },
                        )
                    except Exception:
                        pass
                    return {
                        "session_id": session_id,
                        "graph_id": "",
                        "response": report_response,
                        "score": None,
                        "trace_id": trace_id,
                        "clarification_needed": False,
                        "clarification_question": None,
                        "auditor_issue_id": None,
                        "auditor_issue_kind": None,
                        "matched_report_id": pending["report_id"],
                        "visualizations": report_visualizations,
                    }
                # If we somehow lost the report row, fall through to the
                # agent loop on the user's reply text rather than failing.
            elif reply_kind == "no":
                # Replay the user's ORIGINAL question through the agent loop.
                # Skip report-matching for this turn — otherwise the same
                # report would re-match and we would re-prompt indefinitely.
                original = pending.get("original_question") or message
                logger.info(
                    "User declined report; running agent path on original question",
                    layer="service", conversation_id=conversation_id,
                    trace_id=trace_id,
                )
                message = original
                skip_report_match = True
            # reply_kind == "other" → treat as a refinement; fall through
            # with the new message text. Pending is already cleared above.

        try:
            # Step 0: LOAD TEAM HIERARCHY into Neo4j + build team context
            team_context = ""
            if team_id:
                team_context = await self._load_team_hierarchy(
                    team_id=team_id,
                    conversation_id=conversation_id,
                    trace_id=trace_id,
                ) or ""

            # Phase C.3: pull prior-turn user feedback for this conversation
            # and prepend it to the team context. The agents downstream see
            # "user pushed back on X on prior turn" before they plan, which
            # is the cheapest signal we have for "don't do that again".
            feedback_block = await self._fetch_recent_user_feedback(
                conversation_id=conversation_id, limit=5, trace_id=trace_id,
            )
            if feedback_block:
                team_context = (team_context + "\n\n" + feedback_block).strip()

            # Step 1: REQUEST INTAKE
            graph_id, sop_context = await self._step1_intake(
                session_id=session_id,
                conversation_id=conversation_id,
                message=message,
                team_id=team_id,
                trace_id=trace_id,
            )

            # Step 2: GRAPH CONSTRUCTION
            root_node_id, node_descriptions = await self._step2_graph_construction(
                graph_id=graph_id,
                message=message,
                team_id=team_id,
                sop_context=sop_context,
                trace_id=trace_id,
                team_context=team_context,
                conversation_id=conversation_id,
            )

            # Step 2b: PATTERN DISPATCH.
            # Runs every registered pattern's detect() in parallel,
            # stamps a DecisionTrace on the TaskGraph for the UI, and
            # caches the winner so the gates below can defer to it
            # (Phase 4 cutover). When dispatch fails or routing is
            # disabled, the legacy gates re-derive from translator
            # output as before.
            try:
                prior_turns_for_dispatch = await self._fetch_prior_turns_from_messages(
                    conversation_id=conversation_id, trace_id=trace_id,
                )
            except Exception:
                prior_turns_for_dispatch = []
            await self._run_pattern_dispatch(
                graph_id=graph_id,
                message=message,
                team_id=team_id,
                conversation_id=conversation_id,
                session_id=session_id,
                trace_id=trace_id,
                prior_turns=prior_turns_for_dispatch,
            )

            # Read translator metadata once — both the deterministic-Report
            # path and the clarification path consume it.
            try:
                meta_rows = await self._neo4j.run_query(
                    """
                    MATCH (g:TaskGraph {graph_id: $graph_id})
                    RETURN g.translator_clarification_need AS need,
                           g.translator_clarification      AS question,
                           g.translator_auditor_issue_id   AS issue_id,
                           g.translator_auditor_issue_kind AS issue_kind,
                           g.translator_matched_reports    AS reports
                    """,
                    {"graph_id": graph_id},
                    trace_id=trace_id,
                )
            except Exception:
                meta_rows = []
            meta = meta_rows[0] if meta_rows else {}

            matched_reports: List[Dict[str, Any]] = []
            try:
                matched_reports = json.loads(meta.get("reports") or "[]")
            except Exception:
                matched_reports = []

            # Ext2 — deterministic Report path. Two thresholds instead of one:
            #   AUTO_FIRE: high-confidence match -> execute report silently.
            #   CONFIRM:   middle-band match    -> ask the user before firing.
            #   below:     ignore reports, run the agent loop normally.
            # The confirm gate prevents the scorer-misfire failure mode where
            # a question about graph data accidentally matches a SQL report by
            # ambient token overlap (e.g. "and"/"payment").
            AUTO_FIRE_THRESHOLD = 12.0
            CONFIRM_THRESHOLD = 5.0
            top_match = matched_reports[0] if matched_reports else None
            top_score = float(top_match.get("score") or 0.0) if top_match else 0.0
            second_score = float(matched_reports[1].get("score") or 0.0) if len(matched_reports) > 1 else 0.0

            # Phase 4 — defer the Report band classification to the
            # dispatcher when routing is enabled. We still recompute the
            # legacy thresholds locally so the path stays correct when
            # dispatch failed (winner=None) or is in shadow mode.
            dispatcher_says_report = (
                self._pattern_routing_enabled
                and self._last_pattern_winner == "report"
            )
            dispatcher_report_kind = (
                str(self._last_pattern_payload.get("kind") or "")
                if dispatcher_says_report else ""
            )
            legacy_auto_fire = bool(
                top_match
                and top_score >= AUTO_FIRE_THRESHOLD
                and (top_score - second_score) >= 1.0
            )
            legacy_confirm = bool(
                top_match and top_score >= CONFIRM_THRESHOLD
            )
            should_auto_fire = (
                dispatcher_report_kind == "auto_fire"
                if dispatcher_says_report
                else legacy_auto_fire
            )
            should_confirm = (
                dispatcher_report_kind == "confirm"
                if dispatcher_says_report
                else legacy_confirm
            )

            if (
                not skip_report_match
                and top_match
                and should_auto_fire
            ):
                logger.info(
                    "Pipeline short-circuited for deterministic Report",
                    layer="service",
                    graph_id=graph_id,
                    report_id=top_match.get("report_id"),
                    score=top_score,
                    trace_id=trace_id,
                )
                report_response, report_visualizations = await self._execute_matched_report(
                    top_match, trace_id=trace_id,
                )
                await self._neo4j.update_graph_status(
                    graph_id, "REPORT_EXECUTED", trace_id=trace_id,
                )
                try:
                    await audit.write(
                        trace_id=trace_id,
                        actor="orchestrator",
                        actor_type="SERVICE",
                        action="report.executed",
                        resource_type="Report",
                        resource_id=top_match.get("report_id"),
                        payload={
                            "graph_id": graph_id,
                            "score": top_score,
                            "owner_team": top_match.get("owner_team"),
                            "system": top_match.get("system"),
                        },
                    )
                except Exception:
                    pass
                return {
                    "session_id": session_id,
                    "graph_id": graph_id,
                    "response": report_response,
                    "score": None,
                    "trace_id": trace_id,
                    "clarification_needed": False,
                    "clarification_question": None,
                    "auditor_issue_id": None,
                    "auditor_issue_kind": None,
                    "matched_report_id": top_match.get("report_id"),
                    "visualizations": report_visualizations,
                }

            if (
                not skip_report_match
                and top_match
                and should_confirm
            ):
                # Confirm-band match — ask the user before firing the report.
                # Persist pending state on the conversation so the next turn
                # can act on the user's reply (yes / no / refined question).
                report_name = top_match.get("name") or "(unnamed report)"
                confirm_msg = (
                    f"I found a saved report **'{report_name}'** that may answer your question. "
                    f"Reply **yes** to use the report, or **data** to have me look up the data directly. "
                    f"You can also restate or refine your question."
                )
                self._set_pending_report_confirm(
                    conversation_id=conversation_id,
                    report_id=top_match.get("report_id"),
                    report_name=report_name,
                    score=top_score,
                    original_question=message,
                )
                await self._neo4j.update_graph_status(
                    graph_id, "AWAITING_REPORT_CONFIRM", trace_id=trace_id,
                )
                logger.info(
                    "Pipeline asking user to confirm Report match",
                    layer="service",
                    graph_id=graph_id,
                    report_id=top_match.get("report_id"),
                    score=top_score,
                    trace_id=trace_id,
                )
                try:
                    await audit.write(
                        trace_id=trace_id,
                        actor="orchestrator",
                        actor_type="SERVICE",
                        action="report.confirm_requested",
                        resource_type="Report",
                        resource_id=top_match.get("report_id"),
                        payload={
                            "graph_id": graph_id,
                            "score": top_score,
                            "owner_team": top_match.get("owner_team"),
                            "system": top_match.get("system"),
                        },
                    )
                except Exception:
                    pass
                return {
                    "session_id": session_id,
                    "graph_id": graph_id,
                    "response": confirm_msg,
                    "score": None,
                    "trace_id": trace_id,
                    "clarification_needed": True,
                    "clarification_question": confirm_msg,
                    "clarification_kind": "report_confirm",
                    "pending_report_id": top_match.get("report_id"),
                    "auditor_issue_id": None,
                    "auditor_issue_kind": None,
                }

            # F4 — clarification short-circuit. Phase 4: prefer the
            # dispatcher's verdict; fall back to the translator-meta
            # read when routing is disabled or dispatch failed.
            dispatcher_says_clarify = (
                self._pattern_routing_enabled
                and self._last_pattern_winner == "clarify"
            )
            legacy_clarify = bool(meta and meta.get("need") and meta.get("question"))
            should_clarify = (
                dispatcher_says_clarify
                if self._pattern_routing_enabled and self._last_pattern_winner is not None
                else legacy_clarify
            )
            if should_clarify and meta and meta.get("question"):
                await self._neo4j.update_graph_status(
                    graph_id, "AWAITING_CLARIFICATION", trace_id=trace_id,
                )
                logger.info(
                    "Pipeline short-circuited for clarification",
                    layer="service",
                    graph_id=graph_id,
                    auditor_issue_id=meta.get("issue_id"),
                    trace_id=trace_id,
                )
                return {
                    "session_id": session_id,
                    "graph_id": graph_id,
                    "response": meta.get("question"),
                    "score": None,
                    "trace_id": trace_id,
                    "clarification_needed": True,
                    "clarification_question": meta.get("question"),
                    "auditor_issue_id": meta.get("issue_id"),
                    "auditor_issue_kind": meta.get("issue_kind"),
                }

            # Audit: decomposition done
            try:
                await audit.write(
                    trace_id=trace_id,
                    actor="orchestrator",
                    actor_type="SERVICE",
                    action="pipeline.decomposed",
                    resource_type="TaskGraph",
                    resource_id=graph_id,
                    payload={
                        "subtask_count": len(node_descriptions or []),
                        "ontology_used": bool(sop_context),
                    },
                )
            except Exception:
                pass

            # Step 3: PRE-EXECUTION VALIDATION + CAPABILITY NEGOTIATION
            primary, fallbacks = await self._step3_validation(
                team_id=team_id,
                trace_id=trace_id,
            )

            # Capability Negotiation: broadcast bids for each subtask
            all_agents = ([primary] if primary else []) + fallbacks
            negotiation_results: Dict[str, NegotiationResult] = {}
            bandit_decisions: Dict[str, BanditDecision] = {}
            agent_assignments: Dict[str, Agent] = {}

            if all_agents and node_descriptions:
                # Schema-meta path: every subtask was already pre-assigned
                # by _step2_graph_construction to a specific agent based on
                # its DATABASE/GRAPH tools. Bidding here would burn ~15s
                # per subtask × N subtasks (LLM bid timeouts) and the
                # winner would be overridden anyway. Skip negotiation.
                sm_overrides = getattr(self, "_current_schema_meta_assignments", None) or {}
                sm_only_run = bool(sm_overrides) and all(
                    desc in sm_overrides for desc in node_descriptions
                )

                if not sm_only_run:
                    negotiation_results, bandit_decisions = await self._step3_negotiate(
                        graph_id=graph_id,
                        node_descriptions=node_descriptions,
                        team_agents=all_agents,
                        trace_id=trace_id,
                        team_id=team_id,
                        session_id=session_id,
                    )
                    # Build agent assignments from negotiation winners
                    for desc, neg_result in negotiation_results.items():
                        if neg_result.winner:
                            # Find the matching Agent object
                            winner_agent = next(
                                (a for a in all_agents if a.agent_id == neg_result.winner.agent_id),
                                None,
                            )
                            if winner_agent:
                                agent_assignments[desc] = winner_agent
                else:
                    logger.info(
                        "Skipping capability negotiation — every subtask is "
                        "pre-assigned by schema-meta broadcast",
                        layer="service",
                        graph_id=graph_id,
                        subtask_count=len(node_descriptions),
                        trace_id=trace_id,
                    )

                # Schema-meta override. When the translator detected a
                # catalog-shape question, _step2 built per-agent broadcast
                # subtasks each tagged with its target agent_id. Force
                # the assignment to that agent so a stray bid winner can't
                # claim a subtask intended for someone else.
                if sm_overrides:
                    for desc, target_aid in sm_overrides.items():
                        target = next(
                            (a for a in all_agents if a.agent_id == target_aid),
                            None,
                        )
                        if target:
                            agent_assignments[desc] = target
                    # Clear so later turns on this pipeline instance start fresh.
                    self._current_schema_meta_assignments = {}

            # Step 4-7: EXECUTION loop (with correction + expansion)
            node_results = await self._step4_to_7_execution(
                graph_id=graph_id,
                root_node_id=root_node_id,
                node_descriptions=node_descriptions,
                primary=primary,
                fallbacks=fallbacks,
                message=message,
                trace_id=trace_id,
                agent_assignments=agent_assignments,
                negotiation_results=negotiation_results,
                team_context=team_context,
            )

            # Bandit reward back-fill: for each node result we have a score,
            # feed it back to the bandit so its per-(agent, context) Beta
            # distributions update. Runs after execution so the current request
            # path is not blocked.
            if bandit_decisions:
                for nr in node_results:
                    desc = nr.get("description") or ""
                    decision = bandit_decisions.get(desc)
                    if not decision:
                        continue
                    score = nr.get("score")
                    if score is None:
                        continue
                    try:
                        self._bandit.record_reward(
                            decision_id=decision.decision_id,
                            reward=float(score),
                            trace_id=trace_id,
                        )
                    except Exception as exc:
                        logger.warning(
                            "Bandit reward update failed (non-fatal)",
                            layer="service",
                            decision_id=decision.decision_id,
                            error=str(exc),
                            trace_id=trace_id,
                        )

            # Learned-scorer shadow predictions (1B). Runs once per node_result,
            # logs to learned_scorer_predictions for later comparison against the
            # heuristic scorer. Never blocks on failure.
            if self._learned_scorer.is_loaded():
                for nr in node_results:
                    try:
                        score_val = nr.get("score")
                        if score_val is None:
                            continue
                        self._learned_scorer.predict_and_log(
                            ctx={
                                "content": nr.get("llm_response") or "",
                                "heuristic_score": float(score_val),
                                "latency_ms": int(nr.get("latency_ms") or 0),
                                "tool_call_count": len(nr.get("tools_used") or []),
                                "n_task_nodes": len(node_results),
                                "context_len_chars": len(message or ""),
                                "graph_depth": 1,
                            },
                            trace_id=trace_id,
                            session_id=session_id,
                            graph_id=graph_id,
                            node_id=str(nr.get("node_id") or ""),
                            agent_id=str(nr.get("agent_id") or ""),
                            agent_name=str(nr.get("agent_name") or ""),
                            heuristic_score=float(score_val),
                        )
                    except Exception as exc:
                        logger.warning(
                            "LearnedScorer shadow prediction failed (non-fatal)",
                            layer="service",
                            error=str(exc),
                            trace_id=trace_id,
                        )

            # Step 8: AGGREGATION. Strategy is set by whoever built the
            # subtasks (patterns, broadcast helpers); falls back to
            # ``"default"`` LLM synthesis when nothing opted in.
            if self._current_aggregation_strategy == "python_reduce":
                final_response = await self._step8_python_reduce(
                    message=message,
                    node_results=node_results,
                    graph_id=graph_id,
                    primary=primary,
                    trace_id=trace_id,
                    instructions=self._current_aggregation_instructions or "",
                )
            else:
                final_response = await self._step8_aggregation(
                    message=message,
                    node_results=node_results,
                    graph_id=graph_id,
                    primary=primary,
                    trace_id=trace_id,
                )

            # ─────────────────────────────────────────────────────────────
            # Phase A.4: PERPETUAL OUTER LOOP (sufficiency gate + delta
            # re-decomposition). Round 1 was the initial decomposition above.
            # Subsequent rounds:
            #   1) ask the sufficiency judge whether the team has fully
            #      addressed the user's question;
            #   2) if not, slim-decompose the gaps into 1-3 NEW SUBTASK nodes;
            #   3) negotiate bids for the new nodes;
            #   4) re-execute steps 4-7 (status filter ensures only the new
            #      PENDING nodes run);
            #   5) re-aggregate over ALL accumulated node_results.
            # Bounded by self.MAX_OUTER_ROUNDS (default 3) and a no-op short-
            # circuit when the judge fails or returns no actionable gaps.
            # Every step publishes a typed event so the UI timeline can
            # render the deviation with its reason.
            # ─────────────────────────────────────────────────────────────
            sufficient = True
            judge_meta: Dict[str, Any] = {}
            outer_round_final = 1

            # Pull the detected intent for the judge's prompt (best-effort).
            _intent_for_judge = ""
            try:
                _last = getattr(self, "_last_translation", {}) or {}
                _intent_for_judge = (_last.get("intent") or "")
            except Exception:
                _intent_for_judge = ""

            # Emit decomposition.created (initial round, iteration 0) so the
            # timeline UI can pin the original sub-task list at the top.
            try:
                from app.utils.events import events as _events
                await _events.publish(
                    conversation_id=conversation_id,
                    kind="decomposition.created",
                    trace_id=trace_id,
                    graph_id=graph_id,
                    iteration=0,
                    round_n=1,
                    payload={
                        "intent": _intent_for_judge,
                        "subtasks": list(node_descriptions or [])[:30],
                        "n_subtasks": len(node_descriptions or []),
                    },
                )
            except Exception:
                pass

            # Phase B.2: track avg score across rounds so we can short-
            # circuit when the team is not actually getting better. The
            # initial round's avg is set just below before the loop opens.
            score_history: List[float] = []

            # Loop bounds: rounds 2..MAX. Round 1 already happened above.
            for outer_round in range(2, self.MAX_OUTER_ROUNDS + 1):
                # 1) Sufficiency judge
                judge = await self._sufficiency_judge(
                    user_message=message,
                    intent=_intent_for_judge,
                    node_results=node_results,
                    final_response=final_response,
                    round_n=outer_round - 1,
                    trace_id=trace_id,
                )
                judge_meta = judge

                # Phase B.2: append this round's avg score to history and
                # check for a plateau. We need at least two prior rounds
                # (so history has 2+ entries) before the check kicks in.
                _avg_now = judge.get("avg_score")
                if _avg_now is not None:
                    score_history.append(float(_avg_now))
                plateau_hit = False
                if len(score_history) >= 2:
                    delta = score_history[-1] - score_history[-2]
                    if delta < self.PLATEAU_EPSILON:
                        plateau_hit = True
                        logger.info(
                            "Outer-loop plateau — score not improving across rounds",
                            layer="service",
                            graph_id=graph_id,
                            round=outer_round - 1,
                            history=score_history,
                            delta=delta,
                            epsilon=self.PLATEAU_EPSILON,
                            trace_id=trace_id,
                        )

                try:
                    from app.utils.events import events as _events
                    await _events.publish(
                        conversation_id=conversation_id,
                        kind="sufficiency.checked",
                        trace_id=trace_id,
                        graph_id=graph_id,
                        round_n=outer_round - 1,
                        status="SUCCESS" if judge["sufficient"] else "DEVIATED",
                        payload={
                            "sufficient": judge["sufficient"],
                            "gaps": judge.get("gaps") or [],
                            "reason": judge.get("reason") or "",
                            "avg_score": judge.get("avg_score"),
                            "below_band_count": judge.get("below_band_count"),
                        },
                    )
                except Exception:
                    pass

                if judge["sufficient"]:
                    sufficient = True
                    outer_round_final = outer_round - 1
                    break

                # Phase B.2: plateau gate — bail early if more iterations
                # are unlikely to help. The judge's `sufficient=False` is
                # respected upstream, so accepting here means "best-effort,
                # not enough capability to close the gap".
                if plateau_hit:
                    sufficient = False
                    outer_round_final = outer_round - 1
                    judge_meta = {
                        **judge,
                        "reason": (
                            f"plateau: score history={score_history} "
                            f"(epsilon={self.PLATEAU_EPSILON}). " + (judge.get("reason") or "")
                        ),
                    }
                    break

                # 2) Delta re-decompose: convert gaps into new SUBTASK nodes
                prior_summary_lines: List[str] = []
                for nr in node_results[-10:]:
                    desc = (nr.get("description") or "")[:120]
                    sc = nr.get("score")
                    prior_summary_lines.append(f"- [{sc}] {desc}")
                prior_summary = "\n".join(prior_summary_lines)

                new_descs = await self._delta_decompose(
                    graph_id=graph_id,
                    root_node_id=root_node_id,
                    user_message=message,
                    intent=_intent_for_judge,
                    gaps=judge.get("gaps") or [],
                    prior_findings_summary=prior_summary,
                    round_n=outer_round,
                    trace_id=trace_id,
                )

                try:
                    from app.utils.events import events as _events
                    await _events.publish(
                        conversation_id=conversation_id,
                        kind="decomposition.revised",
                        trace_id=trace_id,
                        graph_id=graph_id,
                        round_n=outer_round,
                        status="DEVIATED",
                        payload={
                            "round": outer_round,
                            "gaps": judge.get("gaps") or [],
                            "reason": judge.get("reason") or "",
                            "new_subtasks": new_descs,
                            "avg_score": judge.get("avg_score"),
                            "below_band_count": judge.get("below_band_count"),
                        },
                    )
                except Exception:
                    pass

                if not new_descs:
                    # Judge said insufficient but couldn't propose new tasks —
                    # nothing more we can do; accept the current answer.
                    sufficient = False
                    outer_round_final = outer_round - 1
                    break

                # 3) Negotiate bids for the new descriptions only
                delta_negotiation: Dict[str, NegotiationResult] = {}
                delta_assignments: Dict[str, Agent] = {}
                if all_agents:
                    try:
                        delta_negotiation, _ = await self._step3_negotiate(
                            graph_id=graph_id,
                            node_descriptions=new_descs,
                            team_agents=all_agents,
                            trace_id=trace_id,
                            team_id=team_id,
                            session_id=session_id,
                            round_n=outer_round,
                        )
                        for desc, neg in delta_negotiation.items():
                            if neg.winner:
                                w = next(
                                    (a for a in all_agents
                                     if a.agent_id == neg.winner.agent_id),
                                    None,
                                )
                                if w:
                                    delta_assignments[desc] = w
                    except Exception as exc:
                        logger.warning(
                            "delta_negotiation_failed",
                            layer="service",
                            error=str(exc)[:300],
                            trace_id=trace_id,
                        )

                # 4) Execute the new PENDING nodes; the status filter inside
                #    _step4_to_7_execution skips already-completed nodes.
                delta_results = await self._step4_to_7_execution(
                    graph_id=graph_id,
                    root_node_id=root_node_id,
                    node_descriptions=new_descs,
                    primary=primary,
                    fallbacks=fallbacks,
                    message=message,
                    trace_id=trace_id,
                    agent_assignments=delta_assignments,
                    negotiation_results=delta_negotiation,
                    team_context=team_context,
                )
                node_results.extend(delta_results)

                # 5) Re-aggregate using whichever strategy was selected.
                if self._current_aggregation_strategy == "python_reduce":
                    final_response = await self._step8_python_reduce(
                        message=message,
                        node_results=node_results,
                        graph_id=graph_id,
                        primary=primary,
                        trace_id=trace_id,
                        instructions=self._current_aggregation_instructions or "",
                    )
                else:
                    final_response = await self._step8_aggregation(
                        message=message,
                        node_results=node_results,
                        graph_id=graph_id,
                        primary=primary,
                        trace_id=trace_id,
                    )

                outer_round_final = outer_round
                # Loop continues — next round's sufficiency check decides.

            # Final sufficiency event when the loop runs through all rounds
            # without breaking (i.e. cap reached but still insufficient).
            if outer_round_final >= self.MAX_OUTER_ROUNDS and not judge_meta.get("sufficient", True):
                sufficient = False

            # Step 9: RESPONSE & LEARNING
            primary_db_id = self._resolve_agent_db_id(primary)
            if primary_db_id is None:
                logger.warning(
                    "step9_skipped_no_agent_db_id",
                    layer="service",
                    trace_id=trace_id,
                    agent_uuid=(primary.agent_id if primary else None),
                )
            else:
                await self._step9_learning(
                    session_id=session_id,
                    graph_id=graph_id,
                    agent_id=primary_db_id,
                    final_response=final_response,
                    node_results=node_results,
                    trace_id=trace_id,
                    task_description=message,
                )

            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            logger.info(
                "Pipeline execution completed",
                layer="service",
                session_id=session_id,
                graph_id=graph_id,
                duration_ms=elapsed_ms,
                trace_id=trace_id,
            )
            REQUEST_TOTAL.labels(method="POST", path="/v1/orchestrator/chat", status="200").inc()

            # Audit: final response sent
            try:
                _scores = [
                    nr.get("score") for nr in (node_results or [])
                    if nr.get("score") is not None
                ]
                _avg = (sum(_scores) / len(_scores)) if _scores else None
                await audit.write(
                    trace_id=trace_id,
                    actor="orchestrator",
                    actor_type="SERVICE",
                    action="pipeline.responded",
                    resource_type="TaskGraph",
                    resource_id=graph_id,
                    payload={
                        "avg_score": _avg,
                        "length": len(final_response or ""),
                        "duration_ms": elapsed_ms,
                        "n_nodes": len(node_results or []),
                    },
                )
            except Exception:
                pass

            # Pull translator metadata once more so the chat response can
            # surface SYNONYM_AMBIGUITY auditor_issue_ids even when we DIDN'T
            # short-circuit (e.g. translator answered both sides but flagged
            # them as synonyms for steward review).
            issue_id = None
            issue_kind = None
            try:
                meta_rows = await self._neo4j.run_query(
                    """MATCH (g:TaskGraph {graph_id: $graph_id})
                       RETURN g.translator_auditor_issue_id AS issue_id,
                              g.translator_auditor_issue_kind AS issue_kind""",
                    {"graph_id": graph_id},
                    trace_id=trace_id,
                )
                if meta_rows:
                    issue_id = meta_rows[0].get("issue_id")
                    issue_kind = meta_rows[0].get("issue_kind")
            except Exception:
                pass

            # ──────────────────────────────────────────────────────────────
            # Phase C.2: persist durable learning artifacts at the end of a
            # successful (or best-effort capped) run. The writes are
            # best-effort; failures are logged but don't break the response.
            # We learn the most when sufficient=True; on cap-reached we
            # still record the decomposition so the next similar question
            # can see what was tried.
            # ──────────────────────────────────────────────────────────────
            try:
                from app.services import learning as _learning
                from app.utils.events import events as _events_for_learn

                # 1) Effective decomposition (all rounds combined into the
                #    final sub-task list as it stood at the end of the run).
                final_subtasks: List[str] = list(node_descriptions or [])
                # Pull any delta nodes added during outer-loop rounds.
                try:
                    extras = await self._neo4j.run_query(
                        """
                        MATCH (n:TaskNode {graph_id: $graph_id})
                        WHERE n.node_type = 'SUBTASK'
                        RETURN n.description AS desc, n.iteration AS it
                        ORDER BY n.iteration ASC, n.created_at ASC
                        """,
                        {"graph_id": graph_id},
                        trace_id=trace_id,
                    )
                    if extras:
                        final_subtasks = [
                            (r.get("desc") or "")[:500]
                            for r in extras if r.get("desc")
                        ]
                except Exception:
                    pass

                _scores_now = [
                    float(nr.get("score")) for nr in (node_results or [])
                    if nr.get("score") is not None
                ]
                _avg_now = (sum(_scores_now) / len(_scores_now)) if _scores_now else None

                if sufficient and final_subtasks:
                    n_dec = await _learning.write_effective_decomposition({
                        "conversation_id": conversation_id,
                        "graph_id": graph_id,
                        "intent": _intent_for_judge,
                        "user_question": message,
                        "subtask_list": final_subtasks,
                        "n_subtasks": len(final_subtasks),
                        "rounds_to_success": outer_round_final or 1,
                        "avg_score": _avg_now,
                    })
                    if n_dec:
                        try:
                            await _events_for_learn.publish(
                                conversation_id=conversation_id,
                                kind="memory.written",
                                trace_id=trace_id,
                                graph_id=graph_id,
                                round_n=outer_round_final or 1,
                                status="SUCCESS",
                                payload={
                                    "artifact_kind": "effective_decomposition",
                                    "key": _intent_for_judge or "unknown",
                                    "n_subtasks": len(final_subtasks),
                                    "rows": n_dec,
                                },
                            )
                        except Exception:
                            pass

                # 2) Agent-tool affinity from successful node results.
                affinity = _learning.affinity_rows_from_results(
                    node_results or [],
                    graph_id=graph_id,
                    intent=_intent_for_judge,
                )
                if affinity:
                    n_aff = await _learning.write_agent_tool_affinity(affinity)
                    if n_aff:
                        try:
                            await _events_for_learn.publish(
                                conversation_id=conversation_id,
                                kind="memory.written",
                                trace_id=trace_id,
                                graph_id=graph_id,
                                round_n=outer_round_final or 1,
                                status="SUCCESS",
                                payload={
                                    "artifact_kind": "agent_tool_affinity",
                                    "key": _intent_for_judge or "unknown",
                                    "rows": n_aff,
                                },
                            )
                        except Exception:
                            pass

                # 3) Entity resolutions used by the team. We surface only
                #    the canonical entities that came back from the
                #    translator (already grounded against the ontology) —
                #    those are the ones a future turn can reuse.
                ent_rows: List[Dict[str, Any]] = []
                try:
                    last_t = getattr(self, "_last_translation", {}) or {}
                    for ce in (last_t.get("canonical_entities") or [])[:20]:
                        if not isinstance(ce, str) or not ce.strip():
                            continue
                        ent_rows.append({
                            "conversation_id": conversation_id,
                            "graph_id": graph_id,
                            "intent": _intent_for_judge or None,
                            "raw_phrase": (message or "")[:500],
                            "canonical_entity": ce.strip()[:500],
                            "ontology_version": (
                                (last_t.get("ontology_versions") or [None])[0]
                                if last_t.get("ontology_versions") else None
                            ),
                            "score": _avg_now,
                            "source": "translator",
                        })
                except Exception:
                    ent_rows = []
                if ent_rows:
                    n_ent = await _learning.write_entity_resolutions(ent_rows)
                    if n_ent:
                        try:
                            await _events_for_learn.publish(
                                conversation_id=conversation_id,
                                kind="memory.written",
                                trace_id=trace_id,
                                graph_id=graph_id,
                                round_n=outer_round_final or 1,
                                status="SUCCESS",
                                payload={
                                    "artifact_kind": "entity_resolution",
                                    "key": _intent_for_judge or "unknown",
                                    "rows": n_ent,
                                },
                            )
                        except Exception:
                            pass
            except Exception as _learn_exc:
                # Never let learning writes break the live response.
                try:
                    logger.warning(
                        "learning_artifacts_phase_failed",
                        layer="service",
                        error=str(_learn_exc)[:300],
                        trace_id=trace_id,
                    )
                except Exception:
                    pass

            # Phase A: emit pipeline.completed for the timeline UI.
            try:
                from app.utils.events import events as _events
                _final_scores = [
                    nr.get("score") for nr in (node_results or [])
                    if nr.get("score") is not None
                ]
                _final_avg = (
                    sum(_final_scores) / len(_final_scores)
                ) if _final_scores else None
                await _events.publish(
                    conversation_id=conversation_id,
                    kind="pipeline.completed",
                    trace_id=trace_id,
                    graph_id=graph_id,
                    round_n=outer_round_final,
                    status="COMPLETE" if sufficient else "DEVIATED",
                    payload={
                        "sufficient": sufficient,
                        "rounds": outer_round_final,
                        "n_nodes": len(node_results or []),
                        "avg_score": _final_avg,
                        "duration_ms": elapsed_ms,
                        "judge_reason": (judge_meta.get("reason") or "")[:300],
                        "remaining_gaps": (judge_meta.get("gaps") or [])[:8],
                    },
                )
            except Exception:
                pass

            return {
                "session_id": session_id,
                "graph_id": graph_id,
                "response": final_response,
                "score": node_results[-1].get("score") if node_results else None,
                "trace_id": trace_id,
                "clarification_needed": False,
                "clarification_question": None,
                "auditor_issue_id": issue_id,
                "auditor_issue_kind": issue_kind,
                "outer_rounds": outer_round_final,
                "sufficient": sufficient,
            }

        except Exception as exc:
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            logger.error(
                "Pipeline execution failed",
                layer="service",
                session_id=session_id,
                error=str(exc),
                duration_ms=elapsed_ms,
                trace_id=trace_id,
            )
            REQUEST_TOTAL.labels(method="POST", path="/v1/orchestrator/chat", status="500").inc()

            # Audit: pipeline error
            try:
                await audit.write(
                    trace_id=trace_id,
                    actor="orchestrator",
                    actor_type="SERVICE",
                    action="pipeline.error",
                    severity="ERROR",
                    resource_type="Conversation",
                    resource_id=conversation_id,
                    payload={
                        "error": str(exc)[:500],
                        "session_id": session_id,
                        "duration_ms": elapsed_ms,
                    },
                )
            except Exception:
                pass

            raise

    # ------------------------------------------------------------------
    # Step 0: LOAD TEAM HIERARCHY
    # ------------------------------------------------------------------

    async def _load_team_hierarchy(
        self,
        team_id: str,
        conversation_id: str,
        trace_id: str,
    ) -> str:
        """Fetch team from agent-mgmt, load hierarchy into Neo4j, return team context string."""
        try:
            team_data = await self._cb_agent_mgmt.call(
                self._agent_mgmt.get_team,
                team_id=team_id,
                trace_id=trace_id,
            )
            await self._neo4j.load_team_for_conversation(
                team_data=team_data,
                conversation_id=conversation_id,
                trace_id=trace_id,
            )
            logger.info(
                "Team hierarchy loaded for conversation",
                layer="service",
                team_id=team_id,
                conversation_id=conversation_id,
                trace_id=trace_id,
            )

            # Build team context string for system prompts
            team_name = team_data.get("name", "Unknown Team")
            agents_list = team_data.get("agents", [])
            context_parts = [f"== YOUR TEAM: {team_name} =="]
            context_parts.append(f"Team ID: {team_id}")
            context_parts.append(f"Total agents: {len(agents_list)}")
            context_parts.append("")

            # Build a structured TeamContext alongside the prompt text so
            # the pattern dispatcher can filter agents by tool type
            # without re-fetching from agent-mgmt.
            tc_agents: List[Dict[str, Any]] = []

            for agent in agents_list:
                a_name = agent.get("agent_name", agent.get("name", "?"))
                a_role = agent.get("role", "specialist")
                a_model = agent.get("foundation_model", "?")
                context_parts.append(f"Agent: {a_name} (role: {a_role}, model: {a_model})")

                # Fetch this agent's tools
                a_id = agent.get("agent_id", "")
                a_tools: List[Dict[str, Any]] = []
                try:
                    tools = await self._agent_mgmt.get_agent_tools(agent_id=a_id, trace_id=trace_id)
                    if tools:
                        a_tools = list(tools)
                        tool_names = [t.get("tool_name", t.get("name", "?")) for t in tools]
                        tool_types = [t.get("tool_type", "?") for t in tools]
                        for tn, tt in zip(tool_names, tool_types):
                            context_parts.append(f"  - Tool: {tn} ({tt})")
                    else:
                        context_parts.append("  - No tools assigned")
                except Exception:
                    context_parts.append("  - Tools: unavailable")
                context_parts.append("")

                tc_agents.append({
                    "agent_id": a_id,
                    "agent_name": a_name,
                    "role": a_role,
                    "foundation_model": a_model,
                    "tools": a_tools,
                })

            text = "\n".join(context_parts)
            self._last_team_context = TeamContext(
                team_id=team_id,
                name=team_name,
                agents=tc_agents,
                text=text,
            )
            return text

        except CircuitBreakerOpenError:
            logger.warning(
                "Agent-mgmt CB open; skipping team hierarchy load",
                layer="service",
                team_id=team_id,
                trace_id=trace_id,
            )
            return ""
        except Exception as exc:
            logger.warning(
                "Team hierarchy load failed (non-fatal, using existing Neo4j data)",
                layer="service",
                team_id=team_id,
                error=str(exc),
                trace_id=trace_id,
            )
            return ""

    async def _run_pattern_dispatch(
        self,
        graph_id: str,
        message: str,
        team_id: str,
        conversation_id: str,
        session_id: str,
        trace_id: str,
        prior_turns: List[Dict[str, Any]],
    ) -> None:
        """Run the dispatcher and stamp the decision trace.

        Phase 4: ``_pattern_routing_enabled`` controls whether downstream
        gates consult ``self._last_pattern_winner`` instead of
        re-deriving from translator output. Either way the trace is
        always recorded for the UI.

        Failures are non-fatal: a broken dispatcher must not break the
        pipeline. ``_last_pattern_winner`` stays None, the legacy gates
        still see the cached translator output via the Neo4j read
        path, and execution proceeds.
        """
        shadow = not self._pattern_routing_enabled
        try:
            ctx = DispatchContext(
                question=message or "",
                team_id=team_id or "",
                conversation_id=conversation_id or "",
                trace_id=trace_id or "",
                session_id=session_id or "",
                graph_id=graph_id or "",
                prior_turns=list(prior_turns or []),
                translator=dict(self._last_translation or {}),
                team=self._last_team_context,
            )
            winner, match, trace = await self._pattern_dispatcher.dispatch(
                ctx, shadow=shadow,
            )

            if winner is not None and match is not None:
                self._last_pattern_winner = winner.name
                self._last_pattern_payload = dict(match.payload or {})
            else:
                self._last_pattern_winner = None
                self._last_pattern_payload = {}

            # Stamp on TaskGraph for the UI. JSON-serialise the trace
            # body once; Neo4j stores it as a string property.
            try:
                payload = json.dumps(trace.to_dict())
            except Exception:
                payload = "{}"
            try:
                await self._neo4j.run_query(
                    """
                    MATCH (g:TaskGraph {graph_id: $graph_id})
                    SET g.pattern_decision_trace = $trace_json,
                        g.pattern_winner         = $winner,
                        g.pattern_shadow         = $shadow,
                        g.updated_at             = datetime()
                    """,
                    {
                        "graph_id": graph_id,
                        "trace_json": payload,
                        "winner": trace.winner or "",
                        "shadow": shadow,
                    },
                    trace_id=trace_id,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to stamp pattern decision trace",
                    layer="service",
                    graph_id=graph_id,
                    error=str(exc),
                    trace_id=trace_id,
                )
        except Exception as exc:
            logger.warning(
                "Pattern dispatch failed — non-fatal, falling back to legacy gates",
                layer="service",
                graph_id=graph_id,
                error=str(exc),
                trace_id=trace_id,
            )
            self._last_pattern_winner = None
            self._last_pattern_payload = {}

    async def _build_schema_meta_subtasks(
        self,
        team_id: str,
        question: str,
        column: str,
        trace_id: str,
        kind: str = "schema_meta",
        sample_n: int = 5,
    ) -> List[Tuple[str, str, str]]:
        """Build one broadcast subtask per team agent that has a
        DATABASE or GRAPH tool.

        ``kind`` controls the SQL/Cypher plan baked into each subtask:
          * ``schema_meta``  — list tables / nodes that have the column.
          * ``column_value`` — list tables, then SELECT a sample of N
            values from each. ``sample_n`` defaults to 5; pass a
            different value when the user asks for a different count.
          * ``entity_count`` — count rows per loan-shaped table /
            label-shaped node so step-8 python_reduce can total them
            without double-counting parent + subtype rows. The
            ``column`` arg is the entity token in this mode (e.g.
            ``"loans"``), not a real column name.

        Returns a list of ``(subtask_description, agent_id, agent_name)``.
        Empty list when no agent on the team has a DB/Graph tool — caller
        falls back to bare LLM decomposition.

        Each agent reports only on ITS OWN datasources; step-8 aggregation
        merges the per-agent answers into the final response.
        """
        if not team_id:
            return []
        try:
            team_data = await self._cb_agent_mgmt.call(
                self._agent_mgmt.get_team,
                team_id=team_id,
                trace_id=trace_id,
            )
        except Exception as exc:
            logger.warning(
                "Could not fetch team for broadcast subtasks",
                layer="service",
                team_id=team_id,
                kind=kind,
                error=str(exc),
                trace_id=trace_id,
            )
            return []

        agents_list = team_data.get("agents", []) or []
        out: List[Tuple[str, str, str]] = []

        # Tag the hint into the description so the agent knows exactly
        # what to look for. The ``column`` argument is reused for the
        # entity-count case as the entity token (e.g. "loans"); the
        # phrasing differs.
        if kind == "entity_count":
            ent = (column or "").strip()
            if ent:
                col_phrase = (
                    f"the business entity '{ent}' "
                    f"(table names containing the token, or Neo4j labels "
                    f"matching, count as candidates)"
                )
            else:
                col_phrase = (
                    f"the entity the user asks to count in this question: "
                    f"\"{question}\""
                )
        elif column:
            col_phrase = (
                f"a column named '{column}' (case-insensitive; treat "
                f"'%{column}%' partial matches as additional candidates)"
            )
        else:
            col_phrase = (
                f"the column the user asks about in this question: "
                f"\"{question}\""
            )

        col_l = (column or "").lower()

        for agent in agents_list:
            a_name = (
                agent.get("agent_name")
                or agent.get("name")
                or "?"
            )
            a_id = str(agent.get("agent_id") or "")
            if not a_id:
                continue
            try:
                tools = await self._agent_mgmt.get_agent_tools(
                    agent_id=a_id, trace_id=trace_id,
                )
            except Exception:
                tools = []
            db_or_graph = [
                t for t in (tools or [])
                if str(t.get("tool_type") or "").upper() in ("DATABASE", "GRAPH")
            ]
            if not db_or_graph:
                continue

            # Compact tool inventory the agent can paste back into its
            # prompt without re-deriving from team_context.
            tool_lines = []
            for t in db_or_graph:
                tn = t.get("tool_name") or t.get("name") or "?"
                tt = str(t.get("tool_type") or "?").upper()
                ep = t.get("tool_endpoint") or t.get("endpoint") or ""
                tool_lines.append(f"  - {tn} ({tt}) {ep}".rstrip())
            tools_block = "\n".join(tool_lines)

            # SQL plan + return-format vary by kind.
            if kind == "column_value":
                col_eq = repr(col_l) if col_l else "LOWER(<col>)"
                col_like = repr("%" + col_l + "%") if col_l else "LOWER('%<col>%')"
                col_ident = column or "<col>"
                plan = (
                    " 1. For each DATABASE tool, first list its tables with "
                    f"the column via:\n"
                    f"      SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME\n"
                    f"      FROM information_schema.COLUMNS\n"
                    f"      WHERE LOWER(COLUMN_NAME) = {col_eq}\n"
                    f"        OR LOWER(COLUMN_NAME) LIKE {col_like}\n"
                    f"      ORDER BY TABLE_SCHEMA, TABLE_NAME;\n"
                    f" 2. For EACH table returned in step 1, run:\n"
                    f"      SELECT `{col_ident}` FROM `<schema>`.`<table>` "
                    f"WHERE `{col_ident}` IS NOT NULL LIMIT {sample_n};\n"
                    f" 3. For each GRAPH tool (Neo4j), find node labels "
                    f"with the property and sample values:\n"
                    f"      CALL db.schema.nodeTypeProperties() YIELD "
                    f"nodeType, propertyName WHERE toLower(propertyName) "
                    f"CONTAINS toLower($col) RETURN nodeType, propertyName;\n"
                    f"      Then for each label, MATCH (n:<Label>) WHERE "
                    f"n.{col_ident} IS NOT NULL RETURN n.{col_ident} "
                    f"LIMIT {sample_n};\n"
                    f" 4. Run EVERY tool you have — partial coverage is "
                    f"the correct answer for your slice; silence is NOT.\n"
                    f" 5. Return a Markdown table with columns: Tool, "
                    f"Database/Schema, Table/NodeLabel, Sample {col_ident} "
                    f"values (comma-separated, up to {sample_n}). After "
                    f"the table, list any tables that returned zero rows, "
                    f"and any tools that had no matching tables."
                )
            elif kind == "entity_count":
                # Entity-count broadcast — agent returns a JSON array of
                # one row per source. python_reduce dedupes and totals.
                ent = (column or "").lower()
                # Heuristic patterns: tables/labels whose name contains
                # the entity token. If the entity is plural ("loans"),
                # the singular form usually appears in label names
                # (Loan, BridgeLoan); strip a trailing 's' to broaden
                # the match.
                singular = ent[:-1] if (ent.endswith("s") and len(ent) > 3) else ent
                tbl_like = repr("%" + singular + "%") if singular else "LOWER('%<ent>%')"
                lbl_like = singular or "<ent>"
                plan = (
                    f" 1. For each DATABASE tool, find candidate tables:\n"
                    f"      SELECT TABLE_SCHEMA, TABLE_NAME\n"
                    f"      FROM information_schema.TABLES\n"
                    f"      WHERE TABLE_TYPE = 'BASE TABLE'\n"
                    f"        AND LOWER(TABLE_NAME) LIKE {tbl_like}\n"
                    f"      ORDER BY TABLE_SCHEMA, TABLE_NAME;\n"
                    f" 2. For each candidate, run:\n"
                    f"      SELECT COUNT(*) AS n FROM `<schema>`.`<table>`;\n"
                    f"    If a candidate is clearly a child/subtype of another "
                    f"(e.g. `bridgeloans` ⊂ `loans`), record both counts but "
                    f"include `is_subtype_of: '<parent_table>'` on the child row.\n"
                    f" 3. For each GRAPH tool (Neo4j), find candidate labels:\n"
                    f"      CALL db.labels() YIELD label\n"
                    f"      WHERE toLower(label) CONTAINS toLower('{lbl_like}')\n"
                    f"      RETURN label;\n"
                    f" 4. For each label, run:\n"
                    f"      MATCH (n:`<label>`) RETURN count(n) AS n;\n"
                    f"    Multi-label nodes (e.g. `:BridgeLoan:Loan`) make "
                    f"`:BridgeLoan` a subtype of `:Loan` — set `is_subtype_of` "
                    f"on the child row.\n"
                    f" 5. Run EVERY tool you have. If a tool returns zero "
                    f"candidates, include a single row with count=0.\n"
                    f" 6. Return a JSON array (NOT prose). Each element:\n"
                    f"      {{\n"
                    f"        \"tool\": \"<tool_name>\",\n"
                    f"        \"source\": \"<schema.table or label>\",\n"
                    f"        \"type\": \"table\" | \"label\",\n"
                    f"        \"label_or_table\": \"<name>\",\n"
                    f"        \"count\": <int>,\n"
                    f"        \"is_subtype_of\": \"<parent>\"   // OPTIONAL\n"
                    f"      }}\n"
                    f"    Return ONLY the JSON array — no surrounding prose. "
                    f"Step-8 python_reduce will compute the headline total "
                    f"and the breakdown table."
                )
            else:  # schema_meta (default)
                col_eq = repr(col_l) if col_l else "LOWER(<col>)"
                col_like = repr("%" + col_l + "%") if col_l else "LOWER('%<col>%')"
                plan = (
                    " 1. For each DATABASE tool, run an information_schema "
                    f"query like:\n"
                    f"      SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME\n"
                    f"      FROM information_schema.COLUMNS\n"
                    f"      WHERE LOWER(COLUMN_NAME) = {col_eq}\n"
                    f"        OR LOWER(COLUMN_NAME) LIKE {col_like}\n"
                    f"      ORDER BY TABLE_SCHEMA, TABLE_NAME;\n"
                    f" 2. For each GRAPH tool (Neo4j), introspect the schema, e.g.:\n"
                    f"      CALL db.schema.nodeTypeProperties() YIELD "
                    f"nodeType, propertyName WHERE toLower(propertyName) "
                    f"CONTAINS toLower($col) RETURN *;\n"
                    f"      CALL db.schema.relTypeProperties() YIELD "
                    f"relType, propertyName WHERE toLower(propertyName) "
                    f"CONTAINS toLower($col) RETURN *;\n"
                    f" 3. Run every tool you have — silence is NOT an answer. "
                    f"If a tool returns zero rows, report that explicitly.\n"
                    f" 4. Return a Markdown table with columns: Tool, "
                    f"Database/Schema, Table/NodeLabel, Column/Property. "
                    f"Below it, give a one-line count: \"<N> matches across "
                    f"<K> tools\". If no matches, say so plainly."
                )

            desc = (
                f"You are {a_name}. Answer this catalog question for "
                f"YOUR datasources only — do NOT delegate to other agents.\n\n"
                f"User question: {question}\n\n"
                f"Looking for: {col_phrase}\n\n"
                f"Tools you must use:\n{tools_block}\n\n"
                f"Plan:\n{plan}"
            )
            out.append((desc, a_id, a_name))

        logger.info(
            "Broadcast plan built",
            layer="service",
            team_id=team_id,
            kind=kind,
            agent_count=len(out),
            sample_n=sample_n if kind == "column_value" else None,
            trace_id=trace_id,
        )
        return out

    async def _assign_agents_to_subtasks(
        self,
        graph_id: str,
        subtask_descriptions: List[str],
        team_agents: List[Agent],
        trace_id: str,
    ) -> Dict[str, Agent]:
        """Use LLM to decide which agent handles which subtask.

        Returns a mapping of subtask description -> assigned Agent.
        The orchestrator agent (if any) does NOT get subtasks; it only decomposes.
        """
        # Separate orchestrator from specialists
        orchestrator = None
        specialists: List[Agent] = []
        for a in team_agents:
            if a.raw.get("role") == "orchestrator":
                orchestrator = a
            else:
                specialists.append(a)

        if not specialists:
            # If no specialists, all agents are available for tasks
            specialists = team_agents

        if len(specialists) == 1:
            # Only one specialist; assign all tasks to it
            return {desc: specialists[0] for desc in subtask_descriptions}

        # Build agent descriptions for LLM assignment
        agent_summaries = []
        for idx, a in enumerate(specialists):
            agent_summaries.append(
                f"Agent {idx}: id={a.agent_id}, name={a.name}, "
                f"accuracy={a.accuracy_rate}, success_rate={a.success_rate}, "
                f"model={a.foundation_model}"
            )

        assignment_prompt = (
            "You are a task assignment engine. "
            "Given the following agents and sub-tasks, assign each sub-task to the best agent. "
            "Return ONLY a JSON array of integers, where each integer is the agent index (0-based) "
            "for the corresponding sub-task. The array length must match the number of sub-tasks.\n\n"
            f"Agents:\n" + "\n".join(agent_summaries) + "\n\n"
            f"Sub-tasks:\n" + "\n".join(f"{i}: {d}" for i, d in enumerate(subtask_descriptions)) + "\n\n"
            "Assignment (JSON array of agent indices):"
        )

        try:
            raw = await self._llm.complete(
                messages=[{"role": "user", "content": assignment_prompt}],
                trace_id=trace_id,
            )
            parsed = json.loads(raw)
            if isinstance(parsed, list) and len(parsed) == len(subtask_descriptions):
                assignments = {}
                for i, desc in enumerate(subtask_descriptions):
                    agent_idx = int(parsed[i]) if isinstance(parsed[i], (int, float)) else 0
                    agent_idx = max(0, min(agent_idx, len(specialists) - 1))
                    assignments[desc] = specialists[agent_idx]
                logger.info(
                    "Subtask agent assignment complete",
                    layer="service",
                    graph_id=graph_id,
                    assignments={d: a.agent_id for d, a in assignments.items()},
                    trace_id=trace_id,
                )
                return assignments
        except Exception as exc:
            logger.warning(
                "LLM agent assignment failed; using round-robin",
                layer="service",
                error=str(exc),
                trace_id=trace_id,
            )

        # Fallback: round-robin assignment
        assignments = {}
        for i, desc in enumerate(subtask_descriptions):
            assignments[desc] = specialists[i % len(specialists)]
        return assignments

    # ------------------------------------------------------------------
    # F7: Multi-turn dialog — prior_turns lookup
    # ------------------------------------------------------------------

    async def _fetch_prior_turns_from_messages(
        self,
        conversation_id: str,
        trace_id: str,
        max_messages: int = 6,
    ) -> List[Dict[str, Any]]:
        """Build the translator prior_turns list from MySQL message history.

        Walks the most recent ``max_messages`` messages of ``conversation_id``
        and stitches together alternating user → translator clarification
        round-trips. Only assistant messages with
        ``metadata.clarification = True`` are surfaced as translator turns.
        Soft-fails to ``[]`` so the single-turn path is never broken.
        """
        if not conversation_id:
            return []
        try:
            conn = mysql.connector.connect(
                host=settings.mysql_host,
                port=settings.mysql_port,
                user=settings.mysql_user,
                password=settings.mysql_password,
                database=settings.mysql_db,
                connection_timeout=3,
            )
        except Exception as exc:
            logger.warning(
                "prior_turns_lookup_db_connect_failed",
                layer="service",
                conversation_id=conversation_id,
                trace_id=trace_id,
                error=str(exc),
            )
            return []

        rows: List[Tuple[Any, ...]] = []
        try:
            cur = conn.cursor()
            try:
                cur.execute(
                    "SELECT role, content, metadata, created_at "
                    "FROM messages WHERE conversation_id = %s "
                    "ORDER BY created_at DESC LIMIT %s",
                    (conversation_id, int(max_messages)),
                )
                rows = list(cur.fetchall() or [])
            finally:
                cur.close()
        except Exception as exc:
            logger.warning(
                "prior_turns_lookup_query_failed",
                layer="service",
                conversation_id=conversation_id,
                trace_id=trace_id,
                error=str(exc),
            )
            return []
        finally:
            try:
                conn.close()
            except Exception:
                pass

        # Reverse to chronological order (oldest first).
        rows.reverse()

        prior_turns: List[Dict[str, Any]] = []
        for role, content, metadata_raw, _created_at in rows:
            role_str = str(role or "").strip().lower()
            content_str = str(content or "").strip()
            if not content_str:
                continue
            if role_str == "user":
                prior_turns.append({"role": "user", "content": content_str})
                continue
            if role_str == "assistant":
                # Only include assistant messages that were clarifications
                # — anything else is a final answer and shouldn't go back
                # into the translator's dialog history.
                meta_obj: Dict[str, Any] = {}
                try:
                    if isinstance(metadata_raw, str) and metadata_raw:
                        meta_obj = json.loads(metadata_raw)
                    elif isinstance(metadata_raw, (bytes, bytearray)):
                        meta_obj = json.loads(metadata_raw.decode("utf-8"))
                    elif isinstance(metadata_raw, dict):
                        meta_obj = metadata_raw
                except Exception:
                    meta_obj = {}
                if not bool(meta_obj.get("clarification")):
                    continue
                clar_q = (
                    str(meta_obj.get("clarification_question") or "").strip()
                    or content_str
                )
                prior_turns.append({"role": "translator", "content": clar_q})

        # Drop trailing user turn if it equals the current incoming message —
        # the executor passes the user's NEW message separately, so it
        # shouldn't appear in prior_turns. Safe heuristic: don't include the
        # MOST RECENT user message at all.
        while prior_turns and prior_turns[-1].get("role") == "user":
            prior_turns.pop()

        # Cap at the last 1-2 round-trips (4 entries) — orchestrator-level
        # safeguard before the translator's own MAX_PRIOR_TURNS_IN_PROMPT cap.
        if len(prior_turns) > 4:
            prior_turns = prior_turns[-4:]

        if prior_turns:
            logger.info(
                "Loaded prior_turns for translator",
                layer="service",
                conversation_id=conversation_id,
                trace_id=trace_id,
                n_prior_turns=len(prior_turns),
            )
        return prior_turns

    # ------------------------------------------------------------------
    # Step 1: REQUEST INTAKE
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Ext2 — Deterministic Report execution
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Pending-report-confirm state — read/write conversations.metadata.
    # Used by the confirm-band Report match flow: turn N stamps the
    # candidate report on the conversation; turn N+1 reads it and acts on
    # the user's reply (yes / data / refinement).
    # ------------------------------------------------------------------

    _CONFIRM_YES_TOKENS = {
        "yes", "y", "yeah", "yep", "yup", "sure", "ok", "okay",
        "use it", "use the report", "show it", "show the report", "run it",
        "go ahead", "do it", "please", "fire it",
    }
    _CONFIRM_NO_TOKENS = {
        "no", "n", "nope", "nah", "skip", "data", "just data",
        "look up the data", "look up data", "different", "agent",
        "go to data", "use data", "do not", "dont", "don't",
    }

    @staticmethod
    def _classify_confirm_reply(message: str) -> str:
        """Returns 'yes', 'no', or 'other'."""
        m = (message or "").strip().lower().strip(".!?")
        if not m:
            return "other"
        if m in PipelineService._CONFIRM_YES_TOKENS:
            return "yes"
        if m in PipelineService._CONFIRM_NO_TOKENS:
            return "no"
        # Short multi-word fuzzy match.
        if any(t in m for t in ("yes,", "yes ", "use the rep", "fire the rep")):
            return "yes"
        if any(t in m for t in ("no,", "no ", "skip ", "look up the data", "use data instead")):
            return "no"
        return "other"

    def _get_pending_report_confirm(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """Read pending_report_confirm from conversations.metadata (MySQL)."""
        if not conversation_id:
            return None
        try:
            import mysql.connector
            conn = mysql.connector.connect(
                host=settings.mysql_host, port=settings.mysql_port,
                user=settings.mysql_user, password=settings.mysql_password,
                database=settings.mysql_db,
            )
            try:
                cur = conn.cursor(dictionary=True)
                cur.execute(
                    "SELECT metadata FROM conversations WHERE conversation_id=%s",
                    (conversation_id,),
                )
                row = cur.fetchone()
            finally:
                conn.close()
            if not row or not row.get("metadata"):
                return None
            md_raw = row["metadata"]
            md = json.loads(md_raw) if isinstance(md_raw, (str, bytes)) else md_raw
            if not isinstance(md, dict):
                return None
            return md.get("pending_report_confirm") or None
        except Exception as exc:
            logger.warning(
                "Failed to read pending_report_confirm",
                layer="service", conversation_id=conversation_id, error=str(exc),
            )
            return None

    def _set_pending_report_confirm(
        self,
        conversation_id: str,
        report_id: str,
        report_name: str,
        score: float,
        original_question: str,
    ) -> None:
        self._merge_conversation_metadata(
            conversation_id,
            {
                "pending_report_confirm": {
                    "report_id": report_id,
                    "report_name": report_name,
                    "score": float(score),
                    "original_question": original_question,
                    "asked_at": datetime.utcnow().isoformat() + "Z",
                }
            },
        )

    def _clear_pending_report_confirm(self, conversation_id: str) -> None:
        self._merge_conversation_metadata(
            conversation_id, {"pending_report_confirm": None}
        )

    def _merge_conversation_metadata(self, conversation_id: str, patch: Dict[str, Any]) -> None:
        """Merge a JSON patch into conversations.metadata. Setting a key to
        None removes it. Best-effort — failures are logged, never raised."""
        if not conversation_id:
            return
        try:
            import mysql.connector
            conn = mysql.connector.connect(
                host=settings.mysql_host, port=settings.mysql_port,
                user=settings.mysql_user, password=settings.mysql_password,
                database=settings.mysql_db,
            )
            try:
                cur = conn.cursor(dictionary=True)
                cur.execute(
                    "SELECT metadata FROM conversations WHERE conversation_id=%s",
                    (conversation_id,),
                )
                row = cur.fetchone()
                md = {}
                if row and row.get("metadata"):
                    raw = row["metadata"]
                    try:
                        md = json.loads(raw) if isinstance(raw, (str, bytes)) else (raw or {})
                    except Exception:
                        md = {}
                if not isinstance(md, dict):
                    md = {}
                for k, v in patch.items():
                    if v is None:
                        md.pop(k, None)
                    else:
                        md[k] = v
                cur.execute(
                    "UPDATE conversations SET metadata=%s WHERE conversation_id=%s",
                    (json.dumps(md), conversation_id),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            logger.warning(
                "Failed to merge conversation metadata",
                layer="service", conversation_id=conversation_id, error=str(exc),
            )

    async def _execute_matched_report(
        self,
        report: Dict[str, Any],
        trace_id: str,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """Run a Report's SQL command(s) directly against the bound DataSource.

        The translator already located the Report and stamped the binding
        target onto each dataset (``source_uri`` like
        ``mysql://host:port/database``). We parse that, run the command via
        ``mysql.connector``, format the result rows as a markdown table, AND
        build a Visualization spec per dataset so the chat UI can render
        bar/line/pie charts alongside the table.

        Returns ``(markdown_response, visualizations)`` where visualizations
        is a list of dicts matching ``shared.visualization.Visualization``.

        Failure modes are non-fatal — we render an explanation in the chat
        response so the user understands what went wrong without the
        pipeline crashing.
        """
        from urllib.parse import urlparse
        # Prefer the shared module (kept in sync via the translator image's
        # build context); fall back to the orchestrator-local copy when the
        # shared package isn't importable in this image.
        try:
            from shared.visualization import make_visualization  # type: ignore
        except Exception:
            try:
                from app.utils.visualization import make_visualization  # type: ignore
            except Exception:
                make_visualization = None  # type: ignore[assignment]

        visualizations: List[Dict[str, Any]] = []
        datasets = report.get("datasets") or []
        if not datasets:
            return (
                f"## {report.get('name')}\n\nThis report has no datasets registered.",
                visualizations,
            )

        sections: List[str] = [
            f"## {report.get('name')}",
            f"_System: {report.get('system')} · Owner: {report.get('owner_team')}_",
            "",
            f"{report.get('description') or ''}",
            "",
        ]

        for ds in datasets:
            command = ds.get("command")
            command_type = (ds.get("command_type") or "SQL").upper()
            source_uri = ds.get("source_uri") or ""
            ds_name = ds.get("name") or ds.get("dataset_id") or "(unnamed)"

            sections.append(f"### Dataset: `{ds_name}`")
            sections.append(f"```{command_type.lower()}\n{command}\n```")

            if not command:
                sections.append("_(no command stored)_\n")
                continue
            if command_type != "SQL":
                sections.append(
                    f"_(skipping execution: {command_type} is not yet supported)_\n"
                )
                continue
            if not source_uri.startswith("mysql://"):
                sections.append(
                    f"_(skipping execution: source `{source_uri}` is not MySQL)_\n"
                )
                continue

            # Parse mysql://host:port/database
            try:
                u = urlparse(source_uri)
                host = u.hostname or "localhost"
                port = u.port or 3306
                database = (u.path or "").lstrip("/") or None
            except Exception as exc:
                sections.append(f"_(could not parse source_uri: {exc})_\n")
                continue

            # The crawled DataSource doesn't carry credentials — fall back
            # to the orchestrator's own MySQL credentials. In production this
            # would resolve to a per-source secret in a vault.
            try:
                import mysql.connector  # local import; we already use it elsewhere
                conn = mysql.connector.connect(
                    host=host, port=port, database=database,
                    user=settings.mysql_user, password=settings.mysql_password,
                    connection_timeout=10,
                )
                cur = conn.cursor(dictionary=True)
                cur.execute(command)
                rows = cur.fetchmany(50)
                col_names = [c[0] for c in (cur.description or [])]
                cur.close()
                conn.close()
            except Exception as exc:
                logger.warning(
                    "Report execution failed",
                    layer="service",
                    trace_id=trace_id,
                    report_id=report.get("report_id"),
                    error=str(exc),
                )
                sections.append(f"_(execution failed: {str(exc)[:300]})_\n")
                continue

            if not rows:
                sections.append("_(no rows returned)_\n")
                continue

            # Render top 50 rows as a markdown table
            sections.append(f"_Returned {len(rows)} row{'s' if len(rows) != 1 else ''}:_\n")
            sections.append("| " + " | ".join(col_names) + " |")
            sections.append("|" + "|".join("---" for _ in col_names) + "|")
            for r in rows:
                vals = []
                for c in col_names:
                    v = r.get(c)
                    if v is None:
                        vals.append("—")
                    else:
                        vals.append(str(v).replace("|", "\\|")[:80])
                sections.append("| " + " | ".join(vals) + " |")
            sections.append("")

            # Build a chart spec for the chat UI to render alongside the
            # markdown table. The heuristic picks bar/line/pie/area/table
            # from the data shape; the user can flip via the toggle.
            if make_visualization is not None:
                try:
                    viz = make_visualization(
                        rows=rows,
                        col_names=col_names,
                        title=f"{report.get('name')} — {ds_name}",
                        description=ds.get("name"),
                    )
                    visualizations.append(viz)
                except Exception as exc:
                    logger.warning(
                        "make_visualization failed (non-fatal)",
                        layer="service",
                        trace_id=trace_id,
                        error=str(exc),
                    )

        return "\n".join(sections), visualizations

    async def _step1_intake(
        self,
        session_id: str,
        conversation_id: str,
        message: str,
        team_id: str,
        trace_id: str,
    ) -> Tuple[str, Dict[str, Any]]:
        """Create session, create graph, pull relevant SOPs."""
        graph_id = await self._graph_mgr.create_graph(
            session_id=session_id,
            user_request=message,
            trace_id=trace_id,
            conversation_id=conversation_id,
            team_id=team_id,
        )

        # Publish telemetry
        await self._redis.publish_telemetry(
            {
                "event_type": "session_started",
                "session_id": session_id,
                "graph_id": graph_id,
                "team_id": team_id,
            },
            trace_id=trace_id,
        )

        # SOP lookup (best-effort; doesn't block pipeline)
        sop_context: Dict[str, Any] = {}
        try:
            sops = await self._neo4j.run_query(
                "MATCH (s:SOP) RETURN s LIMIT 5",
                trace_id=trace_id,
            )
            sop_context = {"sops": sops}
        except Exception as exc:
            logger.warning(
                "SOP lookup failed (non-fatal)",
                layer="service",
                error=str(exc),
                trace_id=trace_id,
            )

        return graph_id, sop_context

    # ------------------------------------------------------------------
    # Step 2: GRAPH CONSTRUCTION
    # ------------------------------------------------------------------

    async def _step2_graph_construction(
        self,
        graph_id: str,
        message: str,
        team_id: str,
        sop_context: Dict[str, Any],
        trace_id: str,
        team_context: str = "",
        conversation_id: str = "",
    ) -> Tuple[str, List[str]]:
        """Decompose intent into sub-tasks via Translator (ontology-aware) and
        create TaskNodes. Falls back to the bare LLM decomposition when the
        Translator returns no ontology matches."""

        # 1. Ask the Translator service first. The adapter never raises — on
        #    failure it returns an empty result with fallback_used=True.
        # F7 — feed prior dialog turns from this conversation so multi-turn
        # clarifications can narrow the translation. The helper soft-fails to
        # an empty list so the single-turn path stays untouched.
        prior_turns = await self._fetch_prior_turns_from_messages(
            conversation_id=conversation_id, trace_id=trace_id,
        )
        translation = await self._translator.translate(
            question=message,
            team_id=team_id,
            conversation_id=conversation_id,
            trace_id=trace_id,
            prior_turns=prior_turns,
        )
        # Stash for the pattern dispatcher (shadow mode in Phase 1).
        self._last_translation = dict(translation or {})

        # F4 — capture clarification & auditor-issue signals on the
        # TaskGraph so the chat response layer can short-circuit and surface
        # the clarification question / issue id to the user without running
        # the full execution pipeline. Ext2 — also stamp matched_reports as
        # a JSON blob so the deterministic short-circuit can read it back.
        matched_reports_raw = translation.get("matched_reports") or []
        try:
            mr_json = json.dumps(matched_reports_raw)
        except Exception:
            mr_json = "[]"
        try:
            await self._neo4j.run_query(
                """
                MATCH (g:TaskGraph {graph_id: $graph_id})
                SET g.translator_intent              = $intent,
                    g.translator_domain              = $domain,
                    g.translator_clarification_need  = $clar_needed,
                    g.translator_clarification       = $clar_question,
                    g.translator_auditor_issue_id    = $issue_id,
                    g.translator_auditor_issue_kind  = $issue_kind,
                    g.translator_canonical_count     = $cn_count,
                    g.translator_binding_count       = $bn_count,
                    g.translator_matched_reports     = $matched_reports,
                    g.updated_at = datetime()
                """,
                {
                    "graph_id": graph_id,
                    "intent": translation.get("intent"),
                    "domain": translation.get("domain"),
                    "clar_needed": bool(translation.get("clarification_needed")),
                    "clar_question": translation.get("clarification_question"),
                    "issue_id": translation.get("auditor_issue_id"),
                    "issue_kind": translation.get("auditor_issue_kind"),
                    "cn_count": len(translation.get("canonical_entities") or []),
                    "bn_count": len(translation.get("dataset_bindings") or []),
                    "matched_reports": mr_json,
                },
                trace_id=trace_id,
            )
        except Exception as exc:
            logger.warning(
                "Failed to stamp translation metadata on TaskGraph",
                layer="service", trace_id=trace_id, error=str(exc),
            )

        canonical_entities = translation.get("canonical_entities") or []
        dataset_bindings_objs = translation.get("dataset_bindings") or []
        domain_subtasks = [str(s) for s in (translation.get("domain_subtasks") or []) if s]
        intent = translation.get("intent")
        domain = translation.get("domain")
        ontology_versions = [str(v) for v in (translation.get("ontology_versions") or [])]

        # Flatten typed objects to plain string lists for storage on TaskNode.
        canonical_entity_names: List[str] = []
        for c in canonical_entities:
            if isinstance(c, dict):
                name = c.get("fq_name") or c.get("name")
                if name:
                    canonical_entity_names.append(str(name))
            elif c:
                canonical_entity_names.append(str(c))

        dataset_binding_strings: List[str] = []
        for b in dataset_bindings_objs:
            if isinstance(b, dict):
                fq = b.get("asset_fq_name")
                if fq:
                    dataset_binding_strings.append(str(fq))
            elif b:
                dataset_binding_strings.append(str(b))

        used_ontology = bool(canonical_entity_names) and bool(domain_subtasks)

        # Catalog/column broadcast — translator detected one of:
        #   schema_meta_question   — "how many tables have X column"
        #   column_value_question  — "value of X across these tables"
        # Build one subtask per team agent that has a DATABASE or GRAPH
        # tool, telling each to introspect / sample ITS OWN catalog and
        # report back. Pre-assign each subtask to the named agent so the
        # bidder can't misroute. Step 8 aggregation combines the per-
        # agent answers into the user-visible response.
        schema_meta_assignments: Dict[str, str] = {}
        if intent in ("schema_meta_question", "column_value_question",
                       "entity_count_question"):
            sm_column = str(translation.get("schema_meta_column") or "").strip()
            sm_kind = (
                "column_value"
                if intent == "column_value_question"
                else "entity_count"
                if intent == "entity_count_question"
                else "schema_meta"
            )
            # Parse "<N> samples" / "sample of <N>" / "<N> rows" from
            # the question so the agent samples the count the user asked
            # for. Falls back to 5 when no number was given.
            sample_n = 5
            if sm_kind == "column_value":
                m = re.search(
                    r"\b(?:sample(?:\s+of)?|of|first|top|limit)\s*"
                    r"(\d{1,4})\b",
                    message or "",
                    re.IGNORECASE,
                )
                if not m:
                    m = re.search(
                        r"\b(\d{1,4})\s*(?:samples?|rows?|values?|records?)\b",
                        message or "",
                        re.IGNORECASE,
                    )
                if m:
                    try:
                        n = int(m.group(1))
                        if 1 <= n <= 1000:
                            sample_n = n
                    except (TypeError, ValueError):
                        pass
            sm_subtasks = await self._build_schema_meta_subtasks(
                team_id=team_id,
                question=message,
                column=sm_column,
                trace_id=trace_id,
                kind=sm_kind,
                sample_n=sample_n,
            )
            if sm_subtasks:
                # Pre-assign: subtask description -> agent_id. Read by the
                # main pipeline AFTER negotiation runs so we can override
                # any mis-routing.
                schema_meta_assignments = {
                    desc: aid for desc, aid, _ in sm_subtasks
                }
                self._current_schema_meta_assignments = dict(schema_meta_assignments)
                # Tag these descriptions so the executor force-accepts
                # the answer (each agent only covers ITS own datasources;
                # the score band would otherwise call partial coverage a
                # failure and bounce to a useless fallback agent).
                self._current_schema_meta_descriptions = set(schema_meta_assignments.keys())
                # The decomposition we send into the graph is just the
                # description list — assignments are picked up post-hoc.
                domain_subtasks = [desc for desc, _, _ in sm_subtasks]
                used_ontology = True  # we have explicit subtasks; skip LLM decomp

                # entity_count delegates aggregation to the team's
                # PythonAnalyst — LLMs are unreliable at exact arithmetic
                # and the no-double-count rule for parent/subtype rows
                # is far easier to express in code than in prompt.
                if sm_kind == "entity_count":
                    self._current_aggregation_strategy = "python_reduce"
                    self._current_aggregation_instructions = (
                        "Each per-source row is a JSON describing a count "
                        "from one tool/source. Each row has fields like:\n"
                        "  tool, source, type ('table'|'label'), label_or_table, "
                        "count, and optionally is_subtype_of.\n\n"
                        "Aggregation rules:\n"
                        " 1. Group by canonical (parent) entity. A row is a "
                        "subtype when 'is_subtype_of' is set OR when its "
                        "label_or_table is plausibly a subtype of another "
                        "row's label_or_table (e.g. BridgeLoan ⊂ Loan in the "
                        "same tool).\n"
                        " 2. Do NOT add subtype counts to the parent's total — "
                        "the parent count already includes them. Surface the "
                        "subtype breakdown separately.\n"
                        " 3. Sum the canonical (non-subtype) counts across "
                        "tools to get the headline total.\n"
                        " 4. Return: a Markdown table with one row per tool/"
                        "source showing source, type, count; then a "
                        "'### Subtype breakdown' section if any; then a single "
                        "bold line: '**Total: <N> <entity>**'."
                    )
                logger.info(
                    "Broadcast subtasks built",
                    layer="service",
                    graph_id=graph_id,
                    trace_id=trace_id,
                    kind=sm_kind,
                    column=sm_column,
                    subtask_count=len(sm_subtasks),
                    aggregation=self._current_aggregation_strategy,
                )
            else:
                # No agent has a DATABASE/GRAPH tool. Fall back to the
                # bare LLM decomposition path; the original question text
                # will route to whichever agent the LLM picks.
                logger.info(
                    "Schema-meta question detected but no DB/GRAPH agents on team",
                    layer="service",
                    graph_id=graph_id,
                    trace_id=trace_id,
                    column=sm_column,
                )

        # 2. Fallback to bare LLM decomposition when the ontology gave us
        #    nothing usable.
        sub_tasks: List[str] = []
        if used_ontology:
            sub_tasks = domain_subtasks
            logger.info(
                "Translator decomposition used",
                layer="service",
                graph_id=graph_id,
                trace_id=trace_id,
                intent=intent,
                domain=domain,
                canonical_entities=len(canonical_entity_names),
                dataset_bindings=len(dataset_binding_strings),
                subtasks=len(sub_tasks),
            )
        else:
            team_info = ""
            if team_context:
                team_info = (
                    f"\n\nTEAM CONTEXT (use this to understand what your team can do):\n"
                    f"{team_context}\n\n"
                    "IMPORTANT: When the user asks about the team, its agents, or their capabilities, "
                    "you should create a SINGLE sub-task that answers from the team context above. "
                    "Do NOT decompose self-referential team questions into multiple sub-tasks. "
                    "Only use agents and tools that are IN THIS TEAM — never reference agents or tools "
                    "that are not listed above.\n\n"
                )

            decomposition_prompt = (
                "You are a task decomposition engine. "
                "Break the following user request into 1-5 concrete, executable sub-tasks. "
                "Return ONLY a JSON array of strings, each being a sub-task description. "
                "No additional text."
                f"{team_info}"
                f"\nUser request: {message}"
            )

            raw = await self._llm.complete(
                messages=[{"role": "user", "content": decomposition_prompt}],
                trace_id=trace_id,
            )

            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    sub_tasks = [str(t) for t in parsed if t]
            except (json.JSONDecodeError, ValueError):
                sub_tasks = self._graph_mgr._extract_sub_tasks(raw)

            if not sub_tasks:
                sub_tasks = [message]

            logger.info(
                "Translator returned no ontology matches; bare LLM decomposition used",
                layer="service",
                graph_id=graph_id,
                trace_id=trace_id,
                subtasks=len(sub_tasks),
            )

        # 3. Create root node (carries intent/domain even on fallback so the
        #    Live Graph UI can show "decomposed without ontology" markers).
        root_node_id = await self._graph_mgr.add_root_node(
            graph_id=graph_id,
            description=message,
            trace_id=trace_id,
        )

        # 4. Create sub-task nodes — stamp ontology bindings only when the
        #    translator actually found matches; never invent bindings on
        #    fallback paths.
        for task_desc in sub_tasks:
            await self._graph_mgr.add_node(
                graph_id=graph_id,
                parent_id=root_node_id,
                description=task_desc,
                node_type=NodeType.SUBTASK,
                depth=1,
                iteration=0,
                trace_id=trace_id,
                canonical_entities=canonical_entity_names if used_ontology else [],
                dataset_bindings=dataset_binding_strings if used_ontology else [],
                intent=intent if used_ontology else None,
                domain=domain if used_ontology else None,
                ontology_versions=ontology_versions if used_ontology else [],
            )

        await self._neo4j.update_graph_status(
            graph_id, "EXECUTING", iteration=0, trace_id=trace_id
        )

        # 5. Audit (best-effort).
        try:
            await audit.write(
                trace_id=trace_id,
                actor="orchestrator",
                actor_type="SERVICE",
                action="pipeline.decomposed",
                resource_type="TaskGraph",
                resource_id=graph_id,
                payload={
                    "subtask_count": len(sub_tasks),
                    "ontology_used": used_ontology,
                    "intent": intent,
                    "domain": domain,
                    "canonical_entities": canonical_entity_names,
                    "dataset_bindings": dataset_binding_strings,
                    "ontology_versions": ontology_versions,
                },
            )
        except Exception:
            pass

        logger.info(
            "Graph construction complete",
            layer="service",
            graph_id=graph_id,
            sub_tasks=len(sub_tasks),
            ontology_used=used_ontology,
            trace_id=trace_id,
        )
        return root_node_id, sub_tasks

    # ------------------------------------------------------------------
    # Step 3: PRE-EXECUTION VALIDATION
    # ------------------------------------------------------------------

    async def _step3_validation(
        self,
        team_id: str,
        trace_id: str,
    ) -> Tuple[Optional[Agent], List[Agent]]:
        """Verify agent availability. Return primary + fallback chain."""
        primary, fallbacks = await self._agent_sel.select_primary_and_fallbacks(
            team_id=team_id,
            trace_id=trace_id,
        )
        if primary is None:
            logger.warning(
                "No primary agent available; will use default LLM execution",
                layer="service",
                team_id=team_id,
                trace_id=trace_id,
            )
        return primary, fallbacks

    # ------------------------------------------------------------------
    # Step 3b: CAPABILITY NEGOTIATION
    # ------------------------------------------------------------------

    async def _step3_negotiate(
        self,
        graph_id: str,
        node_descriptions: List[str],
        team_agents: List[Agent],
        trace_id: str,
        team_id: str = "",
        session_id: str = "",
        round_n: int = 1,
    ) -> Tuple[Dict[str, NegotiationResult], Dict[str, BanditDecision]]:
        """Run capability negotiation for each subtask description.

        In addition to bidding, this also invokes the contextual bandit in
        SHADOW mode so we can log what the bandit would have picked for each
        decision alongside the bid winner. The bandit does not yet influence
        selection; reward back-fill happens after scoring completes.
        """
        results: Dict[str, NegotiationResult] = {}
        bandit_decisions: Dict[str, BanditDecision] = {}

        # Get graph nodes to map descriptions to node IDs
        graph_nodes = await self._graph_mgr.get_graph_nodes(graph_id, trace_id=trace_id)
        subtask_nodes = [n for n in graph_nodes if n.get("node_type") == "SUBTASK"]

        for i, desc in enumerate(node_descriptions):
            # Find corresponding node_id and pull its ontology bindings so the
            # negotiation can filter agents by physical-asset reachability.
            node_id = ""
            dataset_bindings: List[str] = []
            if i < len(subtask_nodes):
                sn = subtask_nodes[i]
                node_id = sn.get("node_id", "")
                raw_bindings = sn.get("dataset_bindings") or []
                dataset_bindings = [str(b) for b in raw_bindings if b]

            bid_request = BidRequest(
                task_id=node_id,
                task_description=desc,
                task_type="general",
                graph_id=graph_id,
                trace_id=trace_id,
                dataset_bindings=dataset_bindings,
            )

            # Phase A: emit bid.opened so the timeline UI can show the
            # candidate set before the team has responded.
            try:
                from app.utils.events import events as _events
                await _events.publish(
                    conversation_id=getattr(self, "_current_conversation_id", "") or "",
                    kind="bid.opened",
                    trace_id=trace_id,
                    graph_id=graph_id,
                    node_id=node_id,
                    round_n=round_n,
                    payload={
                        "description": desc[:240],
                        "candidates": [a.name for a in team_agents][:30],
                        "n_candidates": len(team_agents),
                        "dataset_bindings": dataset_bindings[:20],
                    },
                )
            except Exception:
                pass

            try:
                neg_result = await self._negotiation.negotiate(
                    bid_request=bid_request,
                    team_agents=team_agents,
                    trace_id=trace_id,
                )
                results[desc] = neg_result

                # Phase A: emit bid.closed with the winner + runner-up snapshot.
                try:
                    from app.utils.events import events as _events
                    bid_payload: Dict[str, Any] = {
                        "description": desc[:240],
                        "winner": None,
                        "runners_up": [],
                    }
                    if neg_result.winner:
                        bid_payload["winner"] = {
                            "agent_id": neg_result.winner.agent_id,
                            "agent_name": neg_result.winner.agent_name,
                            "confidence": neg_result.winner.confidence,
                        }
                    bidders = getattr(neg_result, "bidders", None) or []
                    runners: List[Dict[str, Any]] = []
                    for b in list(bidders)[:5]:
                        try:
                            if neg_result.winner and getattr(b, "agent_id", "") == neg_result.winner.agent_id:
                                continue
                            runners.append({
                                "agent_id": getattr(b, "agent_id", ""),
                                "agent_name": getattr(b, "agent_name", ""),
                                "confidence": getattr(b, "confidence", None),
                            })
                        except Exception:
                            continue
                    bid_payload["runners_up"] = runners
                    await _events.publish(
                        conversation_id=getattr(self, "_current_conversation_id", "") or "",
                        kind="bid.closed",
                        trace_id=trace_id,
                        graph_id=graph_id,
                        node_id=node_id,
                        round_n=round_n,
                        status="SUCCESS" if neg_result.winner else "ERROR",
                        payload=bid_payload,
                    )
                except Exception:
                    pass

                # Phase D.1 — bandit decision (SHADOW or LIVE). When the
                # ``bandit_live_selection`` flag is set, the bandit's pick
                # can override the bid winner. The selector itself
                # downgrades LIVE → FALLBACK when the picked arm has fewer
                # than MIN_PULLS_FOR_LIVE (=20) historical pulls, so a cold
                # start can't accidentally promote a noisy estimate over a
                # confident bid.
                try:
                    bandit_mode = (
                        "LIVE" if getattr(settings, "bandit_live_selection", False)
                        else "SHADOW"
                    )
                    context_bucket = f"team:{team_id or 'default'}|type:{bid_request.task_type}"
                    winner_id = neg_result.winner.agent_id if neg_result.winner else ""
                    winner_name = neg_result.winner.agent_name if neg_result.winner else ""
                    bd = self._bandit.select(
                        candidates=team_agents,
                        context_bucket=context_bucket,
                        actual_winner_id=winner_id,
                        actual_winner_name=winner_name,
                        trace_id=trace_id,
                        session_id=session_id,
                        graph_id=graph_id,
                        node_id=node_id,
                        mode=bandit_mode,
                    )
                    if bd is not None:
                        bandit_decisions[desc] = bd

                        # If bandit ran in LIVE mode (and didn't get
                        # auto-downgraded to FALLBACK), surface the
                        # rationale and rewrite the negotiation winner.
                        if bd.mode == "LIVE" and bd.bandit_pick_agent_id:
                            try:
                                from app.utils.events import events as _events
                                pick_id = bd.bandit_pick_agent_id
                                pick_name = bd.bandit_pick_agent_name
                                overridden = (
                                    neg_result.winner is not None
                                    and neg_result.winner.agent_id != pick_id
                                )
                                await _events.publish(
                                    conversation_id=getattr(self, "_current_conversation_id", "") or "",
                                    kind="ml.rationale",
                                    trace_id=trace_id,
                                    graph_id=graph_id,
                                    node_id=node_id,
                                    round_n=round_n,
                                    status="SUCCESS",
                                    payload={
                                        "source": "bandit",
                                        "mode": "LIVE",
                                        "decision_id": bd.decision_id,
                                        "context_bucket": context_bucket,
                                        "pick_agent_id": pick_id,
                                        "pick_agent_name": pick_name,
                                        "overrode_bid_winner": overridden,
                                        "prior_bid_winner": (
                                            neg_result.winner.agent_name
                                            if neg_result.winner else None
                                        ),
                                        "candidates": [
                                            {
                                                "agent_name": c.get("agent_name"),
                                                "theta": round(c.get("sampled_theta", 0.0), 3),
                                                "pulls": c.get("pulls", 0),
                                            }
                                            for c in (bd.candidates or [])[:6]
                                        ],
                                    },
                                )
                            except Exception:
                                pass

                            # Rewrite the negotiation winner so downstream
                            # agent_assignments + execution use the bandit
                            # pick. We synthesise a minimal winner shape
                            # compatible with the existing access pattern.
                            if (
                                neg_result.winner is None
                                or neg_result.winner.agent_id != bd.bandit_pick_agent_id
                            ):
                                winning_bidder = next(
                                    (
                                        b for b in (neg_result.bidders or [])
                                        if getattr(b, "agent_id", "") == bd.bandit_pick_agent_id
                                    ),
                                    None,
                                )
                                if winning_bidder is not None:
                                    neg_result.winner = winning_bidder
                                    logger.info(
                                        "Bandit LIVE override: bid winner replaced by bandit pick",
                                        layer="service",
                                        decision_id=bd.decision_id,
                                        prior=(
                                            neg_result.winner.agent_name
                                            if neg_result.winner else None
                                        ),
                                        new=bd.bandit_pick_agent_name,
                                        trace_id=trace_id,
                                    )
                except Exception as exc:
                    logger.warning(
                        "Bandit decision failed (non-fatal)",
                        layer="service",
                        description=desc[:80],
                        error=str(exc),
                        trace_id=trace_id,
                    )

                # Log negotiation as an interaction (fire-and-forget)
                if neg_result.winner:
                    await self._interaction_logger.log_interaction(
                        task_id=node_id,
                        graph_id=graph_id,
                        agent_id=neg_result.winner.agent_id,
                        agent_name=neg_result.winner.agent_name,
                        interaction_type="BID_WON",
                        description=f"Won bid for: {desc[:200]}",
                        request_payload={"task_description": desc},
                        response_payload={
                            "confidence": neg_result.winner.confidence,
                            "tools": neg_result.winner.tools_available,
                            "reasoning": neg_result.winner.reasoning,
                        },
                        bid_confidence=neg_result.winner.confidence,
                        trace_id=trace_id,
                    )

                    # Audit: bid won per node
                    try:
                        await audit.write(
                            trace_id=trace_id,
                            actor=neg_result.winner.agent_id or "unknown",
                            actor_type="AGENT",
                            action="pipeline.bid_won",
                            resource_type="TaskNode",
                            resource_id=node_id,
                            payload={
                                "agent_id": neg_result.winner.agent_id,
                                "agent_name": neg_result.winner.agent_name,
                                "confidence": neg_result.winner.confidence,
                            },
                        )
                    except Exception:
                        pass
            except Exception as exc:
                logger.warning(
                    "Negotiation failed for subtask; using fallback assignment",
                    layer="service",
                    description=desc[:80],
                    error=str(exc),
                    trace_id=trace_id,
                )

        # ------------------------------------------------------------------
        # Phase 4 — complementary cover. When a negotiation produced
        # multiple complementary winners (no single bid spans the question),
        # spawn additional sibling subtask nodes — one per non-top winner —
        # each tailored to that agent's `coverage.answerable` slice. The
        # original subtask node keeps the top winner; the new nodes get
        # their own assigned_agent_id stamped. The execution step picks
        # them up in the next graph_nodes refresh.
        # ------------------------------------------------------------------
        complementary_spawned = 0
        for original_desc, neg_result in list(results.items()):
            cw = neg_result.complementary_winners or []
            if len(cw) <= 1:
                continue
            original_node = next(
                (n for n in subtask_nodes if n.get("description") == original_desc),
                None,
            )
            parent_id = (
                original_node.get("parent_id")
                or original_node.get("parent_node_id")
                or ""
            ) if original_node else ""
            depth = int(original_node.get("depth") or 1) if original_node else 1
            criticality = (
                original_node.get("criticality") or Criticality.MEDIUM
            ) if original_node else Criticality.MEDIUM
            ds_bindings = (
                [str(b) for b in (original_node.get("dataset_bindings") or [])]
                if original_node else []
            )

            # cw[0] is the top winner — already assigned to the original
            # node by `assign_winner_to_graph`. Skip and spawn the rest.
            for sibling_winner in cw[1:]:
                slice_text = ", ".join(
                    sibling_winner.coverage.answerable
                    if sibling_winner.coverage
                    else []
                ) or "complementary slice"
                new_desc = (
                    f"[{sibling_winner.agent_name} slice: {slice_text}] {original_desc}"
                )
                try:
                    new_node_id = await self._graph_mgr.add_node(
                        graph_id=graph_id,
                        parent_id=parent_id or None,
                        description=new_desc,
                        criticality=criticality,
                        depth=depth,
                        trace_id=trace_id,
                        dataset_bindings=ds_bindings or None,
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed to spawn complementary sibling node; "
                        "skipping",
                        layer="service",
                        graph_id=graph_id,
                        original_desc=original_desc[:80],
                        sibling_agent=sibling_winner.agent_name,
                        error=str(exc),
                        trace_id=trace_id,
                    )
                    continue

                # Stamp this sibling's assignment onto its own node so the
                # execution step picks the right agent.
                try:
                    await self._negotiation.assign_winner_to_graph(
                        task_id=new_node_id,
                        graph_id=graph_id,
                        winner=sibling_winner,
                        fallback_chain=[],
                        trace_id=trace_id,
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed to stamp complementary winner on graph",
                        layer="service",
                        graph_id=graph_id,
                        new_node_id=new_node_id,
                        error=str(exc),
                        trace_id=trace_id,
                    )

                # Mirror the result into the per-description map so the
                # caller's assignment loop picks up this agent.
                sibling_result = NegotiationResult(
                    task_id=new_node_id,
                    task_description=new_desc,
                    winner=sibling_winner,
                    fallback_chain=[],
                    all_bids=neg_result.all_bids,
                    negotiation_time_ms=neg_result.negotiation_time_ms,
                    trace_id=trace_id,
                )
                results[new_desc] = sibling_result
                complementary_spawned += 1

        if complementary_spawned:
            logger.info(
                "Complementary cover expanded subtasks",
                layer="service",
                graph_id=graph_id,
                spawned=complementary_spawned,
                trace_id=trace_id,
            )

        return results, bandit_decisions

    # ------------------------------------------------------------------
    # Steps 4-7: EXECUTION with correction and expansion
    # ------------------------------------------------------------------

    async def _step4_to_7_execution(
        self,
        graph_id: str,
        root_node_id: str,
        node_descriptions: List[str],
        primary: Optional[Agent],
        fallbacks: List[Agent],
        message: str,
        trace_id: str,
        agent_assignments: Optional[Dict[str, Agent]] = None,
        negotiation_results: Optional[Dict[str, NegotiationResult]] = None,
        team_context: str = "",
    ) -> List[Dict[str, Any]]:
        """Execute each sub-task node with scoring, correction, and graph expansion.

        If agent_assignments is provided, each subtask is executed with its assigned agent.
        Nodes whose assigned agents have execution_mode='parallel' at the same hierarchy
        level are dispatched concurrently via asyncio.gather().
        """
        agent_assignments = agent_assignments or {}
        negotiation_results = negotiation_results or {}
        node_results: List[Dict[str, Any]] = []
        graph_nodes = await self._graph_mgr.get_graph_nodes(graph_id, trace_id=trace_id)
        # Filter to SUBTASK nodes only (skip root). Phase A.4: also drop nodes
        # that were already completed in a prior outer-loop round so this
        # method is idempotent — re-calling it on the same graph after delta
        # decomposition only executes the *new* PENDING nodes.
        _executed_states = {"COMPLETED", "FAILED", "ESCALATED"}
        subtask_nodes = [
            n for n in graph_nodes
            if n.get("node_type") == "SUBTASK"
            and (n.get("status") or "").upper() not in _executed_states
        ]

        # Determine if we can execute nodes in parallel
        # Group nodes by whether their assigned agent has execution_mode='parallel'
        parallel_nodes: List[Dict[str, Any]] = []
        sequential_nodes: List[Dict[str, Any]] = []

        for node in subtask_nodes:
            description = node.get("description", "")
            assigned = agent_assignments.get(description)
            if assigned and assigned.raw.get("execution_mode") == "parallel":
                parallel_nodes.append(node)
            else:
                sequential_nodes.append(node)

        # Execute parallel nodes concurrently
        if parallel_nodes:
            async def _execute_parallel_node(node: Dict[str, Any]) -> Dict[str, Any]:
                node_id = node.get("node_id", "")
                description = node.get("description", "")
                criticality = node.get("criticality", Criticality.MEDIUM)
                assigned = agent_assignments.get(description)
                node_primary = assigned if assigned else primary
                # Build fallback list: all agents except the assigned one
                node_fallbacks = [a for a in fallbacks if a.agent_id != (node_primary.agent_id if node_primary else "")]
                # Check for explicit fallback_agent_id
                if assigned and assigned.raw.get("fallback_agent_id"):
                    fb_id = str(assigned.raw["fallback_agent_id"])
                    all_agents = ([primary] if primary else []) + fallbacks
                    fb_agent = next((a for a in all_agents if a.agent_id == fb_id), None)
                    if fb_agent:
                        node_fallbacks = [fb_agent] + [a for a in node_fallbacks if a.agent_id != fb_id]
                return await self._execute_single_node(
                    node_id=node_id,
                    description=description,
                    criticality=criticality,
                    graph_id=graph_id,
                    primary=node_primary,
                    fallbacks=node_fallbacks,
                    trace_id=trace_id,
                    team_context=team_context,
                )

            parallel_results = await asyncio.gather(
                *[_execute_parallel_node(n) for n in parallel_nodes],
                return_exceptions=True,
            )
            for i, result in enumerate(parallel_results):
                if isinstance(result, Exception):
                    node = parallel_nodes[i]
                    logger.error(
                        "Parallel node execution failed",
                        layer="service",
                        node_id=node.get("node_id"),
                        error=str(result),
                        trace_id=trace_id,
                    )
                    node_results.append({
                        "node_id": node.get("node_id", ""),
                        "description": node.get("description", ""),
                        "llm_response": "",
                        "score": 0.0,
                        "status": "FAILED",
                        "error": str(result),
                    })
                else:
                    node_results.append(result)

        # Execute sequential nodes one at a time
        for node in sequential_nodes:
            node_id = node.get("node_id", "")
            description = node.get("description", "")
            criticality = node.get("criticality", Criticality.MEDIUM)

            # Use assigned agent if available, else fall back to primary
            assigned = agent_assignments.get(description)
            node_primary = assigned if assigned else primary
            node_fallbacks = list(fallbacks)
            # If an explicit fallback_agent_id is set on the assigned agent, prioritize it
            if assigned and assigned.raw.get("fallback_agent_id"):
                fb_id = str(assigned.raw["fallback_agent_id"])
                all_agents = ([primary] if primary else []) + fallbacks
                fb_agent = next((a for a in all_agents if a.agent_id == fb_id), None)
                if fb_agent:
                    node_fallbacks = [fb_agent] + [a for a in node_fallbacks if a.agent_id != fb_id]

            # Feature: Speculative execution for CRITICAL tasks
            if str(criticality) == Criticality.CRITICAL and node_primary and node_fallbacks:
                result = await self._execute_speculative(
                    node_id=node_id,
                    description=description,
                    criticality=criticality,
                    graph_id=graph_id,
                    agent_a=node_primary,
                    agent_b=node_fallbacks[0],
                    remaining_fallbacks=node_fallbacks[1:],
                    trace_id=trace_id,
                )
            else:
                result = await self._execute_single_node(
                    node_id=node_id,
                    description=description,
                    criticality=criticality,
                    graph_id=graph_id,
                    primary=node_primary,
                    fallbacks=node_fallbacks,
                    trace_id=trace_id,
                    team_context=team_context,
                )
            node_results.append(result)

            # Step 7: INTERMEDIATE EXPANSION
            if result.get("llm_response"):
                new_ids = await self._graph_mgr.expand_graph_from_response(
                    graph_id=graph_id,
                    parent_node_id=node_id,
                    llm_response=result["llm_response"],
                    iteration=1,
                    parent_depth=node.get("depth", 1),
                    trace_id=trace_id,
                )
                if new_ids:
                    logger.info(
                        "Graph expanded from intermediate response",
                        layer="service",
                        new_nodes=len(new_ids),
                        graph_id=graph_id,
                        trace_id=trace_id,
                    )
                    # Execute expanded nodes with the same agent
                    for new_node_id in new_ids:
                        expanded_result = await self._execute_single_node(
                            node_id=new_node_id,
                            description=result["llm_response"][:200],
                            criticality=criticality,
                            graph_id=graph_id,
                            primary=node_primary,
                            fallbacks=node_fallbacks,
                            trace_id=trace_id,
                            team_context=team_context,
                        )
                        node_results.append(expanded_result)

        return node_results

    # ------------------------------------------------------------------
    # Phase A.4: outer sufficiency loop + delta re-decomposition
    # ------------------------------------------------------------------

    # Cap outer rounds to bound cost. Round 1 is the initial decomposition
    # already executed by the existing pipeline; rounds 2..MAX add delta
    # nodes from the sufficiency judge's identified gaps.
    MAX_OUTER_ROUNDS = 3
    SUFFICIENCY_BAND = 0.7  # forces sufficient=False if avg score below this
    # Phase B.2: marginal-improvement plateau threshold. If the average
    # node score did not improve by at least this much between two
    # consecutive outer rounds, stop iterating — adding more sub-tasks is
    # unlikely to help and just burns tokens.
    PLATEAU_EPSILON = 0.03

    async def _sufficiency_judge(
        self,
        *,
        user_message: str,
        intent: str,
        node_results: List[Dict[str, Any]],
        final_response: str,
        round_n: int,
        trace_id: str,
    ) -> Dict[str, Any]:
        """LLM judge: did the team fully address the user's question?

        Returns ``{"sufficient": bool, "gaps": [str], "reason": str,
        "avg_score": float|None, "below_band_count": int}``. Never raises —
        returns ``sufficient=True`` on any failure so a broken judge cannot
        prevent the pipeline from returning.
        """
        scores: List[float] = []
        findings: List[Dict[str, Any]] = []
        for nr in node_results or []:
            s = nr.get("score")
            if s is not None:
                try:
                    scores.append(float(s))
                except Exception:
                    pass
            findings.append({
                "task": (nr.get("description") or "")[:240],
                "response": (nr.get("llm_response") or "")[:480],
                "score": s,
                "status": nr.get("status"),
            })

        avg_score = (sum(scores) / len(scores)) if scores else None
        below_band = sum(1 for s in scores if s < self.SUFFICIENCY_BAND)

        # Cheap escape hatch: nothing to judge.
        if not findings:
            return {
                "sufficient": True,
                "gaps": [],
                "reason": "no node results to judge",
                "avg_score": avg_score,
                "below_band_count": below_band,
            }

        prompt = (
            "You evaluate whether a team of AI agents has fully addressed a user's question.\n\n"
            f"USER QUESTION:\n{(user_message or '')[:2000]}\n\n"
            f"DETECTED INTENT: {intent or 'unknown'}\n\n"
            f"ACCUMULATED FINDINGS ({len(findings)} sub-tasks executed across {round_n} round(s)):\n"
            f"{json.dumps(findings[:20], default=str)[:6000]}\n\n"
            f"PROPOSED FINAL ANSWER:\n{(final_response or '')[:2000]}\n\n"
            "DECIDE:\n"
            "1. Does the proposed final answer fully address every aspect of the user's question?\n"
            "2. If not, list specific gaps that would benefit from additional sub-tasks.\n"
            "3. Be strict but not pedantic — only mark insufficient when a real, actionable gap remains.\n\n"
            "Output STRICT JSON only (no prose):\n"
            '{"sufficient": true|false, "gaps": ["concrete gap 1", "concrete gap 2"], "reason": "one-line"}'
        )

        try:
            raw = await self._llm.complete(
                messages=[{"role": "user", "content": prompt}],
                trace_id=trace_id,
            )
        except Exception as exc:
            logger.warning(
                "sufficiency_judge_llm_failed",
                layer="service",
                error=str(exc)[:300],
                trace_id=trace_id,
            )
            return {
                "sufficient": True,  # don't keep looping when the judge breaks
                "gaps": [],
                "reason": f"judge failed: {str(exc)[:120]}",
                "avg_score": avg_score,
                "below_band_count": below_band,
            }

        data: Dict[str, Any] = {}
        if isinstance(raw, str):
            try:
                data = json.loads(raw.strip())
            except Exception:
                m = re.search(r"\{.*\}", raw, re.DOTALL)
                if m:
                    try:
                        data = json.loads(m.group(0))
                    except Exception:
                        data = {}

        sufficient_judge = bool(data.get("sufficient", True))
        gaps = [str(g)[:300] for g in (data.get("gaps") or []) if g]
        reason = str(data.get("reason") or "")[:500]

        # Score gate: even if the LLM judge says sufficient, force another
        # round when the average score is below the adaptive band — this is
        # how Property 3 (feedback closes the loop) plugs into Property 1.
        score_forces_iter = (
            avg_score is not None
            and avg_score < self.SUFFICIENCY_BAND
            and below_band > 0
            and round_n < self.MAX_OUTER_ROUNDS
        )
        if score_forces_iter and sufficient_judge:
            sufficient_judge = False
            reason = (
                f"score gate forced iteration: avg={avg_score:.2f} < band {self.SUFFICIENCY_BAND}"
                f" ({below_band} below-band node(s)). " + reason
            )
            if not gaps:
                gaps = ["scores indicate weak coverage; team should refine the lowest-scoring sub-tasks"]

        return {
            "sufficient": sufficient_judge,
            "gaps": gaps,
            "reason": reason,
            "avg_score": avg_score,
            "below_band_count": below_band,
        }

    async def _fetch_recent_user_feedback(
        self,
        *,
        conversation_id: str,
        limit: int = 5,
        trace_id: str = "",
    ) -> str:
        """Pull recent rows from ``user_feedback`` and render them as a
        compact context block. Returns "" when there's nothing useful or
        the lookup fails. NEVER raises.
        """
        if not conversation_id:
            return ""

        def _query() -> List[Dict[str, Any]]:
            cfg = {
                "host": getattr(settings, "mysql_host", "localhost"),
                "port": getattr(settings, "mysql_port", 3306),
                "user": getattr(settings, "mysql_user", "root"),
                "password": getattr(settings, "mysql_password", ""),
                "database": getattr(settings, "mysql_db", "pmos"),
                "connection_timeout": 5,
            }
            conn = mysql.connector.connect(**cfg)
            try:
                cur = conn.cursor(dictionary=True)
                cur.execute(
                    """
                    SELECT rating, comment, created_at, turn_id
                    FROM user_feedback
                    WHERE conversation_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (conversation_id, int(limit)),
                )
                rows = cur.fetchall() or []
                cur.close()
                return rows
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

        try:
            loop = asyncio.get_event_loop()
            rows = await loop.run_in_executor(None, _query)
        except Exception as exc:
            try:
                logger.warning(
                    "user_feedback_fetch_failed",
                    layer="service",
                    error=str(exc)[:300],
                    trace_id=trace_id,
                )
            except Exception:
                pass
            return ""

        if not rows:
            return ""

        lines: List[str] = ["[CARRIED-OVER USER FEEDBACK FROM PRIOR TURNS — adjust your plan accordingly]"]
        for r in rows:
            rating = (r.get("rating") or "NEUTRAL").upper()
            comment = (r.get("comment") or "").strip()
            if not comment and rating == "NEUTRAL":
                continue
            symbol = "👍" if rating == "UP" else ("👎" if rating == "DOWN" else "•")
            if comment:
                if len(comment) > 280:
                    comment = comment[:280] + "…"
                lines.append(f"- {symbol} {rating}: {comment}")
            else:
                lines.append(f"- {symbol} {rating}")
        if len(lines) == 1:  # only the header
            return ""
        lines.append("[END USER FEEDBACK]")
        return "\n".join(lines)

    async def _delta_decompose(
        self,
        *,
        graph_id: str,
        root_node_id: str,
        user_message: str,
        intent: str,
        gaps: List[str],
        prior_findings_summary: str,
        round_n: int,
        trace_id: str,
    ) -> List[str]:
        """Slim re-decomposition: turn the judge's gap list into 1-3 new
        SUBTASK nodes attached to the existing graph at iteration=round_n.
        Returns the list of new sub-task descriptions actually added.
        """
        if not gaps:
            return []

        prompt = (
            "You are a task decomposer adding follow-up sub-tasks to an in-flight team execution.\n"
            "The team already produced an answer that the sufficiency judge marked INSUFFICIENT.\n\n"
            f"USER QUESTION:\n{(user_message or '')[:1500]}\n\n"
            f"DETECTED INTENT: {intent or 'unknown'}\n\n"
            f"PRIOR FINDINGS SUMMARY (truncated):\n{(prior_findings_summary or '')[:2500]}\n\n"
            "REMAINING GAPS the team must close:\n"
            + "\n".join(f"- {g}" for g in gaps[:8]) + "\n\n"
            "Produce 1-3 NEW concrete, executable sub-tasks that close these gaps. "
            "Do NOT repeat work that's already been done. Each sub-task should be one sentence.\n\n"
            "Output STRICT JSON only — an array of strings:\n"
            '["sub-task 1", "sub-task 2"]'
        )

        try:
            raw = await self._llm.complete(
                messages=[{"role": "user", "content": prompt}],
                trace_id=trace_id,
            )
        except Exception as exc:
            logger.warning(
                "delta_decompose_llm_failed",
                layer="service",
                error=str(exc)[:300],
                trace_id=trace_id,
            )
            return []

        new_descs: List[str] = []
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw.strip())
                if isinstance(parsed, list):
                    new_descs = [str(t).strip() for t in parsed if t]
            except Exception:
                m = re.search(r"\[.*\]", raw, re.DOTALL)
                if m:
                    try:
                        parsed = json.loads(m.group(0))
                        if isinstance(parsed, list):
                            new_descs = [str(t).strip() for t in parsed if t]
                    except Exception:
                        pass

        # Cap to 3 to bound cost; drop empties.
        new_descs = [d for d in new_descs if d][:3]
        if not new_descs:
            return []

        # Persist new SUBTASK nodes attached to the existing root.
        for desc in new_descs:
            try:
                await self._graph_mgr.add_node(
                    graph_id=graph_id,
                    parent_id=root_node_id,
                    description=desc,
                    node_type=NodeType.SUBTASK,
                    depth=1,
                    iteration=round_n,
                    trace_id=trace_id,
                )
            except Exception as exc:
                logger.warning(
                    "delta_decompose_add_node_failed",
                    layer="service",
                    error=str(exc)[:300],
                    desc=desc[:120],
                    trace_id=trace_id,
                )

        return new_descs

    # ------------------------------------------------------------------
    # Speculative execution helpers (CRITICAL tasks)
    # ------------------------------------------------------------------

    async def _try_agent_execution(
        self,
        agent: Agent,
        description: str,
        graph_id: str,
        trace_id: str,
    ) -> Dict[str, Any]:
        """Execute with an agent and return result dict.

        Does NOT update Neo4j node status — used for speculative execution
        where two agents race and only the winner's result is applied.
        """
        agent_id = self._resolve_agent_db_id(agent) or 0
        agent_uuid = agent.agent_id
        start = time.monotonic()

        # Memory pull
        system_prompt = ""
        try:
            mem_data = await self._cb_memory.call(
                self._memory.assemble_prompt,
                agent_id=agent_id,
                context={"task_type": "general", "domain": "", "recent_messages": [description]},
                trace_id=trace_id,
            )
            system_prompt = mem_data.get("system_prompt", "")
        except (CircuitBreakerOpenError, Exception):
            pass

        # RAG retrieval
        rag_context = ""
        try:
            rag_data = await self._cb_rag.call(
                self._rag.query,
                query=description,
                agent_id=agent_id,
                task_id="",
                domain="",
                trace_id=trace_id,
            )
            rag_results = rag_data.get("results", []) if rag_data else []
            if rag_results:
                rag_context = "\n\n== Retrieved Documents ==\n"
                for r in rag_results[:5]:
                    rag_context += f"- {r.get('content', '')[:500]}\n"
        except (CircuitBreakerOpenError, Exception):
            pass

        base_prompt = system_prompt or "You are a helpful expert assistant."
        if rag_context:
            base_prompt += rag_context

        llm_response, tool_calls_made = await self._execute_agent_with_tools(
            agent=agent,
            agent_id=agent_uuid or str(agent_id),
            system_prompt=base_prompt,
            task_description=description,
            trace_id=trace_id,
            graph_id=graph_id,
        )

        latency_ms = int((time.monotonic() - start) * 1000)

        # Score
        score_data: Dict[str, Any] = {}
        try:
            score_data = await self._cb_scoring.call(
                self._scoring.evaluate,
                agent_id=agent_id,
                task_id="",
                context_type="general",
                response_text=llm_response,
                used_knowledge=bool(system_prompt),
                latency_ms=latency_ms,
                trace_id=trace_id,
            )
        except (CircuitBreakerOpenError, Exception):
            score_data = {"score": 0.75, "band": {"low": 0.5, "high": 1.0}, "recommendation": "proceed"}

        score = score_data.get("score", 0.75)
        band = score_data.get("band", {})
        band_low = band.get("low", 0.5)
        recommendation = score_data.get("recommendation", "proceed")

        status = "SUCCESS" if (score >= band_low or recommendation == "proceed") else "BELOW_BAND"

        return {
            "llm_response": llm_response,
            "score": score,
            "status": status,
            "agent": agent,
            "agent_id": str(agent_id),
            "agent_name": agent.name,
            "tools_used": tool_calls_made,
            "latency_ms": latency_ms,
            "description": description,
        }

    async def _execute_speculative(
        self,
        node_id: str,
        description: str,
        criticality: str,
        graph_id: str,
        agent_a: Agent,
        agent_b: Agent,
        remaining_fallbacks: List[Agent],
        trace_id: str,
    ) -> Dict[str, Any]:
        """Launch 2 agents simultaneously for CRITICAL tasks. First to succeed wins."""
        logger.info(
            "Speculative execution: launching 2 agents for CRITICAL task",
            layer="service",
            node_id=node_id,
            agent_a=agent_a.name,
            agent_b=agent_b.name,
            trace_id=trace_id,
        )

        await self._graph_mgr.mark_node_running(node_id, trace_id=trace_id)

        # Log speculative launch interaction
        await self._interaction_logger.log_interaction(
            task_id=node_id,
            graph_id=graph_id,
            agent_id="orchestrator",
            agent_name="Orchestrator",
            interaction_type="SPECULATIVE_LAUNCH",
            description=f"Launching {agent_a.name} and {agent_b.name} in parallel for CRITICAL task",
            response_payload={"agents": [agent_a.name, agent_b.name]},
            latency_ms=0,
            tools_used=[],
            trace_id=trace_id,
        )

        # Create two tasks
        task_a = asyncio.create_task(
            self._try_agent_execution(agent_a, description, graph_id, trace_id)
        )
        task_b = asyncio.create_task(
            self._try_agent_execution(agent_b, description, graph_id, trace_id)
        )

        # Wait for first to complete
        done, pending = await asyncio.wait(
            [task_a, task_b],
            return_when=asyncio.FIRST_COMPLETED,
            timeout=60.0,
        )

        # Check completed tasks for a successful result
        winner = None
        for task in done:
            try:
                result = task.result()
                if result.get("status") in ("SUCCESS", "AUTO_CORRECTED"):
                    winner = result
                    break
            except Exception:
                pass

        # Cancel pending tasks
        for task in pending:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        if winner:
            # Apply the winner's result to the real node
            latency_ms = winner.get("latency_ms", 0)
            score = winner.get("score", 0.75)
            await self._graph_mgr.mark_node_success(node_id, score, latency_ms, trace_id=trace_id)

            # Log which agent won
            await self._interaction_logger.log_interaction(
                task_id=node_id,
                graph_id=graph_id,
                agent_id=winner.get("agent_id", ""),
                agent_name=winner.get("agent_name", ""),
                interaction_type="SPECULATIVE_WINNER",
                description=f"Agent {winner.get('agent_name')} won speculative execution (score={score:.2f})",
                response_payload={"score": score, "tools_used": winner.get("tools_used", [])},
                latency_ms=latency_ms,
                tools_used=winner.get("tools_used", []),
                trace_id=trace_id,
            )

            logger.info(
                "Speculative execution winner selected",
                layer="service",
                node_id=node_id,
                winner_agent=winner.get("agent_name"),
                score=score,
                trace_id=trace_id,
            )

            return {
                "node_id": node_id,
                "description": description,
                "llm_response": winner.get("llm_response", ""),
                "score": score,
                "status": "SUCCESS",
                "agent_id": winner.get("agent_id", ""),
                "agent_name": winner.get("agent_name", ""),
                "tools_used": winner.get("tools_used", []),
                "speculative": True,
            }

        # If first-completed weren't successful, check if any pending finished meanwhile
        for task in done:
            try:
                result = task.result()
                if result:  # Any result is better than none
                    winner = result
                    break
            except Exception:
                pass

        if winner:
            score = winner.get("score", 0.0)
            await self._graph_mgr.mark_node_success(node_id, score, winner.get("latency_ms", 0), trace_id=trace_id)
            return {
                "node_id": node_id,
                "description": description,
                "llm_response": winner.get("llm_response", ""),
                "score": score,
                "status": "AUTO_CORRECTED",
                "agent_id": winner.get("agent_id", ""),
                "agent_name": winner.get("agent_name", ""),
                "tools_used": winner.get("tools_used", []),
                "speculative": True,
            }

        # Both truly failed — fall through to remaining fallbacks sequentially
        logger.warning(
            "Speculative execution: both agents failed, trying remaining fallbacks",
            layer="service",
            node_id=node_id,
            remaining_fallbacks=len(remaining_fallbacks),
            trace_id=trace_id,
        )

        if remaining_fallbacks:
            return await self._execute_single_node(
                node_id=node_id,
                description=description,
                criticality=criticality,
                graph_id=graph_id,
                primary=remaining_fallbacks[0],
                fallbacks=remaining_fallbacks[1:],
                trace_id=trace_id,
                team_context="",
            )

        # No fallbacks left
        await self._graph_mgr.mark_node_failed(node_id, trace_id=trace_id)
        return {
            "node_id": node_id,
            "description": description,
            "llm_response": "",
            "score": 0.0,
            "status": "FAILED",
            "error": "Speculative execution failed for all agents",
            "speculative": True,
        }

    async def _execute_single_node(
        self,
        node_id: str,
        description: str,
        criticality: str,
        graph_id: str,
        primary: Optional[Agent],
        fallbacks: List[Agent],
        trace_id: str,
        team_context: str = "",
    ) -> Dict[str, Any]:
        """Execute one TaskNode with per-agent tool execution, fallback, and course-correction."""
        await self._graph_mgr.mark_node_running(node_id, trace_id=trace_id)
        start = time.monotonic()

        agent = primary
        agent_uuid = agent.agent_id if agent else ""
        agent_id = self._resolve_agent_db_id(agent) or 0
        fallback_index = 0
        # Phase B.1: track auto-correct retries per (node, agent). Cap at 1
        # so we don't spin forever — if the same agent still scores below
        # band after the corrective re-prompt, we fall through to fallback.
        auto_correct_attempted: bool = False
        # Phase B.1: when the auto-correct retry runs, we extend the user
        # task with the corrective context so the LLM actually re-does
        # the work. None on the first attempt; populated by the corrector.
        retry_context: Optional[str] = None

        # Audit: node execution start
        try:
            await audit.write(
                trace_id=trace_id,
                actor=(agent_uuid or (agent.name if agent else "orchestrator")),
                actor_type="AGENT" if agent else "SERVICE",
                action="pipeline.node_started",
                resource_type="TaskNode",
                resource_id=node_id,
                payload={
                    "graph_id": graph_id,
                    "agent_id": agent_uuid,
                    "agent_name": agent.name if agent else None,
                    "criticality": str(criticality),
                    "description": (description or "")[:240],
                },
            )
        except Exception:
            pass

        while True:
            try:
                # Step 4a: Memory pull
                system_prompt = ""
                try:
                    mem_data = await self._cb_memory.call(
                        self._memory.assemble_prompt,
                        agent_id=agent_id,
                        context={"task_type": "general", "domain": "", "recent_messages": [description]},
                        trace_id=trace_id,
                    )
                    system_prompt = mem_data.get("system_prompt", "")
                except CircuitBreakerOpenError:
                    logger.warning(
                        "Memory CB open; proceeding without assembled prompt",
                        layer="service",
                        trace_id=trace_id,
                    )
                except Exception as exc:
                    logger.warning(
                        "Memory prompt assembly failed (non-fatal)",
                        layer="service",
                        error=str(exc),
                        trace_id=trace_id,
                    )

                # Step 4b: RAG retrieval — query for relevant documents
                rag_context = ""
                try:
                    rag_data = await self._cb_rag.call(
                        self._rag.query,
                        query=description,
                        agent_id=agent_id,
                        task_id=node_id,
                        domain="",
                        trace_id=trace_id,
                    )
                    rag_results = rag_data.get("results", []) if rag_data else []
                    if rag_results:
                        rag_context = "\n\n== Retrieved Documents ==\n"
                        for r in rag_results[:5]:
                            rag_context += f"- {r.get('content', '')[:500]}\n"
                except CircuitBreakerOpenError:
                    logger.warning(
                        "RAG CB open; proceeding without document retrieval",
                        layer="service",
                        trace_id=trace_id,
                    )
                except Exception as exc:
                    logger.warning(
                        "RAG retrieval failed (non-fatal)",
                        layer="service",
                        error=str(exc),
                        trace_id=trace_id,
                    )

                # Step 4c: Per-agent tool execution via sandbox
                base_prompt = system_prompt or "You are a helpful expert assistant."
                if team_context:
                    base_prompt += f"\n\n{team_context}\n\nIMPORTANT: You are part of this team. Only reference agents and tools listed above. When asked about your team, answer from this context."
                if rag_context:
                    base_prompt += rag_context

                # Phase 5 — Bid contract. If this node has a structured bid
                # plan/coverage stamped by capability_negotiation, prepend it
                # to the system prompt so the agent runs the work it
                # promised at bid time instead of re-discovering schema or
                # over-promising another agent's slice.
                bid_contract = await self._fetch_bid_contract(
                    node_id=node_id, trace_id=trace_id,
                )
                if bid_contract:
                    base_prompt += f"\n\n{bid_contract}"

                # Phase B.1: when the prior attempt scored below band on a
                # HIGH/CRITICAL node, the course corrector hands us a
                # retry_context describing the failure. Append it to the
                # task description so the LLM sees explicit instructions
                # to do better, plus the prior response for reference.
                effective_description = description
                if retry_context:
                    effective_description = f"{description}\n\n{retry_context}"

                llm_response, tool_calls_made = await self._execute_agent_with_tools(
                    agent=agent,
                    agent_id=agent_uuid or str(agent_id),
                    system_prompt=base_prompt,
                    task_description=effective_description,
                    trace_id=trace_id,
                    team_id=getattr(self, '_current_team_id', ''),
                    graph_id=graph_id,
                    node_id=node_id,
                    conversation_id=getattr(self, '_current_conversation_id', ''),
                )

                latency_ms = int((time.monotonic() - start) * 1000)

                # Log interaction (fire-and-forget)
                await self._interaction_logger.log_interaction(
                    task_id=node_id,
                    graph_id=graph_id,
                    agent_id=str(agent_id),
                    agent_name=agent.name if agent else "default",
                    interaction_type="EXECUTION",
                    description=description[:200],
                    response_payload={"response": llm_response[:500], "tool_calls": tool_calls_made},
                    latency_ms=latency_ms,
                    tools_used=tool_calls_made,
                    trace_id=trace_id,
                )

                # Step 4d: Score
                score_data: Dict[str, Any] = {}
                try:
                    score_data = await self._cb_scoring.call(
                        self._scoring.evaluate,
                        agent_id=agent_id,
                        task_id=node_id,
                        context_type="general",
                        response_text=llm_response,
                        used_knowledge=bool(system_prompt),
                        latency_ms=latency_ms,
                        trace_id=trace_id,
                    )
                except CircuitBreakerOpenError:
                    logger.warning(
                        "Scoring CB open; using default score",
                        layer="service",
                        trace_id=trace_id,
                    )
                    score_data = {"score": 0.75, "band": {"low": 0.5, "high": 1.0}, "recommendation": "proceed"}
                except Exception as exc:
                    logger.warning(
                        "Scoring failed (non-fatal)",
                        layer="service",
                        error=str(exc),
                        trace_id=trace_id,
                    )
                    score_data = {"score": 0.75, "band": {"low": 0.5, "high": 1.0}, "recommendation": "proceed"}

                score = score_data.get("score", 0.75)
                band = score_data.get("band", {})
                band_low = band.get("low", 0.5)
                recommendation = score_data.get("recommendation", "proceed")

                # Phase D.2 — learned scorer live blend. When
                # ``scoring_weight_w7_learned`` is > 0, the prediction from
                # the loaded LearnedScorer model is blended into the live
                # heuristic score:
                #     final = (1 - w7) * heuristic + w7 * learned
                # The learned model is the same one already running in
                # SHADOW mode (predict_and_log) — flipping w7 above 0 just
                # promotes its prediction from "logged for analysis" to
                # "blended into the band check".
                heuristic_score = float(score)
                learned_score: Optional[float] = None
                w7 = float(getattr(settings, "scoring_weight_w7_learned", 0.0) or 0.0)
                if w7 > 0.0 and self._learned_scorer.is_loaded():
                    try:
                        # We compute features here (not via predict_and_log)
                        # so we can blend before the band check; a separate
                        # predict_and_log call still fires AFTER step 4-7
                        # so the offline training table keeps growing.
                        from app.services.learned_scorer import extract_features
                        feats = extract_features({
                            "content": llm_response or "",
                            "heuristic_score": heuristic_score,
                            "latency_ms": latency_ms,
                            "tool_call_count": len(tool_calls_made or []),
                            "n_task_nodes": 1,
                            "context_len_chars": len(effective_description or ""),
                            "graph_depth": 1,
                        })
                        learned_score = float(
                            self._learned_scorer._predict_proba(feats)
                        )
                    except Exception as exc:
                        logger.warning(
                            "LearnedScorer live predict failed (non-fatal)",
                            layer="service",
                            error=str(exc),
                            trace_id=trace_id,
                        )
                        learned_score = None

                if learned_score is not None and 0.0 < w7 <= 1.0:
                    blended = (1.0 - w7) * heuristic_score + w7 * learned_score
                    # Surface the rationale BEFORE replacing score so the
                    # band check below consumes the blended value.
                    try:
                        from app.utils.events import events as _events
                        await _events.publish(
                            conversation_id=getattr(self, "_current_conversation_id", "") or "",
                            kind="ml.rationale",
                            trace_id=trace_id,
                            graph_id=graph_id,
                            node_id=node_id,
                            payload={
                                "source": "learned_scorer",
                                "mode": "LIVE",
                                "w7": w7,
                                "heuristic_score": round(heuristic_score, 4),
                                "learned_score": round(learned_score, 4),
                                "blended_score": round(blended, 4),
                                "model_version": self._learned_scorer.version,
                            },
                        )
                    except Exception:
                        pass
                    score = blended

                # Phase A: emit score.evaluated for the timeline UI.
                # Phase D.2: include heuristic + learned components so the
                # UI can show "live=0.74 (heuristic 0.69 + 0.20×learned 0.91)".
                try:
                    from app.utils.events import events as _events
                    await _events.publish(
                        conversation_id=getattr(self, "_current_conversation_id", "") or "",
                        kind="score.evaluated",
                        trace_id=trace_id,
                        graph_id=graph_id,
                        node_id=node_id,
                        status="SUCCESS" if (score >= band_low or recommendation == "proceed") else "BELOW_BAND",
                        payload={
                            "agent_id": str(agent_id) if agent_id else "",
                            "agent_name": agent.name if agent else None,
                            "score": float(score),
                            "heuristic_score": float(heuristic_score),
                            "learned_score": (
                                float(learned_score) if learned_score is not None else None
                            ),
                            "w7_learned": w7,
                            "band_low": float(band_low),
                            "recommendation": recommendation,
                            "criticality": criticality,
                            "latency_ms": latency_ms,
                        },
                    )
                except Exception:
                    pass

                # Schema-meta override: each broadcast subtask is bound to
                # ONE agent's datasources by design — partial coverage is
                # the correct answer, not a failure. The scorer treats
                # "I have no loan_id in my one DB" as low-coverage versus
                # the original question; that bounces to a fallback agent
                # that has nothing useful to offer (GitHubResearcher,
                # PythonAnalyst). Force proceed so the agent's honest
                # per-datasource report flows into step-8 aggregation.
                if description in getattr(self, "_current_schema_meta_descriptions", set()):
                    if recommendation != "proceed":
                        logger.info(
                            "Schema-meta node — forcing proceed despite below-band score",
                            layer="service",
                            node_id=node_id,
                            score=score,
                            band_low=band_low,
                            agent_name=agent.name if agent else "?",
                            trace_id=trace_id,
                        )
                    recommendation = "proceed"

                # Step 4e: Band check
                if score >= band_low or recommendation == "proceed":
                    # Phase B.3: if we got here via an auto-correct retry,
                    # emit auto_correct.completed with improved=True so the
                    # timeline can mark the retry as successful.
                    if auto_correct_attempted:
                        try:
                            from app.utils.events import events as _events
                            await _events.publish(
                                conversation_id=getattr(self, "_current_conversation_id", "") or "",
                                kind="auto_correct.completed",
                                trace_id=trace_id,
                                graph_id=graph_id,
                                node_id=node_id,
                                status="SUCCESS",
                                payload={
                                    "agent_id": str(agent_id) if agent_id else "",
                                    "agent_name": agent.name if agent else None,
                                    "retried": True,
                                    "improved": True,
                                    "final_score": float(score),
                                    "band_low": float(band_low),
                                },
                            )
                        except Exception:
                            pass

                    await self._graph_mgr.mark_node_success(node_id, score, latency_ms, trace_id=trace_id)
                    logger.info(
                        "Node execution succeeded",
                        layer="service",
                        node_id=node_id,
                        agent_id=agent_id,
                        agent_name=agent.name if agent else "default",
                        score=score,
                        latency_ms=latency_ms,
                        tools_used=tool_calls_made,
                        auto_correct_retried=auto_correct_attempted,
                        trace_id=trace_id,
                    )

                    # Audit: node execution complete
                    try:
                        await audit.write(
                            trace_id=trace_id,
                            actor=(agent_uuid or (agent.name if agent else "orchestrator")),
                            actor_type="AGENT" if agent else "SERVICE",
                            action="pipeline.node_completed",
                            resource_type="TaskNode",
                            resource_id=node_id,
                            payload={
                                "score": score,
                                "latency_ms": latency_ms,
                                "status": "SUCCESS",
                                "agent_name": agent.name if agent else None,
                                "tool_calls": len(tool_calls_made or []),
                            },
                        )
                    except Exception:
                        pass

                    return {
                        "node_id": node_id,
                        "description": description,
                        "llm_response": llm_response,
                        "score": score,
                        "status": "SUCCESS",
                        "agent_id": str(agent_id),
                        "agent_name": agent.name if agent else "default",
                        "tools_used": tool_calls_made,
                    }

                # Steps 5-6: COURSE CORRECTION
                correction = await self._corrector.handle_score_failure(
                    node_id=node_id,
                    score=score,
                    band_low=band_low,
                    criticality=criticality,
                    agent_id=agent_id,
                    task_id=node_id,
                    response_text=llm_response,
                    trace_id=trace_id,
                )

                if correction.action == CourseAction.AUTO_CORRECT_LOCAL:
                    # Phase B.1: real retry. If we haven't already burned
                    # our one auto-correct attempt for this (node, agent)
                    # AND the corrector handed us a retry_context, re-run
                    # the inner loop with that context appended. Tracks
                    # before/after score so the timeline can show the diff.
                    if (
                        not auto_correct_attempted
                        and getattr(correction, "retry_context", None)
                    ):
                        auto_correct_attempted = True
                        prior_score = score
                        prior_response = llm_response
                        retry_context = correction.retry_context  # consumed next iter

                        # Phase B.3: emit auto_correct.triggered for the timeline.
                        try:
                            from app.utils.events import events as _events
                            await _events.publish(
                                conversation_id=getattr(self, "_current_conversation_id", "") or "",
                                kind="auto_correct.triggered",
                                trace_id=trace_id,
                                graph_id=graph_id,
                                node_id=node_id,
                                status="BELOW_BAND",
                                payload={
                                    "agent_id": str(agent_id) if agent_id else "",
                                    "agent_name": agent.name if agent else None,
                                    "prior_score": float(prior_score),
                                    "band_low": float(band_low),
                                    "criticality": criticality,
                                    "prior_response_preview": (prior_response or "")[:280],
                                },
                            )
                        except Exception:
                            pass

                        logger.info(
                            "AUTO_CORRECT retry — re-prompting same agent with corrective context",
                            layer="service",
                            node_id=node_id,
                            agent_name=agent.name if agent else "?",
                            prior_score=prior_score,
                            band_low=band_low,
                            trace_id=trace_id,
                        )
                        start = time.monotonic()  # reset latency for retry
                        continue  # re-enter while True with retry_context set

                    # Either we already retried once (and STILL below band)
                    # or there was no retry_context. Treat the original
                    # response as auto-corrected (preserves prior behaviour
                    # so we don't regress the contract for HIGH/CRITICAL).
                    # Phase B.3: emit auto_correct.completed with the diff.
                    try:
                        from app.utils.events import events as _events
                        await _events.publish(
                            conversation_id=getattr(self, "_current_conversation_id", "") or "",
                            kind="auto_correct.completed",
                            trace_id=trace_id,
                            graph_id=graph_id,
                            node_id=node_id,
                            status="SUCCESS" if auto_correct_attempted else "BELOW_BAND",
                            payload={
                                "agent_id": str(agent_id) if agent_id else "",
                                "agent_name": agent.name if agent else None,
                                "retried": auto_correct_attempted,
                                "final_score": float(score),
                                "band_low": float(band_low),
                                "improved": auto_correct_attempted and (score >= band_low),
                            },
                        )
                    except Exception:
                        pass

                    await self._graph_mgr.mark_node_success(node_id, score, latency_ms, trace_id=trace_id)

                    # Audit: node execution complete (auto-corrected)
                    try:
                        await audit.write(
                            trace_id=trace_id,
                            actor=(agent_uuid or (agent.name if agent else "orchestrator")),
                            actor_type="AGENT" if agent else "SERVICE",
                            action="pipeline.node_completed",
                            resource_type="TaskNode",
                            resource_id=node_id,
                            payload={
                                "score": score,
                                "latency_ms": latency_ms,
                                "status": "AUTO_CORRECTED",
                                "agent_name": agent.name if agent else None,
                                "retried": auto_correct_attempted,
                            },
                        )
                    except Exception:
                        pass

                    return {
                        "node_id": node_id,
                        "description": description,
                        "llm_response": llm_response,
                        "score": score,
                        "status": "AUTO_CORRECTED",
                        "agent_id": str(agent_id),
                        "agent_name": agent.name if agent else "default",
                        "tools_used": tool_calls_made,
                        "auto_correct_retried": auto_correct_attempted,
                    }

                # ESCALATE_TO_ORCHESTRATOR -> try fallback agent
                if fallback_index < len(fallbacks):
                    failed_agent_name = agent.name if agent else "unknown"
                    agent = fallbacks[fallback_index]
                    agent_uuid = agent.agent_id if agent else ""
                    agent_id = self._resolve_agent_db_id(agent) or 0
                    fallback_index += 1
                    logger.info(
                        "Switching to fallback agent (score below band)",
                        layer="service",
                        failed_agent=failed_agent_name,
                        failed_score=score,
                        fallback_agent=agent.name if agent else "?",
                        fallback_agent_id=agent.agent_id if agent else "?",
                        fallback_index=fallback_index,
                        remaining_fallbacks=len(fallbacks) - fallback_index,
                        trace_id=trace_id,
                    )
                    # Log the fallback activation
                    await self._interaction_logger.log_interaction(
                        task_id=node_id,
                        graph_id=graph_id,
                        agent_id=agent.agent_id if agent else "",
                        agent_name=agent.name if agent else "fallback",
                        interaction_type="FALLBACK_ACTIVATION",
                        description=f"Fallback #{fallback_index}: {failed_agent_name} failed (score={score:.2f}), trying {agent.name if agent else '?'}",
                        response_payload={"failed_agent": failed_agent_name, "failed_score": score, "fallback_agent": agent.name if agent else "?"},
                        latency_ms=0,
                        tools_used=[],
                        trace_id=trace_id,
                    )
                    start = time.monotonic()  # Reset timer for fallback attempt
                    continue

                # All fallbacks exhausted -> capability gap detection
                logger.warning(
                    "All agents exhausted (primary + fallbacks); triggering capability gap detection",
                    layer="service",
                    node_id=node_id,
                    total_attempts=fallback_index + 1,
                    trace_id=trace_id,
                )
                try:
                    await self._cb_meta.call(
                        self._meta.detect_gap,
                        task_id=node_id,
                        task_type="general",
                        required_tools=[],
                        failed_agents=[agent_id],
                        failure_reasons=[f"score={score} below band_low={band_low}"],
                        trace_id=trace_id,
                    )
                except Exception as exc:
                    logger.error(
                        "Gap detection failed",
                        layer="service",
                        error=str(exc),
                        trace_id=trace_id,
                    )

                await self._graph_mgr.mark_node_failed(node_id, score=score, trace_id=trace_id)

                # Audit: node execution complete (failed)
                try:
                    await audit.write(
                        trace_id=trace_id,
                        actor=(agent_uuid or (agent.name if agent else "orchestrator")),
                        actor_type="AGENT" if agent else "SERVICE",
                        action="pipeline.node_completed",
                        resource_type="TaskNode",
                        resource_id=node_id,
                        severity="WARN",
                        payload={
                            "score": score,
                            "latency_ms": int((time.monotonic() - start) * 1000),
                            "status": "FAILED",
                            "agent_name": agent.name if agent else None,
                        },
                    )
                except Exception:
                    pass

                return {
                    "node_id": node_id,
                    "description": description,
                    "llm_response": llm_response,
                    "score": score,
                    "status": "FAILED",
                }

            except Exception as exc:
                failed_agent_name = agent.name if agent else "unknown"
                logger.error(
                    "Node execution error",
                    layer="service",
                    node_id=node_id,
                    failed_agent=failed_agent_name,
                    error=str(exc),
                    trace_id=trace_id,
                )
                # Try fallback agent on exception
                if fallback_index < len(fallbacks):
                    agent = fallbacks[fallback_index]
                    agent_uuid = agent.agent_id if agent else ""
                    agent_id = self._resolve_agent_db_id(agent) or 0
                    fallback_index += 1
                    logger.info(
                        "Switching to fallback agent (error recovery)",
                        layer="service",
                        failed_agent=failed_agent_name,
                        error=str(exc)[:100],
                        fallback_agent=agent.name if agent else "?",
                        fallback_index=fallback_index,
                        remaining_fallbacks=len(fallbacks) - fallback_index,
                        trace_id=trace_id,
                    )
                    # Log the error fallback
                    await self._interaction_logger.log_interaction(
                        task_id=node_id,
                        graph_id=graph_id,
                        agent_id=agent.agent_id if agent else "",
                        agent_name=agent.name if agent else "fallback",
                        interaction_type="FALLBACK_ERROR_RECOVERY",
                        description=f"Error fallback #{fallback_index}: {failed_agent_name} errored ({str(exc)[:60]}), trying {agent.name if agent else '?'}",
                        response_payload={"failed_agent": failed_agent_name, "error": str(exc)[:200], "fallback_agent": agent.name if agent else "?"},
                        latency_ms=0,
                        tools_used=[],
                        trace_id=trace_id,
                    )
                    start = time.monotonic()  # Reset timer
                    continue
                await self._graph_mgr.mark_node_failed(node_id, trace_id=trace_id)
                return {
                    "node_id": node_id,
                    "description": description,
                    "llm_response": "",
                    "score": 0.0,
                    "status": "FAILED",
                    "error": str(exc),
                    "agents_tried": fallback_index + 1,
                }

    # ------------------------------------------------------------------
    # Per-agent tool execution via sandbox
    # ------------------------------------------------------------------

    async def _fetch_bid_contract(
        self,
        node_id: str,
        trace_id: str = "",
    ) -> str:
        """Read bid_plan/bid_coverage off the TaskNode and render it as a
        commitment block for the agent's system prompt.

        Returns "" when:
          - node_id is empty (legacy / speculative paths),
          - the node has no bid contract stamped (bidding was skipped, e.g.
            schema-meta override),
          - the bid format is 'legacy' (no structured plan to commit to),
          - or the lookup fails (we degrade to today's behaviour rather
            than block the node on Neo4j flakiness).
        """
        if not node_id:
            return ""
        try:
            rows = await self._neo4j.run_query(
                """
                MATCH (n:TaskNode {node_id: $node_id})
                RETURN n.bid_plan AS bid_plan,
                       n.bid_coverage AS bid_coverage,
                       n.bid_plan_format AS bid_plan_format
                """,
                {"node_id": node_id},
                trace_id=trace_id,
            )
        except Exception as exc:
            logger.warning(
                "Bid-contract lookup failed (non-fatal)",
                layer="service",
                node_id=node_id,
                error=str(exc),
                trace_id=trace_id,
            )
            return ""

        if not rows:
            return ""
        row = rows[0]
        plan_format = (row.get("bid_plan_format") or "").lower()
        if plan_format == "legacy":
            return ""
        plan_json = row.get("bid_plan") or ""
        coverage_json = row.get("bid_coverage") or ""
        if not plan_json and not coverage_json:
            return ""

        try:
            plan = json.loads(plan_json) if plan_json else []
        except Exception:
            plan = []
        try:
            coverage = json.loads(coverage_json) if coverage_json else {}
        except Exception:
            coverage = {}

        if not plan and not coverage:
            return ""

        lines: List[str] = ["== BID CONTRACT =="]
        lines.append(
            "At bid time you committed to the following slice of work. "
            "Run this plan. If reality differs (a column is missing, a "
            "join doesn't return rows), deviate and explain why in your "
            "reasoning — but do NOT silently abandon parts you committed to."
        )

        if isinstance(coverage, dict) and coverage.get("answerable"):
            answerable = coverage.get("answerable") or []
            not_ans = coverage.get("not_answerable") or []
            lines.append(
                "\nYour committed parts (answerable): "
                + ", ".join(str(p) for p in answerable)
            )
            if not_ans:
                lines.append(
                    "Other agents handle (not your slice): "
                    + ", ".join(str(p) for p in not_ans)
                )

        plan_kinds: Set[str] = set()
        if isinstance(plan, list) and plan:
            lines.append("\nPlan steps:")
            for i, step in enumerate(plan, start=1):
                if not isinstance(step, dict):
                    continue
                kind = str(step.get("kind") or "").lower()
                if kind:
                    plan_kinds.add(kind)
                tool = step.get("tool") or "?"
                purpose = step.get("purpose") or ""
                sketch = (step.get("sketch") or "")[:600]
                cols = step.get("expected_columns") or []
                lines.append(f"  {i}. tool={tool}  kind={kind or '?'}")
                if purpose:
                    lines.append(f"     purpose: {purpose}")
                if sketch:
                    lines.append(f"     sketch: {sketch}")
                if cols:
                    lines.append(f"     expected_columns: {cols}")

        # When the plan touches a database/graph, demand row-level JSON so
        # the step-8 reducer (Phase 6) can join across agents instead of
        # parsing prose.
        if plan_kinds & {"sql", "cypher"}:
            lines.append(
                "\nOUTPUT: return your data as a JSON array of row objects "
                "inside a fenced ```json block, with the columns named in "
                "`expected_columns` above. Free-text prose is fine for "
                "context, but the structured array is what downstream "
                "reduction will join on."
            )

        return "\n".join(lines)

    async def _execute_agent_with_tools(
        self,
        agent: Optional[Agent],
        agent_id: str,
        system_prompt: str,
        task_description: str,
        trace_id: str,
        team_id: str = "",
        graph_id: str = "",
        node_id: str = "",
        conversation_id: str = "",
    ) -> Tuple[str, List[str]]:
        """Execute an agent with its own tools via the sandbox agent-execute endpoint.

        Returns (llm_response, tool_names_used).
        Falls back to plain LLM completion if tool fetch fails or agent has no tools.
        """
        # 1. Fetch agent's tools from agent-mgmt (using UUID)
        agent_tools: List[Dict[str, Any]] = []
        try:
            agent_tools = await self._cb_agent_mgmt.call(
                self._agent_mgmt.get_agent_tools,
                agent_id=agent_id,
                trace_id=trace_id,
            )
        except CircuitBreakerOpenError:
            logger.warning(
                "Agent-mgmt CB open; executing without tools",
                layer="service",
                agent_id=agent_id,
                trace_id=trace_id,
            )
        except Exception as exc:
            logger.warning(
                "Failed to fetch agent tools; executing without tools",
                layer="service",
                agent_id=agent_id,
                error=str(exc),
                trace_id=trace_id,
            )

        # 2. If agent has tools, use the sandbox agent-execute endpoint
        if agent_tools:
            return await self._call_sandbox_agent_execute(
                agent=agent,
                agent_id=agent_id,
                system_prompt=system_prompt,
                task_description=task_description,
                tools=agent_tools,
                trace_id=trace_id,
                team_id=team_id,
                graph_id=graph_id,
                node_id=node_id,
                conversation_id=conversation_id,
            )

        # 3. Fallback: plain LLM completion (no tools)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task_description},
        ]

        model = agent.foundation_model if agent and agent.foundation_model else None
        provider = None
        if model:
            from app.adapters.llm_adapter import _detect_provider
            provider = _detect_provider(model)

        llm_response = await self._llm.complete(
            messages=messages,
            model=model,
            trace_id=trace_id,
            provider=provider,
        )
        return llm_response, []

    async def _call_sandbox_agent_execute(
        self,
        agent: Optional[Agent],
        agent_id: int,
        system_prompt: str,
        task_description: str,
        tools: List[Dict[str, Any]],
        trace_id: str,
        team_id: str = "",
        graph_id: str = "",
        node_id: str = "",
        conversation_id: str = "",
    ) -> Tuple[str, List[str]]:
        """Call POST /v1/sandbox/agent-execute on localhost with the agent's tools."""
        # Build tool definitions for the sandbox endpoint
        # Tools from agent-mgmt come as {tool_name, tool_type, tool_id, tool_endpoint, tool_auth_config, ...}
        tool_defs = []
        for t in tools:
            tool_config: Dict[str, Any] = {}
            # Parse auth_config which may contain connection strings, base_url, etc.
            auth_config = t.get("tool_auth_config") or t.get("auth_config")
            if auth_config and isinstance(auth_config, dict):
                tool_config.update(auth_config)
            elif auth_config and isinstance(auth_config, str):
                try:
                    tool_config.update(json.loads(auth_config))
                except (json.JSONDecodeError, TypeError):
                    pass
            # Map endpoint to appropriate config key
            endpoint = t.get("tool_endpoint") or t.get("endpoint") or ""
            tool_type = t.get("tool_type", "GENERIC")
            if endpoint:
                tool_config["endpoint"] = endpoint
                if tool_type == "DATABASE":
                    tool_config["connection_string"] = endpoint
                elif tool_type == "GRAPH":
                    tool_config["connection_string"] = endpoint
                    if not tool_config.get("uri"):
                        tool_config["uri"] = endpoint
                elif tool_type == "API":
                    tool_config["base_url"] = endpoint

            tool_defs.append({
                "name": t.get("tool_name") or t.get("name", "unknown"),
                "description": t.get("tool_description") or t.get("description", ""),
                "tool_type": tool_type,
                "tool_id": str(t.get("tool_id", "")),
                "config": tool_config,
            })

        # Detect provider/model from agent
        model = agent.foundation_model if agent and agent.foundation_model else settings.llm_model
        from app.adapters.llm_adapter import _detect_provider
        provider = _detect_provider(model)

        # Build tool executor URL (agent-mgmt tools test endpoint)
        tool_executor_url = f"{settings.agent_mgmt_url}/v1/tools/test"

        # Bugfix: ``agent_id`` reaches this method as the agent's UUID (the
        # same form agent-mgmt expects for /agents/:id/tools). The sandbox
        # endpoint's ``agent_id`` payload field is an INTEGER (the
        # agents.id MySQL primary key) so the prompt assembler / memory
        # refresh paths can join. Resolve via the cache-aware helper; only
        # parse direct int when the caller passed a numeric id (legacy
        # callers / direct invocations).
        _resolved_db_id = self._resolve_agent_db_id(agent)
        if _resolved_db_id is None and agent_id and str(agent_id).isdigit():
            _resolved_db_id = int(agent_id)

        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task_description},
            ],
            "tools": tool_defs,
            "tool_executor_url": tool_executor_url,
            "provider": provider,
            "model": model,
            "temperature": settings.llm_temperature,
            "max_tokens": settings.llm_max_tokens,
            "max_iterations": 5,
            "max_continuations": 3,
            # Sub-agent spawning context
            "team_id": team_id,
            "graph_id": graph_id,
            "parent_node_id": node_id,
            "current_depth": 0,
            "max_sub_agent_depth": settings.max_sub_agent_depth,
            "conversation_id": conversation_id,
            # Phase A: identity for blackboard authorship + per-iteration
            # memory refresh + timeline event attribution.
            "agent_id": _resolved_db_id,
            "agent_name": (agent.name if agent else None),
            "node_id": node_id,
        }

        logger.info(
            "Calling sandbox agent-execute with tools",
            layer="service",
            agent_id=agent_id,
            agent_name=agent.name if agent else "default",
            tool_count=len(tool_defs),
            model=model,
            provider=provider,
            trace_id=trace_id,
        )

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"http://localhost:{settings.orchestrator_port}/v1/sandbox/agent-execute",
                    json=payload,
                    headers={"x-request-id": trace_id, "content-type": "application/json"},
                )
                data = resp.json()

            if data.get("success"):
                tool_names = [tc.get("tool_name", "") for tc in data.get("tool_calls", [])]
                response_text = data.get("response", "")
                logger.info(
                    "Sandbox agent-execute succeeded",
                    layer="service",
                    agent_id=agent_id,
                    tool_calls_count=len(data.get("tool_calls", [])),
                    iterations=data.get("iterations", 0),
                    trace_id=trace_id,
                )
                return response_text, tool_names
            else:
                error = data.get("error", "Unknown sandbox error")
                logger.warning(
                    "Sandbox agent-execute returned error; falling back to plain LLM",
                    layer="service",
                    agent_id=agent_id,
                    error=error,
                    trace_id=trace_id,
                )
                # Fallback to plain LLM
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": task_description},
                ]
                llm_response = await self._llm.complete(
                    messages=messages, model=model, trace_id=trace_id, provider=provider,
                )
                return llm_response, []

        except Exception as exc:
            logger.warning(
                "Sandbox agent-execute call failed; falling back to plain LLM",
                layer="service",
                agent_id=agent_id,
                error=str(exc),
                trace_id=trace_id,
            )
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task_description},
            ]
            model_to_use = model if model else None
            llm_response = await self._llm.complete(
                messages=messages, model=model_to_use, trace_id=trace_id, provider=provider,
            )
            return llm_response, []

    # ------------------------------------------------------------------
    # Step 8: AGGREGATION
    # ------------------------------------------------------------------

    async def _step8_aggregation(
        self,
        message: str,
        node_results: List[Dict[str, Any]],
        graph_id: str,
        primary: Optional[Agent],
        trace_id: str,
    ) -> str:
        """Synthesise all node results into a final response."""
        successful = [r for r in node_results if r.get("status") in ("SUCCESS", "AUTO_CORRECTED")]

        if not successful:
            logger.warning(
                "No successful node results to aggregate",
                layer="service",
                graph_id=graph_id,
                trace_id=trace_id,
            )
            return "I was unable to complete the requested task at this time."

        context_parts = "\n".join(
            f"Sub-task: {r['description']}\nResult: {r['llm_response']}" for r in successful
        )
        aggregation_prompt = (
            "You are a response synthesis agent. "
            "Given the following sub-task results, produce a single coherent, "
            "well-formatted answer to the original user request.\n\n"
            "FORMATTING RULES:\n"
            "- Use Markdown formatting (headers, bold, lists, tables)\n"
            "- When presenting data comparisons, use Markdown tables\n"
            "- When presenting numerical data that could be charted, create a Markdown table AND describe the trend\n"
            "- Use bullet points for lists\n"
            "- Use code blocks for code, SQL, or technical output\n"
            "- Bold key numbers and findings\n"
            "- Be comprehensive but well-structured\n\n"
            f"Original request: {message}\n\n"
            f"Sub-task results:\n{context_parts}\n\n"
            "Synthesised response (use rich Markdown formatting):"
        )
        final = await self._llm.complete(
            messages=[{"role": "user", "content": aggregation_prompt}],
            trace_id=trace_id,
        )
        await self._neo4j.update_graph_status(graph_id, "COMPLETED", trace_id=trace_id)
        return final

    async def _step8_python_reduce(
        self,
        message: str,
        node_results: List[Dict[str, Any]],
        graph_id: str,
        primary: Optional[Agent],
        trace_id: str,
        instructions: str = "",
    ) -> str:
        """Aggregate node results via the team's PYTHON-tool agent.

        LLMs are unreliable at exact arithmetic. When the per-source
        node results are structured numbers (counts, sums, averages,
        breakdowns), routing the reduction through Python is both
        cheaper and more correct.

        Falls back to LLM synthesis (``_step8_aggregation``) when the
        team has no agent with a ``PYTHON`` tool — the system stays
        usable on teams that don't include a PythonAnalyst.
        """
        successful = [
            r for r in node_results
            if r.get("status") in ("SUCCESS", "AUTO_CORRECTED")
        ]
        if not successful:
            logger.warning(
                "No successful node results to python-reduce",
                layer="service",
                graph_id=graph_id,
                trace_id=trace_id,
            )
            return "I was unable to complete the requested task at this time."

        # Find an agent that has a PYTHON tool. ``agents_with_tool_type``
        # already returns agents whose ``tools`` list includes one.
        py_agents = self._last_team_context.agents_with_tool_type("PYTHON")
        if not py_agents:
            logger.info(
                "python_reduce requested but no PYTHON-tool agent on team — "
                "falling back to LLM synthesis",
                layer="service",
                graph_id=graph_id,
                trace_id=trace_id,
            )
            return await self._step8_aggregation(
                message=message,
                node_results=node_results,
                graph_id=graph_id,
                primary=primary,
                trace_id=trace_id,
            )

        py_dict = py_agents[0]
        py_agent = Agent(
            agent_id=str(py_dict.get("agent_id") or ""),
            name=str(py_dict.get("agent_name") or "PythonAnalyst"),
            foundation_model=str(py_dict.get("foundation_model") or settings.llm_model),
            role=str(py_dict.get("role") or "specialist"),
            raw=dict(py_dict),
        )
        agent_db_id = self._resolve_agent_db_id(py_agent) or 0

        # Phase 6 — pull each successful node's bid plan + coverage so the
        # reducer can see what each agent committed to (which columns it
        # promised to return) and infer join keys. A column name appearing
        # in 2+ agents' `expected_columns` is treated as a candidate join
        # key — exactly the mechanism that lets origination.loan_id meet
        # servicing.loan_id in a single pandas merge.
        node_ids = [
            r.get("node_id", "") for r in successful if r.get("node_id")
        ]
        bid_meta_by_node: Dict[str, Dict[str, Any]] = {}
        if node_ids:
            try:
                rows = await self._neo4j.run_query(
                    """
                    UNWIND $ids AS nid
                    MATCH (n:TaskNode {node_id: nid})
                    RETURN n.node_id AS node_id,
                           n.bid_plan AS bid_plan,
                           n.bid_coverage AS bid_coverage,
                           n.bid_plan_format AS bid_plan_format
                    """,
                    {"ids": node_ids},
                    trace_id=trace_id,
                )
                for row in rows or []:
                    nid = row.get("node_id")
                    if not nid:
                        continue
                    fmt = (row.get("bid_plan_format") or "").lower()
                    if fmt == "legacy":
                        continue
                    plan_raw = row.get("bid_plan") or ""
                    cov_raw = row.get("bid_coverage") or ""
                    try:
                        plan = json.loads(plan_raw) if plan_raw else []
                    except Exception:
                        plan = []
                    try:
                        cov = json.loads(cov_raw) if cov_raw else {}
                    except Exception:
                        cov = {}
                    bid_meta_by_node[nid] = {"plan": plan, "coverage": cov}
            except Exception as exc:
                logger.warning(
                    "Reducer bid-meta lookup failed (non-fatal)",
                    layer="service",
                    graph_id=graph_id,
                    error=str(exc),
                    trace_id=trace_id,
                )

        # Compute candidate join keys: any column name that appears in the
        # `expected_columns` of two or more agents' plans.
        col_sources: Dict[str, Set[str]] = {}
        for nid, meta in bid_meta_by_node.items():
            for step in meta.get("plan") or []:
                if not isinstance(step, dict):
                    continue
                for col in step.get("expected_columns") or []:
                    col_sources.setdefault(str(col), set()).add(nid)
        join_keys = sorted(c for c, srcs in col_sources.items() if len(srcs) >= 2)

        # Encode per-source results as a JSON list the agent can paste
        # straight into Python. Truncate each ``llm_response`` so a
        # rambling agent answer doesn't blow up the prompt.
        try:
            payload_items: List[Dict[str, Any]] = []
            for r in successful:
                nid = r.get("node_id", "")
                meta = bid_meta_by_node.get(nid, {})
                expected_columns: List[str] = []
                for step in meta.get("plan") or []:
                    if isinstance(step, dict):
                        for c in step.get("expected_columns") or []:
                            if c and c not in expected_columns:
                                expected_columns.append(str(c))
                cov = meta.get("coverage") or {}
                payload_items.append({
                    "subtask": r.get("description", "")[:500],
                    "agent": r.get("agent_name", ""),
                    "tools_used": r.get("tools_used", []),
                    "expected_columns": expected_columns,
                    "answerable": (cov.get("answerable") or [])[:12],
                    "result": (r.get("llm_response", "") or "")[:8000],
                })
            inputs_payload = json.dumps(payload_items, ensure_ascii=False, indent=2)
        except Exception:
            inputs_payload = json.dumps([], ensure_ascii=False)

        default_instructions = (
            "Aggregate the per-source results into a single coherent answer. "
            "Use your Python tool for any arithmetic or deduplication — do "
            "NOT eyeball numbers. After running Python, return a Markdown "
            "table summarising the per-source results, plus one bold line "
            "with the overall answer."
        )
        body = instructions.strip() or default_instructions

        join_hint_block = ""
        if join_keys:
            join_hint_block = (
                f"\nCANDIDATE JOIN KEYS (columns each agent committed to "
                f"return; appear in two or more sources): {join_keys}\n"
                f"When the per-source results are row-level JSON arrays, "
                f"join them on these keys (pandas.merge) before aggregating "
                f"so cross-schema rows line up. Look for ```json fences in "
                f"each agent's `result` field — those are the row-level "
                f"arrays you can parse with json.loads.\n"
            )

        description = (
            f"Original user request: {message}\n\n"
            f"Per-source results from the multi-tool fan-out (JSON):\n"
            f"```json\n{inputs_payload}\n```\n"
            f"{join_hint_block}"
            f"\nAggregation rules:\n{body}\n\n"
            f"Format: Markdown. Use a table for the breakdown and a bold "
            f"final line for the headline number/result. Do NOT call "
            f"DATABASE/GRAPH tools — those rows above already ran. Only "
            f"call your Python tool."
        )
        system_prompt = (
            "You are a numeric reducer. The fan-out has already happened "
            "and you have the per-source results in front of you. Run "
            "deterministic Python to combine them; return only the final "
            "Markdown answer."
        )

        logger.info(
            "Running step-8 python_reduce",
            layer="service",
            graph_id=graph_id,
            agent_id=py_agent.agent_id,
            agent_name=py_agent.name,
            successful_count=len(successful),
            trace_id=trace_id,
        )

        try:
            response, _ = await self._execute_agent_with_tools(
                agent=py_agent,
                agent_id=py_agent.agent_id or str(agent_db_id),
                system_prompt=system_prompt,
                task_description=description,
                trace_id=trace_id,
                team_id=getattr(self, "_current_team_id", ""),
                graph_id=graph_id,
                node_id="",
                conversation_id=getattr(self, "_current_conversation_id", ""),
            )
        except Exception as exc:
            logger.warning(
                "python_reduce failed — falling back to LLM synthesis",
                layer="service",
                graph_id=graph_id,
                error=str(exc),
                trace_id=trace_id,
            )
            return await self._step8_aggregation(
                message=message,
                node_results=node_results,
                graph_id=graph_id,
                primary=primary,
                trace_id=trace_id,
            )

        await self._neo4j.update_graph_status(graph_id, "COMPLETED", trace_id=trace_id)
        return response or "I was unable to complete the requested task at this time."

    # ------------------------------------------------------------------
    # Step 9: RESPONSE & LEARNING
    # ------------------------------------------------------------------

    async def _step9_learning(
        self,
        session_id: str,
        graph_id: str,
        agent_id: Any,
        final_response: str,
        node_results: List[Dict[str, Any]],
        trace_id: str,
        task_description: str = "",
    ) -> None:
        """Persist session memories and publish scoring feedback."""
        avg_score_pre = (
            sum(float(r.get("score", 0.0) or 0.0) for r in node_results) / len(node_results)
            if node_results else 0.0
        )
        # Async memory write via Redis stream
        try:
            await self._redis.publish_memory_write(
                agent_id=agent_id,
                tier="episodic",
                content=final_response[:2000],
                task_id=graph_id,
                importance=0.7,
                trace_id=trace_id,
                task_description=task_description or "(no task description)",
                score=round(avg_score_pre, 4),
                outcome="SUCCESS" if avg_score_pre >= 0.5 else "PARTIAL",
            )
        except Exception as exc:
            logger.error(
                "Memory write publish failed",
                layer="service",
                error=str(exc),
                trace_id=trace_id,
            )

        # Publish session-completed telemetry
        try:
            avg_score = (
                sum(r.get("score", 0.0) for r in node_results) / len(node_results)
                if node_results
                else 0.0
            )
            await self._redis.publish_telemetry(
                {
                    "event_type": "session_completed",
                    "session_id": session_id,
                    "graph_id": graph_id,
                    "agent_id": str(agent_id),
                    "avg_score": str(avg_score),
                    "node_count": str(len(node_results)),
                },
                trace_id=trace_id,
            )
        except Exception as exc:
            logger.error(
                "Telemetry publish failed",
                layer="service",
                error=str(exc),
                trace_id=trace_id,
            )

    # ------------------------------------------------------------------
    # Scoring feedback consumer handler
    # ------------------------------------------------------------------

    async def handle_scoring_feedback(self, message: Dict[str, Any]) -> None:
        """Called by the Redis consumer for each scoring:feedback message."""
        logger.info(
            "Scoring feedback received",
            layer="service",
            agent_id=message.get("agent_id"),
            score=message.get("score"),
            feedback_type=message.get("feedback_type"),
        )
        # Retrospective band calibration — delegate to scoring service via HTTP
        try:
            agent_id_raw = message.get("agent_id", "0")
            agent_id = int(agent_id_raw) if str(agent_id_raw).isdigit() else 0
            score_raw = message.get("score", "0.0")
            score = float(score_raw) if score_raw else 0.0
            await self._scoring.submit_feedback(
                agent_id=agent_id,
                task_id=str(message.get("task_id", "")),
                feedback_source="ORCHESTRATOR",
                score=score,
            )
        except Exception as exc:
            logger.error(
                "Scoring feedback processing failed",
                layer="service",
                error=str(exc),
            )
