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
import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

import httpx

from app.adapters.agent_mgmt_adapter import AgentMgmtAdapter
from app.adapters.llm_adapter import LLMAdapter
from app.adapters.memory_adapter import MemoryAdapter
from app.adapters.meta_adapter import MetaAdapter
from app.adapters.neo4j_adapter import Neo4jAdapter
from app.adapters.rag_adapter import RAGAdapter
from app.adapters.redis_adapter import RedisAdapter
from app.adapters.scoring_adapter import ScoringAdapter
from app.config import settings
from app.models.bid import BidRequest, BidResponse, NegotiationResult
from app.models.task import Criticality, NodeType, TaskGraph
from app.services.agent_selector import Agent, AgentSelector
from app.services.capability_negotiation import CapabilityNegotiationService
from app.services.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError
from app.services.course_corrector import CourseAction, CourseCorrector
from app.services.graph_manager import GraphManager
from app.services.interaction_logger import InteractionLogger
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
    ) -> None:
        self._neo4j = neo4j
        self._redis = redis
        self._llm = llm
        self._memory = memory
        self._scoring = scoring
        self._rag = rag
        self._meta = meta
        self._agent_mgmt = agent_mgmt or AgentMgmtAdapter()

        self._graph_mgr = GraphManager(neo4j)
        self._agent_sel = AgentSelector(neo4j)
        self._corrector = CourseCorrector(neo4j, redis)

        # Per-downstream circuit breakers
        self._cb_memory = CircuitBreaker("memory")
        self._cb_scoring = CircuitBreaker("scoring")
        self._cb_rag = CircuitBreaker("rag")
        self._cb_meta = CircuitBreaker("meta")
        self._cb_agent_mgmt = CircuitBreaker("agent_mgmt")

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

        logger.info(
            "Pipeline execution started",
            layer="service",
            session_id=session_id,
            conversation_id=conversation_id,
            trace_id=trace_id,
        )

        try:
            # Step 0: LOAD TEAM HIERARCHY into Neo4j + build team context
            team_context = ""
            if team_id:
                team_context = await self._load_team_hierarchy(
                    team_id=team_id,
                    conversation_id=conversation_id,
                    trace_id=trace_id,
                ) or ""

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
            )

            # Step 3: PRE-EXECUTION VALIDATION + CAPABILITY NEGOTIATION
            primary, fallbacks = await self._step3_validation(
                team_id=team_id,
                trace_id=trace_id,
            )

            # Capability Negotiation: broadcast bids for each subtask
            all_agents = ([primary] if primary else []) + fallbacks
            negotiation_results: Dict[str, NegotiationResult] = {}
            agent_assignments: Dict[str, Agent] = {}

            if all_agents and node_descriptions:
                negotiation_results = await self._step3_negotiate(
                    graph_id=graph_id,
                    node_descriptions=node_descriptions,
                    team_agents=all_agents,
                    trace_id=trace_id,
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

            # Step 8: AGGREGATION
            final_response = await self._step8_aggregation(
                message=message,
                node_results=node_results,
                graph_id=graph_id,
                primary=primary,
                trace_id=trace_id,
            )

            # Step 9: RESPONSE & LEARNING
            await self._step9_learning(
                session_id=session_id,
                graph_id=graph_id,
                agent_id=int(primary.agent_id) if (primary and primary.agent_id.isdigit()) else 0,
                final_response=final_response,
                node_results=node_results,
                trace_id=trace_id,
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
            return {
                "session_id": session_id,
                "graph_id": graph_id,
                "response": final_response,
                "score": node_results[-1].get("score") if node_results else None,
                "trace_id": trace_id,
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

            for agent in agents_list:
                a_name = agent.get("agent_name", agent.get("name", "?"))
                a_role = agent.get("role", "specialist")
                a_model = agent.get("foundation_model", "?")
                context_parts.append(f"Agent: {a_name} (role: {a_role}, model: {a_model})")

                # Fetch this agent's tools
                a_id = agent.get("agent_id", "")
                try:
                    tools = await self._agent_mgmt.get_agent_tools(agent_id=a_id, trace_id=trace_id)
                    if tools:
                        tool_names = [t.get("tool_name", t.get("name", "?")) for t in tools]
                        tool_types = [t.get("tool_type", "?") for t in tools]
                        for tn, tt in zip(tool_names, tool_types):
                            context_parts.append(f"  - Tool: {tn} ({tt})")
                    else:
                        context_parts.append("  - No tools assigned")
                except Exception:
                    context_parts.append("  - Tools: unavailable")
                context_parts.append("")

            return "\n".join(context_parts)

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
    # Step 1: REQUEST INTAKE
    # ------------------------------------------------------------------

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
    ) -> Tuple[str, List[str]]:
        """Use LLM to decompose intent into sub-tasks; create TaskNodes."""
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

        # Parse sub-tasks
        sub_tasks: List[str] = []
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                sub_tasks = [str(t) for t in parsed if t]
        except (json.JSONDecodeError, ValueError):
            # Fall back to heuristic extraction
            sub_tasks = self._graph_mgr._extract_sub_tasks(raw)

        if not sub_tasks:
            sub_tasks = [message]  # single root task

        # Create root node
        root_node_id = await self._graph_mgr.add_root_node(
            graph_id=graph_id,
            description=message,
            trace_id=trace_id,
        )

        # Create sub-task nodes
        for task_desc in sub_tasks:
            await self._graph_mgr.add_node(
                graph_id=graph_id,
                parent_id=root_node_id,
                description=task_desc,
                node_type=NodeType.SUBTASK,
                depth=1,
                iteration=0,
                trace_id=trace_id,
            )

        await self._neo4j.update_graph_status(
            graph_id, "EXECUTING", iteration=0, trace_id=trace_id
        )

        logger.info(
            "Graph construction complete",
            layer="service",
            graph_id=graph_id,
            sub_tasks=len(sub_tasks),
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
    ) -> Dict[str, NegotiationResult]:
        """Run capability negotiation for each subtask description."""
        results: Dict[str, NegotiationResult] = {}

        # Get graph nodes to map descriptions to node IDs
        graph_nodes = await self._graph_mgr.get_graph_nodes(graph_id, trace_id=trace_id)
        subtask_nodes = [n for n in graph_nodes if n.get("node_type") == "SUBTASK"]

        for i, desc in enumerate(node_descriptions):
            # Find corresponding node_id
            node_id = ""
            if i < len(subtask_nodes):
                node_id = subtask_nodes[i].get("node_id", "")

            bid_request = BidRequest(
                task_id=node_id,
                task_description=desc,
                task_type="general",
                graph_id=graph_id,
                trace_id=trace_id,
            )

            try:
                neg_result = await self._negotiation.negotiate(
                    bid_request=bid_request,
                    team_agents=team_agents,
                    trace_id=trace_id,
                )
                results[desc] = neg_result

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
            except Exception as exc:
                logger.warning(
                    "Negotiation failed for subtask; using fallback assignment",
                    layer="service",
                    description=desc[:80],
                    error=str(exc),
                    trace_id=trace_id,
                )

        return results

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
        # Filter to SUBTASK nodes only (skip root)
        subtask_nodes = [n for n in graph_nodes if n.get("node_type") == "SUBTASK"]

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
        agent_id = int(agent.agent_id) if agent.agent_id.isdigit() else 0
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
        agent_id = int(agent.agent_id) if (agent and agent.agent_id.isdigit()) else 0
        fallback_index = 0

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

                llm_response, tool_calls_made = await self._execute_agent_with_tools(
                    agent=agent,
                    agent_id=agent_uuid or str(agent_id),
                    system_prompt=base_prompt,
                    task_description=description,
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

                # Step 4e: Band check
                if score >= band_low or recommendation == "proceed":
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
                        trace_id=trace_id,
                    )
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
                    await self._graph_mgr.mark_node_success(node_id, score, latency_ms, trace_id=trace_id)
                    return {
                        "node_id": node_id,
                        "description": description,
                        "llm_response": llm_response,
                        "score": score,
                        "status": "AUTO_CORRECTED",
                        "agent_id": str(agent_id),
                        "agent_name": agent.name if agent else "default",
                        "tools_used": tool_calls_made,
                    }

                # ESCALATE_TO_ORCHESTRATOR -> try fallback agent
                if fallback_index < len(fallbacks):
                    failed_agent_name = agent.name if agent else "unknown"
                    agent = fallbacks[fallback_index]
                    agent_uuid = agent.agent_id if agent else ""
                    agent_id = int(agent.agent_id) if (agent and agent.agent_id.isdigit()) else 0
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
                    agent_id = int(agent.agent_id) if (agent and agent.agent_id.isdigit()) else 0
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
    ) -> None:
        """Persist session memories and publish scoring feedback."""
        # Async memory write via Redis stream
        try:
            await self._redis.publish_memory_write(
                agent_id=agent_id,
                tier="episodic",
                content=final_response[:2000],
                task_id=graph_id,
                importance=0.7,
                trace_id=trace_id,
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
