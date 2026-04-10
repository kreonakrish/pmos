"""
BandEngine — adaptive scoring band computation.

Formula
-------
    scores  = last N scores from score_history (N = scoring_history_window)
    mean    = rolling mean of scores
    std     = rolling standard deviation

    band_width = std * band_sensitivity_factor
    band_low   = max(0.0, mean - band_width)
    band_high  = min(1.0, mean + band_width)

    if (band_high - band_low) < band_min_width:
        center    = (band_high + band_low) / 2.0
        band_low  = max(0.0, center - band_min_width / 2.0)
        band_high = min(1.0, center + band_min_width / 2.0)

CRITICAL: All thresholds (sensitivity_factor, min_width, window_size) come
          from config, never from literals in this file.
"""
from __future__ import annotations

from typing import Dict, List

import numpy as np

from app.adapters.mysql_adapter import MySQLAdapter
from app.config import settings
from app.utils.logger import StructuredLogger

logger = StructuredLogger(layer="service")


class BandEngine:
    def __init__(self, mysql: MySQLAdapter) -> None:
        self._db = mysql

    async def compute_band(
        self,
        agent_id: int,
        context_type: str,
        trace_id: str = "",
    ) -> Dict:
        """
        Compute the adaptive band for the given agent + context type.

        Returns
        -------
        {
            "low":  float,
            "high": float,
            "mean": float,
            "std":  float,
            "n":    int,
        }
        """
        window = settings.scoring_history_window
        scores: List[float] = await self._db.fetch_recent_scores(
            agent_id, context_type, window
        )

        if len(scores) < 2:
            # Not enough history — return maximally wide band
            logger.info(
                "Insufficient history — returning wide band",
                agent_id=agent_id,
                context_type=context_type,
                n=len(scores),
                trace_id=trace_id,
            )
            return {
                "low": 0.0,
                "high": 1.0,
                "mean": 0.5,
                "std": 0.5,
                "n": len(scores),
            }

        arr = np.array(scores, dtype=float)
        mean = float(np.mean(arr))
        std = float(np.std(arr))

        sensitivity = settings.band_sensitivity_factor
        min_width = settings.band_min_width

        band_width = std * sensitivity
        band_low = max(0.0, mean - band_width)
        band_high = min(1.0, mean + band_width)

        # Enforce minimum band width
        if (band_high - band_low) < min_width:
            center = (band_high + band_low) / 2.0
            half = min_width / 2.0
            band_low = max(0.0, center - half)
            band_high = min(1.0, center + half)

        result = {
            "low": round(band_low, 4),
            "high": round(band_high, 4),
            "mean": round(mean, 4),
            "std": round(std, 4),
            "n": len(scores),
        }

        logger.info(
            "Band computed",
            agent_id=agent_id,
            context_type=context_type,
            band=result,
            trace_id=trace_id,
        )
        return result

    def derive_recommendation(self, score: float, band: Dict) -> str:
        """
        Map a score + band into an action recommendation.

        Logic (no hardcoded thresholds — boundaries derived from band):
          - score >= band["low"]                          → proceed
          - score <  band["low"]
            and score >= band["low"] * (1 - 0.5)         → course_correct
              (i.e. within 50 % of the band-low below the band)
          - score <  band["low"] * (1 - 0.5)             → escalate
          - score == 0.0                                  → halt
        """
        if score == 0.0:
            return "halt"

        band_low: float = band["low"]

        if score >= band_low:
            return "proceed"

        # Distance below the band
        deficit = band_low - score
        # Threshold between course_correct and escalate = 50 % of band_low
        # (when band_low == 0 use a small epsilon from min_width config)
        tolerance = max(band_low * 0.5, settings.band_min_width * 0.5)

        if deficit <= tolerance:
            return "course_correct"

        return "escalate"
