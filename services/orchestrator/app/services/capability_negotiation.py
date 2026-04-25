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

        # 1a. Dataset-binding filter (Phase 21).
        # When the TaskNode carries dataset_bindings (Translator stamped them
        # in pipeline._step2), demote bids whose tools cannot reach those
        # physical assets. Bids stay in `all_bids` for audit, but lose
        # eligibility and are excluded from ranking.
        await self._apply_dataset_binding_filter(
            bid_request=bid_request,
            bids=all_bids,
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
        # Also collect tool_uuid (the ``tool_id`` UUID written into Neo4j by
        # toolService.linkToolToDataSource) — agents need this to resolve
        # their physical reach in the catalog graph.
        tool_uuids = [str(t.get("tool_id") or t.get("uuid") or "") for t in tools]
        tool_uuids = [u for u in tool_uuids if u]
        tool_descriptions = []
        for t in tools:
            desc = f"- {t.get('name', 'unknown')} ({t.get('tool_type', 'unknown')}): {t.get('description', '')}"
            tool_descriptions.append(desc)
        tools_text = "\n".join(tool_descriptions) if tool_descriptions else "No tools available."

        # 1b. Bid-time grounding: for any task that carries dataset_bindings,
        # walk Neo4j (Tool→ACCESSES→DataSource→HAS_ASSET→DataAsset→HAS_COLUMN
        # →DataColumn ←MAPS_TO← BusinessAttribute) to find which assets THIS
        # agent's tools can actually read, plus the columns + sample values
        # for each. The data is injected into the bid prompt so the LLM bids
        # with grounded knowledge of the physical schema, not just keyword
        # match. The bid carries ``accessible_assets`` and
        # ``dataset_access_verified`` so downstream ranking can prefer
        # agents whose tools demonstrably reach the required data.
        accessible_metadata: Dict[str, List[Dict[str, Any]]] = {}
        accessible_assets: List[str] = []
        if bid_request.dataset_bindings and tool_uuids:
            try:
                rows = await self._neo4j.run_query(
                    """
                    UNWIND $bindings AS binding
                    MATCH (a:DataAsset {fq_name: binding})
                    OPTIONAL MATCH (ds:DataSource)-[:HAS_ASSET]->(a)
                    OPTIONAL MATCH (t:Tool)-[:ACCESSES]->(ds)
                      WHERE t.tool_id IN $tool_uuids
                    WITH binding, a, collect(DISTINCT t.tool_id) AS reaching_tools
                    WHERE size(reaching_tools) > 0
                    OPTIONAL MATCH (a)-[:HAS_COLUMN]->(col:DataColumn)
                    OPTIONAL MATCH (ba:BusinessAttribute)-[map:MAPS_TO]->(col)
                      WHERE map.effective_until IS NULL
                    RETURN binding AS asset_fq_name,
                           collect(DISTINCT {
                             column: col.name,
                             data_type: col.data_type,
                             sample_values: col.sample_values,
                             business_attribute: ba.name,
                             business_entity: ba.entity,
                             business_domain: ba.domain,
                             map_confidence: map.confidence
                           }) AS columns,
                           reaching_tools[0] AS bound_tool_id
                    """,
                    {
                        "bindings": list(bid_request.dataset_bindings),
                        "tool_uuids": tool_uuids,
                    },
                    trace_id=trace_id,
                )
                for row in rows or []:
                    asset = row.get("asset_fq_name")
                    cols = [c for c in (row.get("columns") or []) if c and c.get("column")]
                    if asset and cols:
                        accessible_metadata[asset] = cols
                        accessible_assets.append(asset)
            except Exception as exc:
                logger.warning(
                    "Bid-time metadata lookup failed (non-fatal)",
                    layer="service",
                    agent_id=agent.agent_id,
                    error=str(exc),
                    trace_id=trace_id,
                )

        # Render the accessible-data summary for the bid prompt. We cap at a
        # handful of columns per asset and at most 3 sample values per column
        # so prompt size stays bounded — the LLM doesn't need every row, just
        # enough to recognize the schema.
        data_text_lines: List[str] = []
        if accessible_metadata:
            for asset, cols in list(accessible_metadata.items())[:6]:
                data_text_lines.append(f"\nASSET {asset}:")
                for c in cols[:12]:
                    name = c.get("column")
                    dtype = c.get("data_type") or "?"
                    ba = c.get("business_attribute")
                    samples = c.get("sample_values") or []
                    if isinstance(samples, list):
                        samples = [str(s)[:40] for s in samples[:3]]
                        samples_text = f"  samples: {samples}" if samples else ""
                    else:
                        samples_text = ""
                    line = f"  - {name} ({dtype})"
                    if ba:
                        line += f"  ↔ {c.get('business_domain') or '?'}.{c.get('business_entity') or '?'}.{ba}"
                    line += samples_text
                    data_text_lines.append(line)
        data_text = "\n".join(data_text_lines)

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

        if bid_request.dataset_bindings:
            if data_text:
                bid_prompt += (
                    "REQUIRED PHYSICAL ASSETS (the orchestrator's translator already "
                    "matched the question to these — use this concrete schema and "
                    "sample-value evidence to ground your bid):\n"
                    f"{data_text}\n\n"
                )
            else:
                bid_prompt += (
                    "REQUIRED PHYSICAL ASSETS:\n"
                    f"  {bid_request.dataset_bindings}\n"
                    "WARNING: none of your tools demonstrably reach these assets in "
                    "the catalog graph. Bid LOW confidence (<= 0.3) unless you "
                    "have a strong reason to believe you can answer without them.\n\n"
                )

        if memory_context:
            bid_prompt += f"YOUR RELEVANT MEMORY/CONTEXT:\n{memory_context[:500]}\n\n"

        bid_prompt += (
            "Respond with ONLY a JSON object (no other text):\n"
            "{\n"
            '  "confidence": <float 0.0-1.0, how confident you are you can handle this task>,\n'
            '  "reasoning": "<brief explanation grounded in the schema/samples above>",\n'
            '  "eligible": <true if you can attempt the task, false if completely unqualified>\n'
            "}\n\n"
            "IMPORTANT: When REQUIRED PHYSICAL ASSETS is present and your tools "
            "DEMONSTRABLY reach them with matching columns (per the schema "
            "summary), bid HIGH (≥0.8). When the assets are required but your "
            "tools cannot reach them, bid LOW (≤0.3) — keyword/tool-type match "
            "without dataset access is not sufficient. For non-data tasks, "
            "score on tool-task fit as before."
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

        # If the task carried dataset_bindings, stamp the bid with the
        # outcome of the bid-time grounding check. This is what the post-
        # filter ``_apply_dataset_binding_filter`` would have computed
        # afterwards, but doing it here makes the bid both grounded and
        # self-verified — the LLM saw the schema/samples; downstream ranking
        # already knows whether the agent can reach the data.
        if bid_request.dataset_bindings:
            verified = bool(accessible_assets)
            bid_response = BidResponse(
                agent_id=agent.agent_id,
                agent_name=agent.name,
                confidence=confidence,
                memory_relevance=memory_relevance,
                estimated_latency_ms=0,
                tools_available=tool_names,
                tool_ids=tool_ids,
                reasoning=reasoning,
                eligible=eligible and (verified or not bid_request.dataset_bindings),
                foundation_model=model,
                provider=provider,
                dataset_access_verified=verified,
                accessible_assets=accessible_assets,
            )
            if not verified and bid_request.dataset_bindings:
                bid_response.error = (
                    "dataset_access_unverified: no bound tool reaches required assets"
                )
            return bid_response

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
    # Dataset-binding filter
    # ------------------------------------------------------------------

    async def _apply_dataset_binding_filter(
        self,
        bid_request: BidRequest,
        bids: List[BidResponse],
        trace_id: str = "",
    ) -> None:
        """Demote bids whose tools cannot reach the required DataAssets.

        When ``bid_request.dataset_bindings`` is empty the filter is a no-op —
        non-data tasks (chat, summaries, system queries) bid as before.

        For each binding, we ask Neo4j which tools ``ACCESSES`` a DataSource
        that ``HAS_ASSET`` that DataAsset. A bid is **dataset-access verified**
        iff its ``tool_ids`` intersect the union of those tool sets.

        Failure mode: if the Neo4j lookup fails we log and leave bids
        untouched (fail-open) — better to over-allow than to drop everyone
        when the catalog is briefly unreachable.
        """
        bindings = [b for b in (bid_request.dataset_bindings or []) if b]
        if not bindings:
            return

        # Per-asset tool reachability map.
        try:
            rows = await self._neo4j.run_query(
                """
                UNWIND $bindings AS binding
                MATCH (a:DataAsset {fq_name: binding})
                OPTIONAL MATCH (ds:DataSource)-[:HAS_ASSET]->(a)
                OPTIONAL MATCH (t:Tool)-[:ACCESSES]->(ds)
                RETURN binding AS asset_fq_name,
                       collect(DISTINCT t.tool_id) AS tool_ids
                """,
                {"bindings": bindings},
                trace_id=trace_id,
            )
        except Exception as exc:
            logger.warning(
                "Dataset-binding filter Neo4j lookup failed — fail-open",
                layer="service",
                trace_id=trace_id,
                error=str(exc),
            )
            return

        asset_to_tools: Dict[str, set] = {}
        for row in rows or []:
            asset = row.get("asset_fq_name")
            tids = {str(t) for t in (row.get("tool_ids") or []) if t}
            if asset:
                asset_to_tools[asset] = tids

        all_eligible_tools: set = set()
        for tids in asset_to_tools.values():
            all_eligible_tools |= tids

        if not all_eligible_tools:
            # No tool in the catalog can reach any of the required assets.
            # Mark every bid as unverified, but DO NOT zero eligibility —
            # ranking will still pick a winner so the pipeline can run with
            # the fallback default agent.
            logger.warning(
                "No tools reach the required assets — keeping bids but flagging unverified",
                layer="service",
                trace_id=trace_id,
                bindings=bindings,
            )
            for bid in bids:
                bid.dataset_access_verified = False
                bid.accessible_assets = []
            return

        verified_count = 0
        demoted: List[Dict[str, Any]] = []

        for bid in bids:
            bid_tool_ids = {str(t) for t in (bid.tool_ids or []) if t}

            # Compute which of the required assets this bid can reach.
            reachable: List[str] = [
                asset for asset, tids in asset_to_tools.items()
                if bid_tool_ids & tids
            ]
            bid.accessible_assets = reachable
            bid.dataset_access_verified = bool(reachable)

            if not reachable:
                # The agent claimed capability but has no tool reaching the
                # data — drop it from ranking. Audit-visible: the bid stays
                # in ``all_bids`` with eligible=False and a reason in
                # ``error`` so governance traces can show why.
                bid.eligible = False
                bid.error = (
                    bid.error
                    or "dataset_access_unverified: no bound tool reaches required assets"
                )
                demoted.append({
                    "agent_id": bid.agent_id,
                    "agent_name": bid.agent_name,
                    "tool_ids": list(bid_tool_ids),
                })
            else:
                verified_count += 1

        logger.info(
            "Dataset-binding filter applied",
            layer="service",
            trace_id=trace_id,
            bindings=bindings,
            total_bids=len(bids),
            verified=verified_count,
            demoted=len(demoted),
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
