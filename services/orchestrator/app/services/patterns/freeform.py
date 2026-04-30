"""FreeFormPattern — last-resort catch-all.

Always accepts with a low score. Wins only when nothing else accepts.
Uses the bare-LLM decomposition path that's already in the pipeline.
"""

from __future__ import annotations

from app.services.patterns.types import (
    DispatchContext,
    ExecutionPlan,
    ExecutionResult,
    PatternMatch,
    Subtask,
)


class FreeFormPattern:
    name = "freeform"
    priority = 0

    async def detect(self, ctx: DispatchContext) -> PatternMatch:
        # Always accept — but at a score lower than every other pattern's
        # threshold so this only wins when nothing else fires.
        return PatternMatch(
            score=0.1,
            threshold=0.0,
            evidence=["catch-all"],
            explanation="no specific pattern matched; falling back to bare-LLM agent loop",
            payload={},
        )

    async def plan(self, ctx: DispatchContext, match: PatternMatch) -> ExecutionPlan:
        return ExecutionPlan(
            subtasks=[Subtask(description=ctx.question or "")],
            aggregation="default",
            metadata={"kind": "freeform"},
        )

    async def execute(self, ctx: DispatchContext, plan: ExecutionPlan) -> ExecutionResult:
        return ExecutionResult(response="", extras={"pattern": self.name})
