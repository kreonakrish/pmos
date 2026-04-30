"""MetadataPattern — "where does column X live?" / "how many tables
have a column called X" / "which databases contain Y" / "is there a
field named Z" — catalog-shape questions.

Today the translator emits ``intent="schema_meta_question"`` for
these. The pattern reads that signal directly so we don't duplicate
the regex work."""

from __future__ import annotations

import re
from typing import Any, Dict

from app.services.patterns.types import (
    DispatchContext,
    ExecutionPlan,
    ExecutionResult,
    PatternMatch,
    Subtask,
)
from app.services.patterns.base import extract_column_name


# Same phrasings the translator detects, kept here so a future change
# to the translator (which we want to slim down) doesn't silently
# disable this pattern.
_OBJECT_TOKENS = r"(?:tables?|databases?|schemas?|datasets?|systems?|catalogs?|stores?)"
_FIELD_TOKENS = r"(?:columns?|fields?|attributes?|properties)"
_CATALOG_FIELD_RE = re.compile(
    rf"\b{_OBJECT_TOKENS}\b[\s\w]{{0,80}}?\b{_FIELD_TOKENS}\b"
    rf"|\b{_FIELD_TOKENS}\b[\s\w]{{0,80}}?\b{_OBJECT_TOKENS}\b",
    re.IGNORECASE,
)
_EXISTENCE_RE = re.compile(
    r"\b(?:where\s+(?:is|does|do|are|can\s+(?:i|we)\s+find)"
    r"|in\s+which\s+(?:tables?|databases?|schemas?|datasets?)"
    r"|is\s+(?:there|the)\s+(?:a\s+)?(?:column|field|attribute)"
    r"|does\s+(?:any|the)\s+(?:table|database|schema|dataset)"
    r"|which\s+(?:tables?|databases?|schemas?|datasets?)\s+(?:have|contain|with|has))\b",
    re.IGNORECASE,
)


class MetadataPattern:
    name = "metadata"
    priority = 70

    async def detect(self, ctx: DispatchContext) -> PatternMatch:
        # Trust the translator first — if it already classified this as
        # schema_meta_question, accept with high confidence.
        evidence = []
        score = 0.0
        if ctx.translator.get("intent") == "schema_meta_question":
            evidence.append("translator.intent == 'schema_meta_question'")
            score = 0.85

        # Independent regex hit boosts confidence (or carries the
        # decision when the translator wasn't run).
        q = ctx.question or ""
        q_l = q.lower()
        regex_hit = False
        if _CATALOG_FIELD_RE.search(q_l):
            evidence.append("regex 'tables ... columns' matched")
            regex_hit = True
        if _EXISTENCE_RE.search(q_l):
            evidence.append("regex existence-verb matched")
            regex_hit = True
        if regex_hit:
            score = max(score, 0.75)

        if score == 0.0:
            return PatternMatch(
                score=0.0,
                threshold=0.6,
                explanation="no catalog-shape phrasing",
            )

        # Column extraction — translator may have already stashed it.
        column = (
            str(ctx.translator.get("schema_meta_column") or "").strip()
            or extract_column_name(q)
            or ""
        )
        if column:
            evidence.append(f"column='{column}'")
            score = min(1.0, score + 0.05)

        # We need at least one DATABASE/GRAPH agent to make a broadcast
        # plan worthwhile. If none, score down so a different pattern
        # (or FreeForm) can take over.
        db_agents = ctx.team.agents_with_tool_type("DATABASE", "GRAPH")
        if not db_agents:
            evidence.append("no DB/GRAPH agents on team")
            score = min(score, 0.4)

        return PatternMatch(
            score=score,
            threshold=0.6,
            evidence=evidence,
            explanation=(
                f"catalog-shape question (column={column!r}, "
                f"db_agents={len(db_agents)})"
            ),
            payload={"column": column, "db_agent_ids": [a.get("agent_id") for a in db_agents]},
        )

    async def plan(self, ctx: DispatchContext, match: PatternMatch) -> ExecutionPlan:
        # The plan() body is intentionally minimal — Phase 4 wires this
        # to the host pipeline's _build_schema_meta_subtasks helper so
        # we don't duplicate the SQL templates. For Phase 3 (shadow)
        # we just record the intent + target agents.
        column = str(match.payload.get("column") or "")
        agents = list(match.payload.get("db_agent_ids") or [])
        return ExecutionPlan(
            subtasks=[
                Subtask(
                    description=f"[metadata-broadcast] column={column!r}",
                    agent_id=aid,
                    force_proceed=True,
                    metadata={"kind": "schema_meta", "column": column},
                )
                for aid in agents
            ],
            aggregation="broadcast_merge",
            metadata={"kind": "schema_meta", "column": column},
        )

    async def execute(self, ctx: DispatchContext, plan: ExecutionPlan) -> ExecutionResult:
        # Phase 4 will wire this to the existing broadcast machinery.
        return ExecutionResult(response="", extras={"pattern": self.name})
