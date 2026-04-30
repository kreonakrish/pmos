"""ColumnValuePattern — "value of X across these tables" / "give me 5
sample loan_id values from each table" / "show me sample data of
borrower_id from every database".

Sister of MetadataPattern: same broadcast pattern (one subtask per
DB/GRAPH agent), different SQL plan (list-then-sample vs
information_schema-only)."""

from __future__ import annotations

import re

from app.services.patterns.types import (
    DispatchContext,
    ExecutionPlan,
    ExecutionResult,
    PatternMatch,
    Subtask,
)
from app.services.patterns.base import extract_column_name, parse_sample_count


_VALUE_VERBS_RE = re.compile(
    r"\b(?:value|values|sample|samples|sampling|rows?|records?|"
    r"data|observations?|examples?|entries|instances?)\b",
    re.IGNORECASE,
)
_SCOPE_RE = re.compile(
    r"\b(?:across|in\s+each|from\s+each|from\s+all|from\s+the|"
    r"from\s+these|from\s+those|every\s+(?:table|database|source)|"
    r"\btables\b|\bdatabases\b|data\s*sources?|"
    r"\bdatasets\b|\btools\b)\b",
    re.IGNORECASE,
)


class ColumnValuePattern:
    name = "column_value"
    priority = 65

    async def detect(self, ctx: DispatchContext) -> PatternMatch:
        evidence = []
        score = 0.0
        if ctx.translator.get("intent") == "column_value_question":
            evidence.append("translator.intent == 'column_value_question'")
            score = 0.85

        q = ctx.question or ""
        q_l = q.lower()
        verb_hit = bool(_VALUE_VERBS_RE.search(q_l))
        scope_hit = bool(_SCOPE_RE.search(q_l))
        if verb_hit and scope_hit:
            evidence.append("regex value-verb + multi-source qualifier")
            score = max(score, 0.75)

        if score == 0.0:
            return PatternMatch(
                score=0.0,
                threshold=0.6,
                explanation=(
                    "no value-sampling phrasing"
                    if not (verb_hit or scope_hit)
                    else "value-verb without multi-source qualifier"
                ),
            )

        column = (
            str(ctx.translator.get("schema_meta_column") or "").strip()
            or extract_column_name(q)
            or ""
        )
        if column:
            evidence.append(f"column='{column}'")
            score = min(1.0, score + 0.05)

        sample_n = parse_sample_count(q, default=5)
        if sample_n != 5:
            evidence.append(f"sample_n={sample_n}")

        db_agents = ctx.team.agents_with_tool_type("DATABASE", "GRAPH")
        if not db_agents:
            evidence.append("no DB/GRAPH agents on team")
            score = min(score, 0.4)

        return PatternMatch(
            score=score,
            threshold=0.6,
            evidence=evidence,
            explanation=(
                f"column-value broadcast (column={column!r}, "
                f"sample_n={sample_n}, db_agents={len(db_agents)})"
            ),
            payload={
                "column": column,
                "sample_n": sample_n,
                "db_agent_ids": [a.get("agent_id") for a in db_agents],
            },
        )

    async def plan(self, ctx: DispatchContext, match: PatternMatch) -> ExecutionPlan:
        column = str(match.payload.get("column") or "")
        sample_n = int(match.payload.get("sample_n") or 5)
        agents = list(match.payload.get("db_agent_ids") or [])
        return ExecutionPlan(
            subtasks=[
                Subtask(
                    description=f"[column-value-broadcast] column={column!r} sample_n={sample_n}",
                    agent_id=aid,
                    force_proceed=True,
                    metadata={"kind": "column_value", "column": column, "sample_n": sample_n},
                )
                for aid in agents
            ],
            aggregation="broadcast_merge",
            metadata={
                "kind": "column_value",
                "column": column,
                "sample_n": sample_n,
            },
        )

    async def execute(self, ctx: DispatchContext, plan: ExecutionPlan) -> ExecutionResult:
        return ExecutionResult(response="", extras={"pattern": self.name})
