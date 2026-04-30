"""EntityCountPattern — pure count of a business entity.

"how many total loans are there in the system" / "count of borrowers"
/ "total mortgages" — the user wants a number, not a row sample, not
a column distribution.

Sits at priority 86 (just above Clarify=85) because the translator's
ontology synonym detector loves to mis-fire on "total <something>" by
matching `total_*_amount` BAs and asking the user to disambiguate
balance columns. EntityCountPattern preempts that bogus clarification.

Plan + execution:
  Plan emits a per-DB/GRAPH-agent broadcast subtask with dual SQL +
  Cypher count recipes (built by the host pipeline's
  _build_schema_meta_subtasks(kind="entity_count") helper). Each agent
  returns a JSON array of {tool, source, type, count, is_subtype_of?}.
  Step-8 aggregation runs python_reduce — the team's PythonAnalyst
  totals the canonical (non-subtype) counts and emits the breakdown
  table; LLMs are unreliable at exact arithmetic and the
  no-double-count rule is far easier in code than prompt.
"""

from __future__ import annotations

import re
from typing import Optional

from app.services.patterns.types import (
    DispatchContext,
    ExecutionPlan,
    ExecutionResult,
    PatternMatch,
    Subtask,
)


_VERB_RE = re.compile(
    r"\b(?:how\s+many|number\s+of|count\s+of|total(?:\s+number)?\s+of?|"
    r"how\s+much|"
    r"total\s+(?=[a-z]))\b",
    re.IGNORECASE,
)
_DISQUALIFIERS_RE = re.compile(
    r"\b(?:tables?|columns?|fields?|attributes?|databases?|schemas?|"
    r"datasets?|catalogs?|"
    r"sample|samples|rows?|records?|values?|"
    r"average|sum|max|min|median|"
    r"where\s+|having\s+|group\s+by)\b",
    re.IGNORECASE,
)
_PREDICATE_RE = re.compile(r"[<>=!]=?\s*['\"\d]")
_FILLERS = (r"(?:total|active|inactive|pending|outstanding|closed|open|"
            r"new|the|all|currently|distinct|unique)")
_NOUN_RE = re.compile(
    rf"\b(?:how\s+many|number\s+of|count\s+of|total(?:\s+number)?\s+of?"
    rf"|how\s+much|total)\s+(?:{_FILLERS}\s+)*"
    rf"([a-zA-Z][a-zA-Z0-9_]*)\b",
    re.IGNORECASE,
)
_FILLER_TOKENS = {
    "total", "active", "inactive", "pending", "outstanding", "closed",
    "open", "new", "distinct", "unique", "currently",
    "are", "is", "do", "does", "have", "has", "the",
}


def _extract_entity_token(question: str) -> Optional[str]:
    m = _NOUN_RE.search(question)
    if not m:
        return None
    cand = (m.group(1) or "").strip()
    if not cand or cand.lower() in _FILLER_TOKENS or len(cand) < 2:
        return None
    return cand


class EntityCountPattern:
    name = "entity_count"
    priority = 86

    async def detect(self, ctx: DispatchContext) -> PatternMatch:
        evidence = []
        score = 0.0
        # Trust the translator's verdict first.
        if ctx.translator.get("intent") == "entity_count_question":
            evidence.append("translator.intent == 'entity_count_question'")
            score = 0.85

        # Local regex carries the decision when translator wasn't run
        # (e.g. unit tests) or when its detector misses a phrasing.
        q = ctx.question or ""
        q_l = q.lower()
        verb_hit = bool(_VERB_RE.search(q_l))
        disqualified = (
            bool(_DISQUALIFIERS_RE.search(q_l))
            or bool(_PREDICATE_RE.search(q_l))
        )
        if verb_hit and not disqualified:
            evidence.append("regex 'how many <noun>' matched (no disqualifiers)")
            score = max(score, 0.75)

        if score == 0.0:
            return PatternMatch(
                score=0.0,
                threshold=0.6,
                explanation=(
                    "no count verb"
                    if not verb_hit
                    else "count verb but disqualifier present "
                         "(table/column/predicate/aggregator)"
                ),
            )

        entity = (
            str(ctx.translator.get("schema_meta_column") or "").strip()
            or _extract_entity_token(q)
            or ""
        )
        if entity:
            evidence.append(f"entity='{entity}'")
            score = min(1.0, score + 0.05)

        # When the translator already bound the question to specific
        # dataset(s), the user has narrowed the scope themselves —
        # defer to BusinessPattern, which runs the agent loop with the
        # binding in hand. EntityCount is for the wider "across the
        # whole system" case where no specific source was named.
        # Translator-classified entity_count_question still wins because
        # that path skips the ontology and never sets bindings.
        if (
            ctx.translator.get("intent") != "entity_count_question"
            and (ctx.translator.get("dataset_bindings") or [])
        ):
            n_bindings = len(ctx.translator.get("dataset_bindings") or [])
            evidence.append(
                f"translator bound {n_bindings} dataset(s) — defer to business"
            )
            score = min(score, 0.4)

        # Need at least one DB/GRAPH agent to broadcast against.
        db_agents = ctx.team.agents_with_tool_type("DATABASE", "GRAPH")
        if not db_agents:
            evidence.append("no DB/GRAPH agents on team")
            score = min(score, 0.4)

        # Note: python_reduce is best-effort — the orchestrator's
        # _step8_python_reduce falls back to LLM synthesis when no
        # PYTHON-tool agent is on the team. Don't penalise the
        # detection for missing PythonAnalyst.

        return PatternMatch(
            score=score,
            threshold=0.6,
            evidence=evidence,
            explanation=(
                f"entity-count broadcast (entity={entity!r}, "
                f"db_agents={len(db_agents)})"
            ),
            payload={
                "entity": entity,
                "db_agent_ids": [a.get("agent_id") for a in db_agents],
                "aggregation": "python_reduce",
            },
        )

    async def plan(self, ctx: DispatchContext, match: PatternMatch) -> ExecutionPlan:
        entity = str(match.payload.get("entity") or "")
        agents = list(match.payload.get("db_agent_ids") or [])
        return ExecutionPlan(
            subtasks=[
                Subtask(
                    description=f"[entity-count-broadcast] entity={entity!r}",
                    agent_id=aid,
                    force_proceed=True,
                    metadata={"kind": "entity_count", "entity": entity},
                )
                for aid in agents
            ],
            aggregation="python_reduce",
            metadata={
                "kind": "entity_count",
                "entity": entity,
                "reduce_instructions": (
                    "Group counts by canonical entity. Subtract subtype "
                    "rows (is_subtype_of set) from parent totals — they're "
                    "already included. Sum surviving rows for the headline."
                ),
            },
        )

    async def execute(self, ctx: DispatchContext, plan: ExecutionPlan) -> ExecutionResult:
        # Phase-3-style stub — execution still flows through the host
        # pipeline's broadcast helper. The pattern's plan() metadata
        # records the routing for the UI's decision trace.
        return ExecutionResult(response="", extras={"pattern": self.name})
