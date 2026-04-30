"""Question-pattern dispatcher.

Runs every registered pattern's ``detect()`` in parallel, picks the
winner by ``(accepted, priority, registry_order)``, and records a
``DecisionTrace`` of every candidate's score.

In **shadow mode** (Phase 1) the dispatcher is wired into the pipeline
but does NOT drive routing — it only stamps the trace on the TaskGraph
so the legacy ``if/elif`` dispatch can be A/B-compared against it.
The cutover (Phase 4) flips a single flag.
"""

from __future__ import annotations

import asyncio
import time
from typing import List, Optional, Tuple

from app.services.patterns.types import (
    CandidateScore,
    DecisionTrace,
    DispatchContext,
    PatternMatch,
    QuestionPattern,
)
from app.utils.logger import logger


class PatternDispatcher:
    """Walks the registered patterns and picks one winner per request."""

    def __init__(self, patterns: List[QuestionPattern]):
        # Order is stable: registry order is the final tie-break, so we
        # preserve insertion order. Priority sort is computed at
        # dispatch time so callers can mutate the list (registries
        # under test) without breaking the dispatcher.
        self._patterns = list(patterns)

    @property
    def patterns(self) -> List[QuestionPattern]:
        return list(self._patterns)

    async def dispatch(
        self,
        ctx: DispatchContext,
        *,
        shadow: bool = False,
    ) -> Tuple[Optional[QuestionPattern], Optional[PatternMatch], DecisionTrace]:
        """Run every pattern's detect() and pick the winner.

        Returns ``(winning_pattern, winning_match, trace)``. When no
        pattern accepted, the first two are ``None`` — callers fall
        back to whatever default pattern they have registered (today
        FreeFormPattern). The trace always contains every candidate's
        score, including the rejects.
        """
        start = time.monotonic()

        async def _detect(p: QuestionPattern) -> Tuple[QuestionPattern, CandidateScore, Optional[PatternMatch]]:
            t0 = time.monotonic()
            try:
                match = await p.detect(ctx)
            except Exception as exc:
                duration_ms = int((time.monotonic() - t0) * 1000)
                logger.warning(
                    "Pattern detect raised — recording as rejected",
                    layer="dispatcher",
                    pattern=getattr(p, "name", "?"),
                    error=str(exc),
                    trace_id=ctx.trace_id,
                )
                return (
                    p,
                    CandidateScore(
                        name=getattr(p, "name", "?"),
                        priority=int(getattr(p, "priority", 0)),
                        score=0.0,
                        threshold=1.0,
                        accepted=False,
                        evidence=[],
                        explanation="detect() raised",
                        error=str(exc)[:240],
                        duration_ms=duration_ms,
                    ),
                    None,
                )
            duration_ms = int((time.monotonic() - t0) * 1000)
            cand = CandidateScore(
                name=p.name,
                priority=int(p.priority),
                score=float(match.score),
                threshold=float(match.threshold),
                accepted=bool(match.accepted),
                evidence=list(match.evidence),
                explanation=match.explanation or "",
                duration_ms=duration_ms,
            )
            return p, cand, match

        results = await asyncio.gather(
            *[_detect(p) for p in self._patterns],
            return_exceptions=False,  # _detect already swallows exceptions
        )

        candidates = [r[1] for r in results]
        # Pick the winner. Sort key: accepted-first, then priority desc,
        # then registry order. Registry order is preserved by the
        # ``index`` we capture below.
        accepted = [
            (idx, p, m)
            for idx, (p, _, m) in enumerate(results)
            if m is not None and m.accepted
        ]
        accepted.sort(key=lambda t: (-int(t[1].priority), t[0]))

        winner: Optional[QuestionPattern] = None
        winning_match: Optional[PatternMatch] = None
        if accepted:
            _, winner, winning_match = accepted[0]

        trace = DecisionTrace(
            candidates=candidates,
            winner=winner.name if winner else None,
            duration_ms=int((time.monotonic() - start) * 1000),
            translator_summary={
                "intent": ctx.translator.get("intent"),
                "domain": ctx.translator.get("domain"),
                "fallback_used": ctx.translator.get("fallback_used"),
                "n_canonical_entities": len(ctx.translator.get("canonical_entities") or []),
                "n_dataset_bindings": len(ctx.translator.get("dataset_bindings") or []),
                "n_matched_reports": len(ctx.translator.get("matched_reports") or []),
                "schema_meta_column": ctx.translator.get("schema_meta_column") or "",
            },
            shadow=shadow,
        )

        logger.info(
            "Pattern dispatch decision",
            layer="dispatcher",
            shadow=shadow,
            winner=trace.winner,
            candidate_count=len(candidates),
            duration_ms=trace.duration_ms,
            trace_id=ctx.trace_id,
        )
        return winner, winning_match, trace
