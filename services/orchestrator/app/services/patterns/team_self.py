"""TeamSelfPattern — questions about the team itself.

"hi how many agents do you have in your team with access to which
tools" → don't run the agent loop; synthesise from team_context that's
already loaded into the dispatcher."""

from __future__ import annotations

import re

from app.services.patterns.types import (
    DispatchContext,
    ExecutionPlan,
    ExecutionResult,
    PatternMatch,
    Subtask,
)


# These phrases are highly distinctive — the user is talking ABOUT the
# system, not USING it.
_SELF_REF_RE = re.compile(
    r"\b(?:your\s+team|this\s+team|the\s+team|"
    r"your\s+(?:tools?|agents?|capabilities)|"
    r"what\s+(?:tools?|agents?|capabilities)\s+(?:do|does)\s+you\s+(?:have|use)|"
    r"who\s+(?:are|is)\s+(?:in\s+)?(?:your|the)\s+team|"
    r"how\s+many\s+(?:tools?|agents?)\s+(?:do|does)\s+(?:you|this\s+team)\s+have|"
    r"list\s+(?:your|the)\s+(?:tools?|agents?))\b",
    re.IGNORECASE,
)


class TeamSelfPattern:
    name = "team_self"
    priority = 95  # very high — beats Report when both fire

    async def detect(self, ctx: DispatchContext) -> PatternMatch:
        q = ctx.question or ""
        if not q.strip():
            return PatternMatch(score=0.0, threshold=0.6, explanation="empty question")

        if not _SELF_REF_RE.search(q):
            return PatternMatch(
                score=0.0,
                threshold=0.6,
                explanation="no team-self phrasing",
            )

        agents = list(ctx.team.agents or [])
        if not agents:
            # No team context loaded. Decline gracefully — the freeform
            # path can still answer with "I don't know my team yet".
            return PatternMatch(
                score=0.4,
                threshold=0.6,
                evidence=["regex matched but team not loaded"],
                explanation="self-reference detected but team context empty",
            )

        return PatternMatch(
            score=0.8,
            threshold=0.6,
            evidence=[
                "regex 'your team / your tools' matched",
                f"team has {len(agents)} agent(s)",
            ],
            explanation="answer from team_context — no agent loop needed",
            payload={"agent_count": len(agents)},
        )

    async def plan(self, ctx: DispatchContext, match: PatternMatch) -> ExecutionPlan:
        return ExecutionPlan(
            subtasks=[
                Subtask(
                    description=f"[team-self] {ctx.question}",
                    metadata={"kind": "team_self"},
                )
            ],
            aggregation="default",
            metadata={"kind": "team_self"},
        )

    async def execute(self, ctx: DispatchContext, plan: ExecutionPlan) -> ExecutionResult:
        return ExecutionResult(response="", extras={"pattern": self.name})
