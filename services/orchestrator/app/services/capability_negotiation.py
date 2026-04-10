"""Capability negotiation service.

Broadcasts bid requests to all team agents in parallel, ranks bids,
and assigns the winner + fallback chain to the Neo4j graph.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from app.adapters.agent_mgmt_adapter import AgentMgmtAdapter
from app.adapters.llm_adapter import LLMAdapter
from app.adapters.memory_adapter import MemoryAdapter
from app.adapters.neo4j_adapter import Neo4jAdapter
from app.config import settings
from app.models.bid import BidRequest, BidResponse, NegotiationResult
from app.services.agent_selector import Agent
from app.services.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError
from app.utils.logger import logger


class CapabilityNegotiationService:
    """Broadcasts bid requests, ranks responses, assigns to graph."""

    def __init__(
        self,
        neo4j: Neo4jAdapter,
        llm: LLMAdapter,
        memory: MemoryAdapter,
        agent_mgmt: AgentMgmtAdapter,
        cb_memory: Optional[CircuitBreaker] = None,
        cb_agent_mgmt: Optional[CircuitBreaker] = None,
    ) -> None:
        self._neo4j = neo4j
        self._llm = llm
        self._memory = memory
        self._agent_mgmt = agent_mgmt
        self._cb_memory = cb_memory or CircuitBreaker("memory")
        self._cb_agent_mgmt = cb_agent_mgmt or CircuitBreaker("agent_mgmt")

    # ------------------------------------------------------------------
    # Public: negotiate for a single task
    # ------------------------------------------------------------------

    async def negotiate(
        self,
        bid_request: BidRequest,
        team_agents: List[Agent],
        trace_id: str = "",
    ) -> NegotiationResult:
        """Run full negotiation: broadcast -> rank -> assign."""
        start = time.monotonic()
        trace_id = trace_id or bid_request.trace_id

        logger.info(
            "Capability negotiation started",
            layer="service",
            task_id=bid_request.task_id,
            task_description=bid_request.task_description[:80],
            agent_count=len(team_agents),
            trace_id=trace_id,
        )

        # 1. Broadcast bid requests to all agents in parallel
        all_bids = await self.broadcast_bid_request(
            bid_request=bid_request,
            team_agents=team_agents,
            trace_id=trace_id,
        )

        # 2. Rank eligible bids
        ranked = self.rank_bids(all_bids)

        # 3. Pick winner + fallback chain
        winner = ranked[0] if ranked else None
        fallback_chain = ranked[1:] if len(ranked) > 1 else []

        elapsed_ms = int((time.monotonic() - start) * 1000)

        # 4. Write assignment to Neo4j
        if winner:
            await self.assign_winner_to_graph(
                task_id=bid_request.task_id,
                graph_id=bid_request.graph_id,
                winner=winner,
                fallback_chain=fallback_chain,
                trace_id=trace_id,
            )

        logger.info(
            "Capability negotiation completed",
            layer="service",
            task_id=bid_request.task_id,
            winner_agent=winner.agent_id if winner else None,
            winner_confidence=winner.confidence if winner else 0.0,
            fallback_count=len(fallback_chain),
            total_bids=len(all_bids),
            eligible_bids=len(ranked),
            negotiation_time_ms=elapsed_ms,
            trace_id=trace_id,
        )

        return NegotiationResult(
            task_id=bid_request.task_id,
            task_description=bid_request.task_description,
            winner=winner,
            fallback_chain=fallback_chain,
            all_bids=all_bids,
            negotiation_time_ms=elapsed_ms,
            trace_id=trace_id,
        )

    # ------------------------------------------------------------------
    # Broadcast bid requests to all agents
    # ------------------------------------------------------------------

    async def broadcast_bid_request(
        self,
        bid_request: BidRequest,
        team_agents: List[Agent],
        trace_id: str = "",
    ) -> List[BidResponse]:
        """Send bid requests to all team agents in parallel with timeout."""
        # Filter out orchestrator-role agents (they don't execute tasks)
        candidates = [a for a in team_agents if a.role != "orchestrator"]
        if not candidates:
            candidates = team_agents  # fallback: all agents are candidates

        tasks = [
            asyncio.wait_for(
                self._request_agent_bid(
                    agent=agent,
                    bid_request=bid_request,
                    trace_id=trace_id,
                ),
                timeout=settings.bid_timeout_sec,
            )
            for agent in candidates
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        bids: List[BidResponse] = []
        for i, result in enumerate(results):
            agent = candidates[i]
            if isinstance(result, asyncio.TimeoutError):
                logger.warning(
                    "Bid request timed out",
                    layer="service",
                    agent_id=agent.agent_id,
                    agent_name=agent.name,
                    trace_id=trace_id,
                )
                bids.append(BidResponse(
                    agent_id=agent.agent_id,
                    agent_name=agent.name,
                    confidence=0.0,
                    eligible=False,
                    error=f"Bid timed out after {settings.bid_timeout_sec}s",
                    foundation_model=agent.foundation_model,
                ))
            elif isinstance(result, Exception):
                logger.warning(
                    "Bid request failed",
                    layer="service",
                    agent_id=agent.agent_id,
                    agent_name=agent.name,
                    error=str(result),
                    trace_id=trace_id,
                )
                bids.append(BidResponse(
                    agent_id=agent.agent_id,
                    agent_name=agent.name,
                    confidence=0.0,
                    eligible=False,
                    error=str(result),
                    foundation_model=agent.foundation_model,
                ))
            else:
                bids.append(result)

        return bids

    # ------------------------------------------------------------------
    # Request a single agent's bid
    # ------------------------------------------------------------------

    async def _request_agent_bid(
        self,
        agent: Agent,
        bid_request: BidRequest,
        trace_id: str = "",
    ) -> BidResponse:
        """For a single agent: assemble memory, check tools, call LLM for self-assessment."""
        agent_id = int(agent.agent_id) if agent.agent_id.isdigit() else 0

        # 1. Fetch agent tools from agent-mgmt
        tools: List[Dict[str, Any]] = []
        try:
            tools = await self._cb_agent_mgmt.call(
                self._agent_mgmt.get_agent_tools,
                agent_id=agent.agent_id,
                trace_id=trace_id,
            )
        except CircuitBreakerOpenError:
            logger.warning(
                "Agent-mgmt CB open; bidding without tool info",
                layer="service",
                agent_id=agent.agent_id,
                trace_id=trace_id,
            )
        except Exception as exc:
            logger.warning(
                "Failed to fetch agent tools for bid",
                layer="service",
                agent_id=agent.agent_id,
                error=str(exc),
                trace_id=trace_id,
            )

        tool_names = [t.get("name", "") for t in tools]
        tool_ids = [str(t.get("id", t.get("tool_id", ""))) for t in tools]
        tool_descriptions = []
        for t in tools:
            desc = f"- {t.get('name', 'unknown')} ({t.get('tool_type', 'unknown')}): {t.get('description', '')}"
            tool_descriptions.append(desc)
        tools_text = "\n".join(tool_descriptions) if tool_descriptions else "No tools available."

        # 2. Assemble memory context (best-effort)
        memory_relevance = 0.0
        memory_context = ""
        try:
            mem_data = await self._cb_memory.call(
                self._memory.assemble_prompt,
                agent_id=agent_id,
                context={
                    "task_type": bid_request.task_type,
                    "domain": "",
                    "recent_messages": [bid_request.task_description],
                },
                trace_id=trace_id,
            )
            memory_context = mem_data.get("system_prompt", "")
            sources = mem_data.get("sources", {})
            total_hits = sum(sources.get(k, 0) for k in sources)
            memory_relevance = min(1.0, total_hits / 10.0) if total_hits > 0 else 0.0
        except CircuitBreakerOpenError:
            pass
        except Exception:
            pass

        # 3. Detect provider from agent's foundation model
        from app.adapters.llm_adapter import _detect_provider
        model = agent.foundation_model or settings.llm_model
        provider = _detect_provider(model)

        # 4. Call LLM for self-assessment bid
        bid_prompt = (
            "You are an AI agent performing a capability self-assessment. "
            "Given the following task and your available tools, assess how well you can handle this task.\n\n"
            f"TASK: {bid_request.task_description}\n\n"
            f"YOUR NAME: {agent.name}\n"
            f"YOUR TOOLS:\n{tools_text}\n\n"
        )
        if memory_context:
            bid_prompt += f"YOUR RELEVANT MEMORY/CONTEXT:\n{memory_context[:500]}\n\n"

        bid_prompt += (
            "Respond with ONLY a JSON object (no other text):\n"
            "{\n"
            '  "confidence": <float 0.0-1.0, how confident you are you can handle this task>,\n'
            '  "reasoning": "<brief explanation of why you can or cannot handle this task>",\n'
            '  "eligible": <true if you can attempt the task, false if completely unqualified>\n'
            "}\n\n"
            "IMPORTANT: If you have database tools and the task involves data/SQL/database queries, "
            "bid HIGH confidence. If you have API tools and the task involves web/API calls, bid HIGH. "
            "If you have no relevant tools for the task type, bid lower but still eligible if you have general knowledge."
        )

        try:
            raw_response = await self._llm.complete(
                messages=[{"role": "user", "content": bid_prompt}],
                model=model,
                trace_id=trace_id,
                provider=provider,
            )

            # Parse LLM JSON response with fallback
            bid_data = self._parse_bid_response(raw_response)
            confidence = float(bid_data.get("confidence", 0.5))
            reasoning = str(bid_data.get("reasoning", ""))
            eligible = bool(bid_data.get("eligible", True))

            # Clamp confidence to [0.0, 1.0]
            confidence = max(0.0, min(1.0, confidence))

            # Boost confidence if agent has relevant tools
            if tools and confidence > 0.0:
                confidence = min(1.0, confidence + 0.05)

        except Exception as exc:
            logger.warning(
                "LLM bid assessment failed; using heuristic",
                layer="service",
                agent_id=agent.agent_id,
                error=str(exc),
                trace_id=trace_id,
            )
            # Heuristic fallback: use agent's success_rate * accuracy_rate
            confidence = agent.success_rate * agent.accuracy_rate
            reasoning = f"Heuristic bid (LLM failed): success={agent.success_rate}, accuracy={agent.accuracy_rate}"
            eligible = True

        return BidResponse(
            agent_id=agent.agent_id,
            agent_name=agent.name,
            confidence=confidence,
            memory_relevance=memory_relevance,
            estimated_latency_ms=0,
            tools_available=tool_names,
            tool_ids=tool_ids,
            reasoning=reasoning,
            eligible=eligible,
            foundation_model=model,
            provider=provider,
        )

    # ------------------------------------------------------------------
    # Rank bids
    # ------------------------------------------------------------------

    def rank_bids(self, bids: List[BidResponse]) -> List[BidResponse]:
        """Rank eligible bids by weighted score: confidence, memory relevance, latency."""
        eligible = [b for b in bids if b.eligible and b.error is None]
        if not eligible:
            # If none are eligible, try all non-error bids
            eligible = [b for b in bids if b.error is None]

        w_conf = settings.bid_confidence_weight
        w_mem = settings.bid_memory_weight
        w_lat = settings.bid_latency_weight

        def score(bid: BidResponse) -> float:
            # Latency: lower is better, normalize to 0-1 (inverse)
            lat_score = 1.0 / (1.0 + bid.estimated_latency_ms / 1000.0)
            return (
                w_conf * bid.confidence
                + w_mem * bid.memory_relevance
                + w_lat * lat_score
            )

        eligible.sort(key=score, reverse=True)
        return eligible

    # ------------------------------------------------------------------
    # Write assignment to Neo4j
    # ------------------------------------------------------------------

    async def assign_winner_to_graph(
        self,
        task_id: str,
        graph_id: str,
        winner: BidResponse,
        fallback_chain: List[BidResponse],
        trace_id: str = "",
    ) -> None:
        """Write the negotiation result to the TaskNode and create ExecutionEvents."""
        # Update TaskNode with assigned agent
        fallback_ids = [b.agent_id for b in fallback_chain]
        try:
            cypher = """
            MATCH (n:TaskNode {node_id: $task_id})
            SET n.assigned_agent_id = $agent_id,
                n.assigned_agent_name = $agent_name,
                n.fallback_agent_ids = $fallback_ids,
                n.bid_confidence = $confidence,
                n.updated_at = datetime()
            """
            await self._neo4j.run_query(
                cypher,
                {
                    "task_id": task_id,
                    "agent_id": winner.agent_id,
                    "agent_name": winner.agent_name,
                    "fallback_ids": fallback_ids,
                    "confidence": winner.confidence,
                },
                trace_id=trace_id,
            )
        except Exception as exc:
            logger.error(
                "Failed to write bid assignment to Neo4j",
                layer="service",
                task_id=task_id,
                error=str(exc),
                trace_id=trace_id,
            )

        # Persist ALL bids as ExecutionEvents (BID_SUBMITTED for each, BID_WON for winner)
        for bid in [winner] + fallback_chain:
            is_winner = bid.agent_id == winner.agent_id
            try:
                event_id = str(uuid.uuid4())
                await self._neo4j.create_execution_event(
                    event_id=event_id,
                    event_type="BID_WON" if is_winner else "BID_SUBMITTED",
                    agent_id=bid.agent_id,
                    node_id=task_id,
                    score=bid.confidence,
                    action_taken=json.dumps({
                        "agent_name": bid.agent_name,
                        "confidence": bid.confidence,
                        "memory_relevance": bid.memory_relevance,
                        "estimated_latency_ms": bid.estimated_latency_ms,
                        "tools_available": bid.tools_available,
                        "reasoning": bid.reasoning,
                        "eligible": bid.eligible,
                        "is_winner": is_winner,
                    }),
                    correlation_id=trace_id,
                    trace_id=trace_id,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to create bid ExecutionEvent",
                    layer="service",
                    agent_id=bid.agent_id,
                    event_type="BID_WON" if is_winner else "BID_SUBMITTED",
                    error=str(exc),
                    trace_id=trace_id,
                )

    # ------------------------------------------------------------------
    # Post-execution accuracy update
    # ------------------------------------------------------------------

    async def update_bid_accuracy(
        self,
        task_id: str,
        agent_id: str,
        actual_score: float,
        bid_confidence: float,
        trace_id: str = "",
    ) -> None:
        """After execution, record how accurate the bid was vs actual performance."""
        accuracy_delta = abs(bid_confidence - actual_score)
        try:
            event_id = str(uuid.uuid4())
            await self._neo4j.create_execution_event(
                event_id=event_id,
                event_type="BID_ACCURACY",
                agent_id=agent_id,
                node_id=task_id,
                score=actual_score,
                action_taken=f"Bid confidence={bid_confidence:.2f}, actual={actual_score:.2f}, delta={accuracy_delta:.2f}",
                correlation_id=trace_id,
                trace_id=trace_id,
            )
        except Exception as exc:
            logger.warning(
                "Failed to record bid accuracy",
                layer="service",
                error=str(exc),
                trace_id=trace_id,
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_bid_response(raw: str) -> Dict[str, Any]:
        """Parse LLM JSON response with fallback for malformed output."""
        # Try direct JSON parse
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            pass

        # Try extracting JSON from markdown code block
        import re
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except (json.JSONDecodeError, ValueError):
                pass

        # Try finding first { ... } block
        match = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except (json.JSONDecodeError, ValueError):
                pass

        # Last resort: return defaults
        return {"confidence": 0.5, "reasoning": raw[:200], "eligible": True}
