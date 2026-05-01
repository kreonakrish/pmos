"""Capability negotiation service.

Broadcasts bid requests to all team agents in parallel, ranks bids,
and assigns the winner + fallback chain to the Neo4j graph.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from app.adapters.agent_mgmt_adapter import AgentMgmtAdapter
from app.adapters.llm_adapter import LLMAdapter
from app.adapters.memory_adapter import MemoryAdapter
from app.adapters.neo4j_adapter import Neo4jAdapter
from app.config import settings
from app.models.bid import (
    BidCoverage,
    BidPlanStep,
    BidRequest,
    BidResponse,
    NegotiationResult,
)
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

        # 3b. Complementary-cover (Phase 4). When the top winner can't
        # cover the question alone, pick a set of bids whose answerable
        # parts span the question. Pipeline-side splicing reads
        # ``complementary_winners`` to spawn sibling subtask nodes — one
        # per chosen agent.
        complementary_winners, uncovered_parts = self._compute_set_cover(
            ranked_bids=ranked,
            top_winner=winner,
        )

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
            complementary_winners=complementary_winners,
            uncovered_parts=uncovered_parts,
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
        accessible_metadata: Dict[str, Dict[str, Any]] = {}
        accessible_assets: List[str] = []
        asset_relationships: List[Dict[str, Any]] = []
        if bid_request.dataset_bindings and tool_uuids:
            try:
                rows = await self._neo4j.run_query(
                    """
                    UNWIND $bindings AS binding
                    MATCH (a:DataAsset {fq_name: binding})
                    OPTIONAL MATCH (ds:DataSource)-[:HAS_ASSET]->(a)
                    OPTIONAL MATCH (t:Tool)-[:ACCESSES]->(ds)
                      WHERE t.tool_id IN $tool_uuids
                    WITH binding, a, ds, collect(DISTINCT t.tool_id) AS reaching_tools
                    WHERE size(reaching_tools) > 0
                    OPTIONAL MATCH (a)-[:HAS_COLUMN]->(col:DataColumn)
                    OPTIONAL MATCH (ba:BusinessAttribute)-[map:MAPS_TO]->(col)
                      WHERE map.effective_until IS NULL
                    RETURN binding AS asset_fq_name,
                           a.asset_type AS asset_type,
                           a.comment    AS asset_comment,
                           a.row_count  AS row_count,
                           ds.source_type AS source_type,
                           collect(DISTINCT {
                             column: col.name,
                             data_type: col.data_type,
                             sample_values: col.sample_values,
                             is_pk: col.is_pk,
                             is_fk: col.is_fk,
                             fk_references: col.fk_references,
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
                        accessible_metadata[asset] = {
                            "columns": cols,
                            "asset_type": row.get("asset_type") or "TABLE",
                            "asset_comment": row.get("asset_comment") or "",
                            "source_type": row.get("source_type") or "",
                            "row_count": row.get("row_count"),
                        }
                        accessible_assets.append(asset)
            except Exception as exc:
                logger.warning(
                    "Bid-time metadata lookup failed (non-fatal)",
                    layer="service",
                    agent_id=agent.agent_id,
                    error=str(exc),
                    trace_id=trace_id,
                )

            # Pull RELATED_TO edges between any pair of accessible assets so a
            # multi-tool agent can see the join paths (loan_id ↔ loan_id) in
            # its bid prompt and commit to a cross-schema plan. Limited to
            # relationships among assets THIS agent can reach — irrelevant
            # cross-DB joins it cannot run are noise.
            if accessible_assets:
                try:
                    rel_rows = await self._neo4j.run_query(
                        """
                        UNWIND $assets AS aname
                        MATCH (a:DataAsset {fq_name: aname})
                        OPTIONAL MATCH (a)-[r:RELATED_TO]->(b:DataAsset)
                          WHERE b.fq_name IN $assets
                        WITH aname, r, b
                        WHERE r IS NOT NULL
                        RETURN aname AS from_asset,
                               b.fq_name AS to_asset,
                               r.via AS via
                        """,
                        {"assets": accessible_assets},
                        trace_id=trace_id,
                    )
                    for r in rel_rows or []:
                        if r.get("from_asset") and r.get("to_asset"):
                            asset_relationships.append({
                                "from": r["from_asset"],
                                "to": r["to_asset"],
                                "via": r.get("via") or "",
                            })
                except Exception as exc:
                    logger.warning(
                        "Bid-time relationship lookup failed (non-fatal)",
                        layer="service",
                        agent_id=agent.agent_id,
                        error=str(exc),
                        trace_id=trace_id,
                    )

        # Render the accessible-data summary for the bid prompt. We cap at a
        # handful of columns per asset and at most 3 sample values per column
        # so prompt size stays bounded — the LLM doesn't need every row, just
        # enough to recognize the schema. The header and column-line shape
        # branch on asset_type so Neo4j sources render as
        # `(:Customer {customer_id, segment})` instead of SQL syntax.
        data_text_lines: List[str] = []
        source_types_seen: Set[str] = set()
        if accessible_metadata:
            for asset, meta in list(accessible_metadata.items())[:8]:
                cols = meta.get("columns") or []
                asset_type = meta.get("asset_type") or "TABLE"
                source_type = (meta.get("source_type") or "").upper()
                comment = meta.get("asset_comment") or ""
                row_count = meta.get("row_count")
                if source_type:
                    source_types_seen.add(source_type)

                row_count_text = (
                    f"  [~{int(row_count):,} rows]"
                    if isinstance(row_count, (int, float)) and row_count
                    else ""
                )

                if asset_type == "NODE_LABEL":
                    bare = asset.split(".")[-1]
                    data_text_lines.append(f"\nNODE LABEL (:{bare}):{row_count_text}")
                elif asset_type == "RELATIONSHIP":
                    data_text_lines.append(
                        f"\nRELATIONSHIP {comment or asset}:{row_count_text}"
                    )
                else:
                    data_text_lines.append(f"\nASSET {asset}:{row_count_text}")

                for c in cols[:30]:
                    name = c.get("column")
                    dtype = c.get("data_type") or "?"
                    ba = c.get("business_attribute")
                    samples = c.get("sample_values") or []
                    flags: List[str] = []
                    if c.get("is_pk"):
                        flags.append("PK")
                    if c.get("is_fk"):
                        ref = c.get("fk_references") or ""
                        flags.append(f"FK→{ref}" if ref else "FK")
                    flag_text = f"  [{','.join(flags)}]" if flags else ""
                    if isinstance(samples, list):
                        samples = [str(s)[:40] for s in samples[:3]]
                        samples_text = f"  samples: {samples}" if samples else ""
                    else:
                        samples_text = ""
                    line = f"  - {name} ({dtype}){flag_text}"
                    if ba:
                        line += f"  ↔ {c.get('business_domain') or '?'}.{c.get('business_entity') or '?'}.{ba}"
                    line += samples_text
                    data_text_lines.append(line)

            # Cross-asset relationships — surface join paths so a multi-tool
            # agent can commit to a join in its bid plan.
            if asset_relationships:
                data_text_lines.append("\nKNOWN JOIN PATHS:")
                for rel in asset_relationships[:20]:
                    via = rel.get("via") or "?"
                    data_text_lines.append(
                        f"  - {rel.get('from')}  ⟶  {rel.get('to')}   via {via}"
                    )
        data_text = "\n".join(data_text_lines)
        # If any required asset is graph-shaped, hint to the agent which query
        # language to use. Mixed (SQL + Cypher) tasks are rare but possible —
        # we surface the set so the agent picks per-asset.
        query_lang_hint = ""
        if "NEO4J" in source_types_seen and len(source_types_seen) == 1:
            query_lang_hint = "Use Cypher to query the graph assets shown."
        elif "NEO4J" in source_types_seen:
            query_lang_hint = (
                "Required assets span multiple source types — use Cypher for "
                "NODE LABEL / RELATIONSHIP assets and SQL for TABLE assets."
            )

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
                    f"{data_text}\n"
                )
                if query_lang_hint:
                    bid_prompt += f"{query_lang_hint}\n"
                bid_prompt += "\n"
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
            "Respond with ONLY a JSON object (no other text). Your bid is a "
            "CONTRACT — `coverage.answerable` is what you commit to deliver if "
            "you win. `plan` is the SQL/Cypher/Python sketch you intend to run.\n"
            "{\n"
            '  "confidence": <float 0.0-1.0>,\n'
            '  "eligible": <true|false>,\n'
            '  "reasoning": "<why this fit, grounded in the schema/samples above>",\n'
            '  "coverage": {\n'
            '    "answerable":     ["<question part you can fully answer>", ...],\n'
            '    "not_answerable": ["<question part you cannot answer>", ...],\n'
            '    "reason_missing": "<why those parts are out of reach for your tools>"\n'
            '  },\n'
            '  "plan": [\n'
            '    {"tool": "<tool name>", "kind": "sql|cypher|api|python",\n'
            '     "sketch": "<SQL/Cypher/code sketch grounded in real columns>",\n'
            '     "expected_columns": ["<col1>", "<col2>"],\n'
            '     "purpose": "<which answerable part this step addresses>"}\n'
            "  ]\n"
            "}\n\n"
            "RULES:\n"
            "- Decompose the user task into discrete *parts* (e.g. count, dates, "
            "tenure, status). Put each part in EXACTLY ONE of `answerable` / "
            "`not_answerable`.\n"
            "- `plan` must reference real tool names from YOUR TOOLS above and "
            "real column/asset names from REQUIRED PHYSICAL ASSETS above. "
            "Don't invent columns that aren't in the schema summary.\n"
            "- If you have multiple tools, commit to a SEPARATE plan step for "
            "each tool you intend to call. Multi-tool agents are expected to "
            "stitch via `expected_columns` join keys.\n"
            "- When REQUIRED PHYSICAL ASSETS is present and your tools "
            "DEMONSTRABLY reach them, bid HIGH (≥0.8). When you can't reach "
            "them, bid LOW (≤0.3) and put the parts in `not_answerable`.\n"
            "- For non-data tasks (chat/summary/system), `coverage.answerable` "
            "should still list what you'll do; `plan` may be empty or contain "
            "a single API/Python step."
        )

        coverage: Optional[BidCoverage] = None
        plan_steps: List[BidPlanStep] = []
        plan_format = "structured"

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

            # Extract structured coverage + plan. When the LLM returned the
            # legacy {confidence, reasoning, eligible} shape, both fields are
            # absent — we mark the bid plan_format="legacy" so ranking can
            # fall back to confidence-only scoring.
            coverage_data = bid_data.get("coverage")
            plan_data = bid_data.get("plan")
            has_structured = isinstance(coverage_data, dict) or isinstance(plan_data, list)
            if has_structured:
                coverage = self._coerce_coverage(coverage_data)
                plan_steps = self._coerce_plan(plan_data)
                # If neither survived coercion, treat as legacy.
                if coverage is None and not plan_steps:
                    plan_format = "legacy"
            else:
                plan_format = "legacy"

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
            plan_format = "legacy"

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
                coverage=coverage,
                plan=plan_steps,
                plan_format=plan_format,
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
            coverage=coverage,
            plan=plan_steps,
            plan_format=plan_format,
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
        """Rank eligible bids by weighted score.

        Score = w_cov × coverage_ratio
              + w_conf × confidence
              + w_mem × memory_relevance
              + w_lat × latency_score

        When a bid carries no structured coverage (``plan_format='legacy'``
        or absent ``BidCoverage``) the coverage term defaults to 1.0 so
        legacy bids aren't penalised — they fall back to the pre-Phase-22
        score weights once the coverage term is neutralised.
        """
        eligible = [b for b in bids if b.eligible and b.error is None]
        if not eligible:
            # If none are eligible, try all non-error bids
            eligible = [b for b in bids if b.error is None]

        w_conf = settings.bid_confidence_weight
        w_mem = settings.bid_memory_weight
        w_lat = settings.bid_latency_weight
        w_cov = settings.bid_coverage_weight

        def score(bid: BidResponse) -> float:
            # Latency: lower is better, normalize to 0-1 (inverse)
            lat_score = 1.0 / (1.0 + bid.estimated_latency_ms / 1000.0)
            cov_score = (
                bid.coverage.ratio() if bid.coverage is not None else 1.0
            )
            return (
                w_cov * cov_score
                + w_conf * bid.confidence
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
        # Update TaskNode with assigned agent. Plan + coverage are stored as
        # JSON strings on the node so the execution prompt builder can pick
        # them up later (and the UI Decision tab can render them) without
        # another negotiation lookup.
        fallback_ids = [b.agent_id for b in fallback_chain]
        try:
            bid_plan_json = json.dumps(
                [step.model_dump() for step in (winner.plan or [])],
                ensure_ascii=False,
            )
            bid_coverage_json = (
                json.dumps(winner.coverage.model_dump(), ensure_ascii=False)
                if winner.coverage
                else ""
            )
        except Exception:
            bid_plan_json = ""
            bid_coverage_json = ""

        try:
            cypher = """
            MATCH (n:TaskNode {node_id: $task_id})
            SET n.assigned_agent_id = $agent_id,
                n.assigned_agent_name = $agent_name,
                n.fallback_agent_ids = $fallback_ids,
                n.bid_confidence = $confidence,
                n.bid_plan = $bid_plan,
                n.bid_coverage = $bid_coverage,
                n.bid_plan_format = $plan_format,
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
                    "bid_plan": bid_plan_json,
                    "bid_coverage": bid_coverage_json,
                    "plan_format": winner.plan_format,
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
                        "plan_format": bid.plan_format,
                        "coverage": (
                            bid.coverage.model_dump() if bid.coverage else None
                        ),
                        "plan": [s.model_dump() for s in (bid.plan or [])],
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
    def _compute_set_cover(
        ranked_bids: List[BidResponse],
        top_winner: Optional[BidResponse],
    ) -> Tuple[List[BidResponse], List[str]]:
        """Greedy set cover across structured bids.

        Returns ``(chosen, uncovered_parts)``. ``chosen`` is non-empty only
        when the top winner can't cover the question alone — at least 2
        bids are needed to span the declared parts. The first entry is
        always the top winner (so pipeline-side splicing knows which
        sibling slot is the "primary" node).

        When called with no structured bids (everything is legacy / no
        coverage), returns ``([], [])`` and the caller falls back to the
        single-winner path.
        """
        if top_winner is None or top_winner.coverage is None:
            return [], []

        # Union of all parts declared by any structured bid — that's the
        # question's surface area as bidders perceive it.
        all_parts: set[str] = set()
        for b in ranked_bids:
            if b.coverage:
                all_parts.update(b.coverage.answerable)
                all_parts.update(b.coverage.not_answerable)

        if not all_parts:
            return [], []

        # If the top winner already covers everything declared, no need to
        # complement.
        top_answerable = set(top_winner.coverage.answerable)
        if all_parts.issubset(top_answerable):
            return [], []

        # Greedy set cover: at each step, pick the bid that adds the most
        # uncovered parts. Stop when full coverage or no more progress.
        structured = [
            b for b in ranked_bids
            if b.coverage and b.coverage.answerable and b.error is None
        ]
        if not structured:
            return [], []

        chosen: List[BidResponse] = []
        chosen_ids: set[str] = set()
        covered: set[str] = set()

        # Seed with the top winner — pipeline reuses its existing node.
        chosen.append(top_winner)
        chosen_ids.add(top_winner.agent_id)
        covered |= top_answerable

        while covered < all_parts:
            best: Optional[BidResponse] = None
            best_gain = 0
            for b in structured:
                if b.agent_id in chosen_ids:
                    continue
                gain = len(set(b.coverage.answerable) - covered)
                if gain > best_gain:
                    best = b
                    best_gain = gain
            if best is None or best_gain == 0:
                break
            chosen.append(best)
            chosen_ids.add(best.agent_id)
            covered |= set(best.coverage.answerable)

        uncovered = sorted(all_parts - covered)

        # If only the top winner ended up chosen, no complementary mode —
        # callers want None/empty in that case.
        if len(chosen) <= 1:
            return [], uncovered

        return chosen, uncovered

    @staticmethod
    def _coerce_coverage(raw: Any) -> Optional[BidCoverage]:
        """Coerce a possibly-malformed coverage dict into BidCoverage.

        Returns None when the input isn't dict-shaped or yields no parts —
        ranking treats the absence as legacy and falls back accordingly.
        """
        if not isinstance(raw, dict):
            return None
        ans = raw.get("answerable") or []
        notans = raw.get("not_answerable") or []
        if not isinstance(ans, list):
            ans = []
        if not isinstance(notans, list):
            notans = []
        # Defensive: keep strings only, drop None/empty.
        ans = [str(x).strip() for x in ans if x is not None and str(x).strip()]
        notans = [str(x).strip() for x in notans if x is not None and str(x).strip()]
        if not ans and not notans:
            return None
        return BidCoverage(
            answerable=ans[:24],
            not_answerable=notans[:24],
            reason_missing=str(raw.get("reason_missing") or "")[:500],
        )

    @staticmethod
    def _coerce_plan(raw: Any) -> List[BidPlanStep]:
        """Coerce a possibly-malformed plan list into BidPlanStep[]."""
        if not isinstance(raw, list):
            return []
        steps: List[BidPlanStep] = []
        for item in raw[:12]:  # cap to keep storage bounded
            if not isinstance(item, dict):
                continue
            cols = item.get("expected_columns") or []
            if not isinstance(cols, list):
                cols = []
            cols = [str(c).strip() for c in cols if str(c).strip()][:30]
            steps.append(BidPlanStep(
                tool=str(item.get("tool") or "")[:120],
                kind=str(item.get("kind") or "sql").lower()[:20],
                sketch=str(item.get("sketch") or "")[:2000],
                expected_columns=cols,
                purpose=str(item.get("purpose") or "")[:300],
            ))
        return steps

    @staticmethod
    def _parse_bid_response(raw: str) -> Dict[str, Any]:
        """Parse LLM JSON response with fallback for malformed output.

        The new bid shape is nested ({coverage:{...}, plan:[{...}]}), so the
        flat ``\\{[^{}]*\\}`` regex no longer covers it. We brace-balance to
        pull the first complete top-level JSON object.
        """
        # Try direct JSON parse
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            pass

        # Try extracting JSON from markdown code block (greedy across newlines).
        import re
        match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except (json.JSONDecodeError, ValueError):
                pass

        # Brace-balance: find first '{' then read until matching '}', honoring
        # string literals so a brace inside a quoted SQL sketch doesn't fool us.
        start = raw.find("{")
        if start != -1:
            depth = 0
            in_string = False
            escape = False
            for i in range(start, len(raw)):
                ch = raw[i]
                if escape:
                    escape = False
                    continue
                if ch == "\\":
                    escape = True
                    continue
                if ch == '"':
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = raw[start:i + 1]
                        try:
                            return json.loads(candidate)
                        except (json.JSONDecodeError, ValueError):
                            break

        # Last resort: return defaults — caller treats missing coverage/plan
        # as legacy bid shape and skips structured ranking.
        return {"confidence": 0.5, "reasoning": raw[:200], "eligible": True}
