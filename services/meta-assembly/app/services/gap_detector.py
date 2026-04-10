"""Gap detector — uses LLM to identify missing capabilities from failure context."""
from __future__ import annotations

import json
import uuid
from typing import Any

from app.adapters.llm_adapter import LLMAdapter, get_llm_adapter
from app.config import settings
from app.utils.logger import get_logger
from app.utils.metrics import GAPS_DETECTED_TOTAL

logger = get_logger(layer="service")

VALID_CAPABILITY_TYPES = {"TOOL", "SKILL", "AGENT"}


class GapDetectorService:
    """Analyses failed task context to identify what capability is missing."""

    def __init__(self, llm: LLMAdapter | None = None) -> None:
        self._llm = llm or get_llm_adapter()

    # ── Prompt assembly (never a static string) ──────────────────────────────

    def _build_gap_detection_prompt(
        self,
        task_context: dict[str, Any],
        failed_agents: list[int],
        failure_reasons: list[str],
    ) -> str:
        """Dynamically construct the gap-detection prompt from runtime context."""
        task_id = task_context.get("task_id", "unknown")
        task_type = task_context.get("task_type", "unknown")
        required_tools = task_context.get("required_tools", [])

        failed_agents_str = ", ".join(str(a) for a in failed_agents) or "none"
        failure_reasons_str = "\n".join(
            f"  - {r}" for r in failure_reasons
        ) or "  - No specific reason provided"
        required_tools_str = ", ".join(required_tools) or "none"

        return f"""You are an AI orchestration architect analysing a task execution failure.

Task details:
  - task_id: {task_id}
  - task_type: {task_type}
  - required_tools: {required_tools_str}

Failed agent IDs: {failed_agents_str}

Failure reasons:
{failure_reasons_str}

Based on the above, identify the capability gap that prevented successful execution.

Respond with a JSON object containing exactly these fields:
{{
  "gap_description": "<one or two sentence description of what is missing>",
  "suggested_capability_type": "<one of: TOOL, SKILL, AGENT>",
  "confidence": <float between 0.0 and 1.0>
}}

Rules:
- TOOL  → if a specific function, API call, or data transformation is missing
- SKILL → if a reasoning pattern, domain knowledge, or prompt strategy is missing
- AGENT → if no agent exists with the required domain expertise or role
- Confidence should reflect how certain you are given the available information
"""

    def _parse_gap_response(
        self, raw: dict[str, Any], trace_id: str
    ) -> dict[str, Any]:
        cap_type = str(raw.get("suggested_capability_type", "TOOL")).upper()
        if cap_type not in VALID_CAPABILITY_TYPES:
            cap_type = "TOOL"

        confidence = float(raw.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))

        return {
            "gap_description": str(raw.get("gap_description", "Unknown capability gap")),
            "suggested_capability_type": cap_type,
            "confidence": confidence,
            "trace_id": trace_id,
        }

    # ── Public API ────────────────────────────────────────────────────────────

    async def detect_gap(
        self,
        task_context: dict[str, Any],
        failed_agents: list[int],
        failure_reasons: list[str],
        trace_id: str = "",
    ) -> dict[str, Any]:
        """Identify the capability gap via LLM analysis."""
        trace_id = trace_id or str(uuid.uuid4())
        logger.info(
            "gap_detection_started",
            trace_id=trace_id,
            task_id=task_context.get("task_id"),
            failed_agents=failed_agents,
            layer="service",
        )

        prompt = self._build_gap_detection_prompt(
            task_context, failed_agents, failure_reasons
        )

        try:
            raw = await self._llm.complete_json(prompt)
        except Exception as exc:
            logger.error(
                "gap_detection_llm_error",
                trace_id=trace_id,
                error=str(exc),
                layer="service",
            )
            raise

        result = self._parse_gap_response(raw, trace_id)

        GAPS_DETECTED_TOTAL.inc()
        logger.info(
            "gap_detection_completed",
            trace_id=trace_id,
            gap_description=result["gap_description"],
            suggested_type=result["suggested_capability_type"],
            confidence=result["confidence"],
            layer="service",
        )
        return result
