"""Severity-aware course correction decision tree.

Decision logic (from ARCHITECTURE.md §8.3):
  score >= band_low                          → PASS
  score < band_low + LOW/MEDIUM criticality  → escalate to orchestrator
  score < band_low + HIGH/CRITICAL           → immediate local auto-correct
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Dict, Optional

from app.adapters.neo4j_adapter import Neo4jAdapter
from app.adapters.redis_adapter import RedisAdapter
from app.utils.logger import logger


class CourseAction(str, Enum):
    PASS = "PASS"
    ESCALATE_TO_ORCHESTRATOR = "ESCALATE_TO_ORCHESTRATOR"
    AUTO_CORRECT_LOCAL = "AUTO_CORRECT_LOCAL"
    ESCALATE_TO_USER = "ESCALATE_TO_USER"
    HALT = "HALT"


class CourseCorrectionResult:
    def __init__(
        self,
        action: CourseAction,
        reason: str = "",
        correction_applied: bool = False,
        corrected_response: Optional[str] = None,
        retry_context: Optional[str] = None,
    ) -> None:
        self.action = action
        self.reason = reason
        self.correction_applied = correction_applied
        self.corrected_response = corrected_response
        # Phase B.1: when AUTO_CORRECT_LOCAL fires, the corrector hands the
        # caller a corrective system message describing exactly what went
        # wrong. The caller (_execute_single_node) re-prompts the same agent
        # with this context appended; one retry per node is allowed.
        self.retry_context = retry_context


class CourseCorrector:
    """Evaluates score vs band and applies severity-aware correction."""

    def __init__(self, neo4j: Neo4jAdapter, redis: RedisAdapter) -> None:
        self._neo4j = neo4j
        self._redis = redis

    async def handle_score_failure(
        self,
        node_id: str,
        score: float,
        band_low: float,
        criticality: str,
        agent_id: int,
        task_id: str,
        response_text: str = "",
        trace_id: str = "",
    ) -> CourseCorrectionResult:
        """
        Entry point for the course correction decision tree.
        Always called when score < band_low.
        """
        span_id = str(uuid.uuid4())

        if score >= band_low:
            return CourseCorrectionResult(action=CourseAction.PASS, reason="score within band")

        criticality_upper = criticality.upper()
        logger.warning(
            "Score below band — evaluating correction",
            layer="service",
            node_id=node_id,
            score=score,
            band_low=band_low,
            criticality=criticality_upper,
            agent_id=agent_id,
            trace_id=trace_id,
            span_id=span_id,
        )

        if criticality_upper in ("HIGH", "CRITICAL"):
            return await self._auto_correct_locally(
                node_id=node_id,
                score=score,
                band_low=band_low,
                criticality=criticality_upper,
                agent_id=agent_id,
                task_id=task_id,
                response_text=response_text,
                trace_id=trace_id,
                span_id=span_id,
            )
        else:
            # LOW / MEDIUM → escalate to orchestrator
            return await self._escalate_to_orchestrator(
                node_id=node_id,
                score=score,
                band_low=band_low,
                criticality=criticality_upper,
                agent_id=agent_id,
                task_id=task_id,
                trace_id=trace_id,
                span_id=span_id,
            )

    async def _auto_correct_locally(
        self,
        node_id: str,
        score: float,
        band_low: float,
        criticality: str,
        agent_id: int,
        task_id: str,
        response_text: str,
        trace_id: str,
        span_id: str,
    ) -> CourseCorrectionResult:
        """HIGH/CRITICAL: correct immediately, log event, send async feedback."""
        logger.info(
            "AUTO_CORRECT_LOCAL triggered",
            layer="service",
            node_id=node_id,
            criticality=criticality,
            trace_id=trace_id,
            span_id=span_id,
        )

        # Log correction event to Neo4j
        event_id = str(uuid.uuid4())
        try:
            await self._neo4j.create_execution_event(
                event_id=event_id,
                event_type="AUTOCORRECT",
                agent_id=str(agent_id),
                node_id=node_id,
                score=score,
                action_taken=f"AUTO_CORRECT_LOCAL criticality={criticality}",
                correlation_id=trace_id,
                trace_id=trace_id,
            )
        except Exception as exc:
            logger.error(
                "Failed to log autocorrect event to Neo4j",
                layer="service",
                error=str(exc),
                trace_id=trace_id,
            )

        # Send async feedback to scoring service via Redis
        try:
            await self._redis.publish_to_stream(
                "scoring:feedback",
                {
                    "agent_id": str(agent_id),
                    "task_id": task_id,
                    "node_id": node_id,
                    "score": str(score),
                    "feedback_source": "ORCHESTRATOR",
                    "feedback_type": "AUTOCORRECT",
                    "action": "AUTO_CORRECT_LOCAL",
                },
                trace_id=trace_id,
            )
        except Exception as exc:
            logger.error(
                "Failed to publish autocorrect feedback",
                layer="service",
                error=str(exc),
                trace_id=trace_id,
            )

        # Phase B.1: build the corrective context the caller should append
        # to the agent's next prompt. Keep it concrete — naming the score,
        # the band, and a behavior hint gives the LLM something actionable
        # to reason about. Truncate the prior response so we don't blow up
        # the prompt; the LLM already saw the full version.
        prior_preview = (response_text or "").strip()
        if len(prior_preview) > 800:
            prior_preview = prior_preview[:800] + "…"
        retry_context = (
            "[AUTO_CORRECT — your prior response was below the quality band]\n"
            f"Prior score: {score:.2f}  |  Required band: ≥{band_low:.2f}  |  Criticality: {criticality}\n"
            "Common reasons a response scores below band: missing requested information, "
            "unsupported claims, wrong tool/source, vague summary instead of grounded data, "
            "ignored a part of the user's question.\n\n"
            "Re-do the task. Address every aspect of the original instruction. "
            "If you must call a tool, do so. Cite the source/dataset where relevant. "
            "Be more thorough and specific than your prior attempt.\n\n"
            f"PRIOR RESPONSE (for reference, do not just rephrase it):\n{prior_preview}"
        )

        return CourseCorrectionResult(
            action=CourseAction.AUTO_CORRECT_LOCAL,
            reason=f"criticality={criticality} requires immediate correction",
            correction_applied=True,
            retry_context=retry_context,
        )

    async def _escalate_to_orchestrator(
        self,
        node_id: str,
        score: float,
        band_low: float,
        criticality: str,
        agent_id: int,
        task_id: str,
        trace_id: str,
        span_id: str,
    ) -> CourseCorrectionResult:
        """LOW/MEDIUM: log event and return ESCALATE_TO_ORCHESTRATOR."""
        logger.info(
            "ESCALATE_TO_ORCHESTRATOR triggered",
            layer="service",
            node_id=node_id,
            criticality=criticality,
            score=score,
            band_low=band_low,
            trace_id=trace_id,
            span_id=span_id,
        )

        event_id = str(uuid.uuid4())
        try:
            await self._neo4j.create_execution_event(
                event_id=event_id,
                event_type="ESCALATION",
                agent_id=str(agent_id),
                node_id=node_id,
                score=score,
                action_taken=f"ESCALATE_TO_ORCHESTRATOR criticality={criticality}",
                correlation_id=trace_id,
                trace_id=trace_id,
            )
        except Exception as exc:
            logger.error(
                "Failed to log escalation event to Neo4j",
                layer="service",
                error=str(exc),
                trace_id=trace_id,
            )

        return CourseCorrectionResult(
            action=CourseAction.ESCALATE_TO_ORCHESTRATOR,
            reason=f"score={score:.3f} below band_low={band_low:.3f}, criticality={criticality}",
        )
