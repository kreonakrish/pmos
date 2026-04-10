"""
ScoreEngine — 6-factor weighted scoring formula.

Formula:
    S = w1·R + w2·Acc + w3·P + w4·Lat + w5·Conf + w6·Know

Where:
    w1 = w1_relevance          — how relevant the response is to the task
    w2 = w2_accuracy           — output quality / correctness
    w3 = w3_tool_success       — fraction of tool calls that succeeded
    w4 = w4_latency            — latency penalty (1 - actual/max)
    w5 = w5_memory_utilization — whether the agent leveraged its memories
    w6 = w6_validation         — did output pass validation step

CRITICAL: weights are ALWAYS loaded from MySQL scoring_weights table.
          No weight value is ever hardcoded in this file.
"""
from __future__ import annotations

from typing import Dict

from app.services.weight_store import WeightStore
from app.utils.logger import StructuredLogger

logger = StructuredLogger(layer="service")

# Sentinel used to clamp individual factor values to the valid domain.
_FACTOR_MIN = 0.0
_FACTOR_MAX = 1.0


class ScoreEngine:
    def __init__(self, weight_store: WeightStore) -> None:
        self._weight_store = weight_store

    async def compute_score(
        self,
        agent_id: int,
        context_type: str,
        factors: Dict[str, float],
        trace_id: str = "",
    ) -> Dict:
        """
        Compute a weighted score for one execution result.

        Parameters
        ----------
        agent_id : int
        context_type : str
        factors : dict with keys:
            relevance, accuracy, tool_success, latency_penalty,
            memory_utilization, validation_pass
        trace_id : str

        Returns
        -------
        {
            "score": float,            # 0.0 – 1.0
            "factors": dict,           # clamped factor values
            "weights_used": dict,      # weights loaded from DB
        }
        """
        # Clamp every factor to [0, 1] to protect against caller mistakes
        clamped = {
            k: max(_FACTOR_MIN, min(_FACTOR_MAX, float(v)))
            for k, v in factors.items()
        }

        weights = await self._weight_store.get_weights(agent_id, context_type)

        score = (
            weights["w1_relevance"] * clamped["relevance"]
            + weights["w2_accuracy"] * clamped["accuracy"]
            + weights["w3_tool_success"] * clamped["tool_success"]
            + weights["w4_latency"] * clamped["latency_penalty"]
            + weights["w5_memory_utilization"] * clamped["memory_utilization"]
            + weights["w6_validation"] * clamped["validation_pass"]
        )
        score = round(max(0.0, min(1.0, score)), 4)

        logger.info(
            "Score computed",
            agent_id=agent_id,
            context_type=context_type,
            score=score,
            trace_id=trace_id,
        )

        return {
            "score": score,
            "factors": clamped,
            "weights_used": weights,
        }

    def derive_factors_from_request(
        self,
        response_text: str,
        used_knowledge: bool,
        latency_ms: int,
        tool_calls: list,
    ) -> Dict[str, float]:
        """
        Derive best-effort factors when the caller does not supply explicit ones.

        This is a heuristic layer — in production, accuracy and relevance
        would come from an LLM judge call.  We return neutral mid-point values
        for factors that require LLM evaluation, and compute what we can from
        the structured fields.
        """
        # Tool success: unknown without actual results — optimistic mid-point
        tool_success = 0.5 if tool_calls else 1.0

        # Latency penalty: full credit if under 2 s; degrades linearly up to 30 s
        max_latency_ms = 30_000
        latency_penalty = max(0.0, 1.0 - (latency_ms / max_latency_ms))

        # Memory utilization: binary from used_knowledge flag
        memory_utilization = 1.0 if used_knowledge else 0.0

        # Validation: default to pass when response is non-empty
        validation_pass = 1.0 if response_text and response_text.strip() else 0.0

        # Relevance + accuracy require LLM judge — return neutral until integrated
        relevance = 0.5
        accuracy = 0.5

        return {
            "relevance": relevance,
            "accuracy": accuracy,
            "tool_success": tool_success,
            "latency_penalty": round(latency_penalty, 4),
            "memory_utilization": memory_utilization,
            "validation_pass": validation_pass,
        }
