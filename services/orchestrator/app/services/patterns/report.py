"""ReportPattern — saved Report (SSRS / Cognos / PowerBI / SQL) match.

The translator's report resolver scores every saved Report against the
user's question; the orchestrator decides what to do with that score.
Three bands (same thresholds as today's branch):

  score >= 12  + margin to #2 >= 1   → execute report directly
  score >= 5                         → ask the user to confirm
  below                              → ignore
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.patterns.types import (
    DispatchContext,
    ExecutionPlan,
    ExecutionResult,
    PatternMatch,
    Subtask,
)


AUTO_FIRE_THRESHOLD = 12.0
CONFIRM_THRESHOLD = 5.0
MIN_MARGIN = 1.0


class ReportPattern:
    """Match against translator.matched_reports."""

    name = "report"
    priority = 90

    def __init__(self):
        # ReportPattern uses the translator output (matched_reports) and
        # delegates back to the orchestrator's _execute_matched_report
        # helper at execute time. No detect-time deps.
        pass

    async def detect(self, ctx: DispatchContext) -> PatternMatch:
        matched: List[Dict[str, Any]] = ctx.translator.get("matched_reports") or []
        if not matched:
            return PatternMatch(
                score=0.0,
                threshold=CONFIRM_THRESHOLD,
                explanation="no matched reports from translator",
            )

        top = matched[0] or {}
        try:
            top_score = float(top.get("score") or 0.0)
        except (TypeError, ValueError):
            top_score = 0.0
        try:
            second_score = float((matched[1] or {}).get("score") or 0.0) if len(matched) > 1 else 0.0
        except (TypeError, ValueError):
            second_score = 0.0

        margin = top_score - second_score
        report_name = top.get("name") or top.get("report_id") or "(unnamed)"

        # Band classification baked into payload.kind so plan() doesn't
        # have to re-decide.
        if top_score >= AUTO_FIRE_THRESHOLD and margin >= MIN_MARGIN:
            kind = "auto_fire"
        elif top_score >= CONFIRM_THRESHOLD:
            kind = "confirm"
        else:
            kind = "below"

        evidence = [
            f"matched_reports[0].name={report_name!r}",
            f"score={top_score:.2f}",
            f"margin_to_next={margin:.2f}",
        ]
        explanation = (
            f"top report '{report_name}' score={top_score:.2f}"
            f" (band={kind})"
        )

        return PatternMatch(
            score=top_score,
            threshold=CONFIRM_THRESHOLD,
            evidence=evidence,
            explanation=explanation,
            payload={
                "report": top,
                "score": top_score,
                "margin": margin,
                "kind": kind,
            },
        )

    async def plan(self, ctx: DispatchContext, match: PatternMatch) -> ExecutionPlan:
        kind = match.payload.get("kind") or "below"
        report = match.payload.get("report") or {}
        score = match.payload.get("score") or 0.0
        report_name = report.get("name") or "(unnamed)"

        if kind == "auto_fire":
            # Single subtask; execute() runs the report directly via
            # the host pipeline's _execute_matched_report helper.
            return ExecutionPlan(
                subtasks=[],
                aggregation="report_passthrough",
                metadata={
                    "report": report,
                    "report_id": report.get("report_id"),
                    "score": score,
                    "execution_kind": "auto_fire",
                },
            )

        if kind == "confirm":
            confirm_msg = (
                f"I found a saved report **'{report_name}'** that may "
                f"answer your question. Reply **yes** to use the report, "
                f"or **data** to have me look up the data directly. You "
                f"can also restate or refine your question."
            )
            return ExecutionPlan(
                subtasks=[],
                aggregation="report_passthrough",
                clarification_needed=True,
                clarification_question=confirm_msg,
                clarification_kind="report_confirm",
                response=confirm_msg,
                metadata={
                    "report": report,
                    "report_id": report.get("report_id"),
                    "score": score,
                    "execution_kind": "confirm",
                    "report_name": report_name,
                },
            )

        # "below" should not have been the winner because the threshold
        # is CONFIRM_THRESHOLD; defensive — fall through to a no-op.
        return ExecutionPlan(
            subtasks=[],
            aggregation="default",
            metadata={"execution_kind": "below_threshold_passthrough"},
        )

    async def execute(self, ctx: DispatchContext, plan: ExecutionPlan) -> ExecutionResult:
        # Phase 3 keeps execute() as a stub — the legacy pipeline still
        # drives. Phase 4 wires this to the host's _execute_matched_report
        # and pending-report-confirm helpers.
        kind = plan.metadata.get("execution_kind", "")
        return ExecutionResult(
            response=plan.response or "",
            clarification_needed=plan.clarification_needed,
            clarification_question=plan.clarification_question,
            clarification_kind=plan.clarification_kind,
            pending_report_id=(
                (plan.metadata.get("report") or {}).get("report_id")
                if kind == "confirm" else None
            ),
            matched_report_id=(
                (plan.metadata.get("report") or {}).get("report_id")
                if kind == "auto_fire" else None
            ),
            extras={"pattern": self.name, "kind": kind},
        )
