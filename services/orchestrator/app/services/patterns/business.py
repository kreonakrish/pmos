"""BusinessPattern — the standard data-analytics path.

The catch-all for ontology-bound questions: "how many loans in
pmos_servicing have term_months > 300", "what is the status of loan
L0009 in foreclosures", "list BridgeLoan and HomeEquityLoan records
and borrower segments". These need the agent loop with bidding +
tool use; nothing special routing-wise.

Score is driven by translator output — if the translator bound
canonical entities AND dataset bindings, we're confident; if only one,
moderate; if neither, this pattern doesn't fire and FreeForm picks
up.
"""

from __future__ import annotations

from app.services.patterns.types import (
    DispatchContext,
    ExecutionPlan,
    ExecutionResult,
    PatternMatch,
    Subtask,
)


class BusinessPattern:
    name = "business"
    priority = 50

    async def detect(self, ctx: DispatchContext) -> PatternMatch:
        canonical = ctx.translator.get("canonical_entities") or []
        bindings = ctx.translator.get("dataset_bindings") or []
        subtasks = ctx.translator.get("domain_subtasks") or []

        evidence = []
        score = 0.0

        if canonical and bindings:
            evidence.append(
                f"translator bound {len(canonical)} entities + "
                f"{len(bindings)} dataset bindings"
            )
            score = 0.7
        elif canonical:
            evidence.append(
                f"translator bound {len(canonical)} entities (no dataset bindings)"
            )
            score = 0.55
        elif bindings:
            evidence.append(
                f"translator returned {len(bindings)} dataset bindings (no entities)"
            )
            score = 0.55
        else:
            return PatternMatch(
                score=0.0,
                threshold=0.5,
                explanation="no canonical entities or dataset bindings",
            )

        if subtasks:
            evidence.append(f"translator decomposition produced {len(subtasks)} subtasks")
            score = min(1.0, score + 0.1)

        # Intent strength — promote when intent is one of the analytics
        # buckets (these indicate data work, not catalog/RAG).
        intent = (ctx.translator.get("intent") or "").lower()
        if intent in {"metric_lookup", "trend_analysis", "comparison", "lineage"}:
            evidence.append(f"intent='{intent}' (analytics bucket)")
            score = min(1.0, score + 0.05)

        return PatternMatch(
            score=score,
            threshold=0.5,
            evidence=evidence,
            explanation=(
                f"ontology-bound data question "
                f"(entities={len(canonical)}, bindings={len(bindings)}, "
                f"subtasks={len(subtasks)})"
            ),
            payload={
                "subtasks": [str(s) for s in subtasks if s],
                "canonical_count": len(canonical),
                "binding_count": len(bindings),
            },
        )

    async def plan(self, ctx: DispatchContext, match: PatternMatch) -> ExecutionPlan:
        # The standard ontology decomposition path — turn the
        # translator's domain_subtasks into Subtasks. No pre-assignment;
        # bidding picks winners.
        descs = match.payload.get("subtasks") or []
        if not descs:
            descs = [ctx.question]
        return ExecutionPlan(
            subtasks=[Subtask(description=d) for d in descs],
            aggregation="default",
            metadata={"kind": "business"},
        )

    async def execute(self, ctx: DispatchContext, plan: ExecutionPlan) -> ExecutionResult:
        return ExecutionResult(response="", extras={"pattern": self.name})
