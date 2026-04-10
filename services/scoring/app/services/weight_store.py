"""
WeightStore — loads and saves scoring weights from MySQL.

Weight loading priority (highest to lowest):
  1. AGENT scope  → scope_type='AGENT',     scope_id=str(agent_id)
  2. TASK_TYPE    → scope_type='TASK_TYPE', scope_id=context_type
  3. GLOBAL       → scope_type='GLOBAL',    scope_id=NULL

If no weights exist at all, a safe default set is returned and persisted so
subsequent calls converge on real data quickly.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from app.adapters.mysql_adapter import MySQLAdapter
from app.utils.logger import StructuredLogger

logger = StructuredLogger(layer="service")

# Safe defaults — used ONLY when the DB has no rows at all.
# These are seeded into the GLOBAL scope on first use so the system can boot
# without a manual DB seed step.
_SAFE_DEFAULTS: Dict[str, float] = {
    "w1_relevance": 0.25,
    "w2_accuracy": 0.25,
    "w3_tool_success": 0.15,
    "w4_latency": 0.15,
    "w5_memory_utilization": 0.10,
    "w6_validation": 0.10,
}

REQUIRED_WEIGHT_NAMES = list(_SAFE_DEFAULTS.keys())


class WeightStore:
    def __init__(self, mysql: MySQLAdapter) -> None:
        self._db = mysql

    # ── Public interface ───────────────────────────────────────────────────────

    async def get_weights(self, agent_id: int, context_type: str) -> Dict[str, float]:
        """
        Load weights with 3-level priority fallback.
        Returns a complete weight dict (all 6 keys guaranteed).
        """
        # 1. Agent-specific weights
        weights = await self._db.fetch_weights("AGENT", str(agent_id))
        if self._is_complete(weights):
            logger.debug(
                "Loaded AGENT-scope weights",
                agent_id=agent_id,
                context_type=context_type,
            )
            return weights  # type: ignore[return-value]

        # 2. Task-type weights
        weights = await self._db.fetch_weights("TASK_TYPE", context_type)
        if self._is_complete(weights):
            logger.debug(
                "Loaded TASK_TYPE-scope weights",
                agent_id=agent_id,
                context_type=context_type,
            )
            return weights  # type: ignore[return-value]

        # 3. Global weights
        weights = await self._db.fetch_weights("GLOBAL", None)
        if self._is_complete(weights):
            logger.debug(
                "Loaded GLOBAL-scope weights",
                agent_id=agent_id,
                context_type=context_type,
            )
            return weights  # type: ignore[return-value]

        # 4. No weights in DB at all — seed GLOBAL with safe defaults
        logger.warning(
            "No weights found in DB — seeding safe defaults",
            agent_id=agent_id,
            context_type=context_type,
        )
        await self._seed_global_defaults()
        return dict(_SAFE_DEFAULTS)

    async def update_weight(
        self,
        agent_id: int,
        context_type: str,
        weight_name: str,
        new_value: float,
    ) -> None:
        """Upsert a single weight for the AGENT scope."""
        clamped = max(0.0, min(1.0, new_value))
        await self._db.upsert_weight("AGENT", str(agent_id), weight_name, clamped)
        logger.info(
            "Weight updated",
            agent_id=agent_id,
            context_type=context_type,
            weight_name=weight_name,
            new_value=clamped,
        )

    async def update_weights(
        self,
        agent_id: int,
        context_type: str,
        weights: Dict[str, float],
    ) -> None:
        """Upsert all weights for the AGENT scope in one operation."""
        for name, value in weights.items():
            await self.update_weight(agent_id, context_type, name, value)

    async def get_all_weights(self, agent_id: int) -> Dict[str, float]:
        """Return agent-scope weights (falling back to global if absent)."""
        weights = await self._db.fetch_weights("AGENT", str(agent_id))
        if weights:
            return weights
        weights = await self._db.fetch_weights("GLOBAL", None)
        if weights:
            return weights
        return dict(_SAFE_DEFAULTS)

    async def get_all_context_types(self, agent_id: int) -> List[str]:
        return await self._db.fetch_all_context_types(agent_id)

    # ── Private helpers ────────────────────────────────────────────────────────

    def _is_complete(self, weights: Optional[Dict[str, float]]) -> bool:
        if not weights:
            return False
        return all(k in weights for k in REQUIRED_WEIGHT_NAMES)

    async def _seed_global_defaults(self) -> None:
        for name, value in _SAFE_DEFAULTS.items():
            await self._db.upsert_weight("GLOBAL", None, name, value)
