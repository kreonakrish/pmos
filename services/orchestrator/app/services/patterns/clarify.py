"""ClarifyPattern — surfaces the translator's clarification question.

The translator decides when it needs to ask the user something
(synonym ambiguity, NO_RESOLUTION). This pattern just propagates that
signal — it does NOT generate clarifications itself."""

from __future__ import annotations

from app.services.patterns.types import (
    DispatchContext,
    ExecutionPlan,
    ExecutionResult,
    PatternMatch,
)


class ClarifyPattern:
    name = "clarify"
    priority = 85  # below TeamSelf/Report, above all data/RAG patterns

    async def detect(self, ctx: DispatchContext) -> PatternMatch:
        need = bool(ctx.translator.get("clarification_needed"))
        question = ctx.translator.get("clarification_question")
        if not need or not question:
            return PatternMatch(
                score=0.0,
                threshold=0.5,
                explanation="translator did not request clarification",
            )

        return PatternMatch(
            score=0.95,
            threshold=0.5,
            evidence=[
                "translator.clarification_needed == True",
                f"clarification_question_len={len(str(question))}",
            ],
            explanation="translator surfaced an ambiguity; pass-through",
            payload={
                "question": question,
                "issue_id": ctx.translator.get("auditor_issue_id"),
                "issue_kind": ctx.translator.get("auditor_issue_kind"),
            },
        )

    async def plan(self, ctx: DispatchContext, match: PatternMatch) -> ExecutionPlan:
        question = str(match.payload.get("question") or "")
        return ExecutionPlan(
            subtasks=[],
            aggregation="clarify",
            response=question,
            clarification_needed=True,
            clarification_question=question,
            metadata={
                "issue_id": match.payload.get("issue_id"),
                "issue_kind": match.payload.get("issue_kind"),
            },
        )

    async def execute(self, ctx: DispatchContext, plan: ExecutionPlan) -> ExecutionResult:
        return ExecutionResult(
            response=plan.response or "",
            clarification_needed=True,
            clarification_question=plan.clarification_question,
            auditor_issue_id=plan.metadata.get("issue_id"),
            auditor_issue_kind=plan.metadata.get("issue_kind"),
            extras={"pattern": self.name},
        )
