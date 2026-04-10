"""Prompt assembler — builds dynamic system prompts from all 4 memory tiers."""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from app.models.memory import MemoryTier, PromptSourceCounts
from app.services.episodic import EpisodicMemoryService
from app.services.long_term import LongTermMemoryService
from app.services.reasoning import ReasoningMemoryService
from app.services.short_term import ShortTermMemoryService
from app.utils.logger import get_logger, new_span_id

logger = get_logger()


def _format_short_term(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return ""
    lines = ["=== Current Session Context (SHORT_TERM) ==="]
    for e in entries:
        content = e.get("content", "")
        meta = e.get("metadata", {})
        ts = e.get("created_at", "")
        lines.append(f"[{ts}] {content}")
    return "\n".join(lines)


def _format_long_term(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return ""
    lines = ["=== Accumulated Knowledge (LONG_TERM) ==="]
    for e in entries:
        content = e.get("content", "")
        score = e.get("similarity_score", 0.0)
        lines.append(f"[relevance={score:.2f}] {content}")
    return "\n".join(lines)


def _format_reasoning(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return ""
    lines = ["=== Reasoning Patterns ==="]
    for e in entries:
        content = e.get("content", "")
        score = e.get("similarity_score", 0.0)
        lines.append(f"[relevance={score:.2f}] {content}")
    return "\n".join(lines)


def _format_episodic(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return ""
    lines = ["=== Relevant Past Experiences (EPISODIC) ==="]
    for e in entries:
        task_desc = e.get("task_description", e.get("content", ""))
        output = e.get("output", "")
        outcome = e.get("outcome", "")
        score = e.get("score", e.get("similarity_score", 0.0))
        lines.append(f"Task: {task_desc}")
        if output:
            lines.append(f"  Output: {output[:200]}")
        if outcome:
            lines.append(f"  Outcome: {outcome} (score={score:.2f})")
    return "\n".join(lines)


class PromptAssembler:
    def __init__(
        self,
        short_term: ShortTermMemoryService | None = None,
        long_term: LongTermMemoryService | None = None,
        reasoning: ReasoningMemoryService | None = None,
        episodic: EpisodicMemoryService | None = None,
    ) -> None:
        self._short_term = short_term or ShortTermMemoryService()
        self._long_term = long_term or LongTermMemoryService()
        self._reasoning = reasoning or ReasoningMemoryService()
        self._episodic = episodic or EpisodicMemoryService()

    async def assemble_prompt(
        self,
        agent_id: int,
        context: dict[str, Any],
        tiers: list[str],
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Assembles a dynamic system prompt from all requested memory tiers.

        Returns:
        {
          "system_prompt": str,
          "sources": { "short_term_hits": int, ... },
          "trace_id": str
        }
        """
        span_id = new_span_id()
        if trace_id is None:
            trace_id = str(uuid.uuid4())

        query_text = _build_query_text(context)

        # Kick off parallel retrieval — swallow per-tier exceptions
        tasks = [
            self._fetch_short_term(agent_id, context, tiers),
            self._fetch_long_term(agent_id, query_text, tiers),
            self._fetch_reasoning(agent_id, query_text, tiers),
            self._fetch_episodic(agent_id, query_text, tiers),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        st_entries = results[0] if not isinstance(results[0], Exception) else []
        lt_entries = results[1] if not isinstance(results[1], Exception) else []
        re_entries = results[2] if not isinstance(results[2], Exception) else []
        ep_entries = results[3] if not isinstance(results[3], Exception) else []

        # Log any exceptions from tiers
        tier_names = ["short_term", "long_term", "reasoning", "episodic"]
        for tier_name, result in zip(tier_names, results):
            if isinstance(result, Exception):
                logger.error(
                    "Tier retrieval failed during prompt assembly",
                    layer="service",
                    tier=tier_name,
                    agent_id=agent_id,
                    error=str(result),
                    span_id=span_id,
                    trace_id=trace_id,
                )

        # Build assembled prompt — never static strings, always from retrieved content
        sections: list[str] = []
        if st_entries:
            sections.append(_format_short_term(st_entries))
        if lt_entries:
            sections.append(_format_long_term(lt_entries))
        if re_entries:
            sections.append(_format_reasoning(re_entries))
        if ep_entries:
            sections.append(_format_episodic(ep_entries))

        system_prompt = "\n\n".join(sections) if sections else ""

        sources = PromptSourceCounts(
            short_term_hits=len(st_entries),
            long_term_hits=len(lt_entries),
            reasoning_hits=len(re_entries),
            episodic_hits=len(ep_entries),
        )

        logger.info(
            "Prompt assembled",
            layer="service",
            agent_id=agent_id,
            total_hits=sum([sources.short_term_hits, sources.long_term_hits, sources.reasoning_hits, sources.episodic_hits]),
            prompt_length=len(system_prompt),
            span_id=span_id,
            trace_id=trace_id,
        )

        return {
            "system_prompt": system_prompt,
            "sources": sources.model_dump(),
            "trace_id": trace_id,
        }

    async def _fetch_short_term(
        self, agent_id: int, context: dict[str, Any], tiers: list[str]
    ) -> list[dict[str, Any]]:
        if MemoryTier.SHORT_TERM.value not in tiers:
            return []
        session_id = context.get("session_id")
        if session_id:
            return await self._short_term.get_session_context(agent_id, str(session_id))
        return await self._short_term.read_all(agent_id)

    async def _fetch_long_term(
        self, agent_id: int, query: str, tiers: list[str]
    ) -> list[dict[str, Any]]:
        if MemoryTier.LONG_TERM.value not in tiers:
            return []
        return await self._long_term.semantic_search(agent_id, query, k=5)

    async def _fetch_reasoning(
        self, agent_id: int, query: str, tiers: list[str]
    ) -> list[dict[str, Any]]:
        if MemoryTier.REASONING.value not in tiers:
            return []
        return await self._reasoning.search(agent_id, query, k=3)

    async def _fetch_episodic(
        self, agent_id: int, query: str, tiers: list[str]
    ) -> list[dict[str, Any]]:
        if MemoryTier.EPISODIC.value not in tiers:
            return []
        return await self._episodic.retrieve_similar(agent_id, query, k=2)


def _build_query_text(context: dict[str, Any]) -> str:
    """Construct a single search query string from the context dict."""
    parts: list[str] = []
    if task_type := context.get("task_type"):
        parts.append(str(task_type))
    if domain := context.get("domain"):
        parts.append(str(domain))
    if messages := context.get("recent_messages"):
        if isinstance(messages, list):
            parts.extend(str(m) for m in messages[-3:])
        else:
            parts.append(str(messages))
    return " ".join(parts) if parts else "general context"
