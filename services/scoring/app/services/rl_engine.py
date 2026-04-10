"""
RLEngine — Q-learning-inspired reinforcement learning weight updater.

Formula
-------
    effective_reward = reward_signal * source_weight
    w_new = w_old + α * (effective_reward - w_old)

Where:
    α              = rl_learning_rate (from config)
    source_weight  = rl_feedback_weights[feedback_source] (from config)

The engine also runs as a long-lived background consumer of the
"scoring:feedback" Redis stream.
"""
from __future__ import annotations

import asyncio
import json
from typing import Dict, Optional

from app.adapters.mysql_adapter import MySQLAdapter
from app.adapters.redis_adapter import RedisAdapter, STREAM_SCORING_FEEDBACK
from app.config import settings
from app.services.weight_store import WeightStore
from app.utils.logger import StructuredLogger

logger = StructuredLogger(layer="service")

CONSUMER_GROUP = "rl-engine"
CONSUMER_NAME = "consumer-1"


class RLEngine:
    def __init__(
        self,
        mysql: MySQLAdapter,
        redis: RedisAdapter,
        weight_store: WeightStore,
    ) -> None:
        self._db = mysql
        self._redis = redis
        self._weight_store = weight_store
        self._running = False

    # ── Core RL update ────────────────────────────────────────────────────────

    async def process_feedback(self, feedback: Dict) -> None:
        """
        Apply one feedback signal to the agent's weights.

        feedback keys (from Redis stream or direct call):
            agent_id, feedback_source, feedback_type, score,
            reward_signal, context_type
        """
        agent_id: int = int(feedback["agent_id"])
        feedback_source: str = str(feedback["feedback_source"]).upper()
        feedback_type: str = str(feedback.get("feedback_type", "SCORE"))
        score: float = float(feedback["score"])
        reward_signal: float = float(feedback["reward_signal"])
        context_type: str = str(feedback["context_type"])

        source_weights: Dict[str, float] = settings.rl_feedback_weights_dict
        # Key mapping — normalize to lower-case keys in config dict
        source_key = feedback_source.lower()
        source_weight: float = source_weights.get(source_key, 0.1)

        effective_reward = reward_signal * source_weight
        alpha = settings.rl_learning_rate

        # Load current weights
        current_weights = await self._weight_store.get_weights(agent_id, context_type)
        weights_before = dict(current_weights)

        # Apply Q-learning update to every weight
        updated_weights: Dict[str, float] = {}
        for name, w_old in current_weights.items():
            w_new = w_old + alpha * (effective_reward - w_old)
            # Keep weights in [0, 1]
            w_new = max(0.0, min(1.0, w_new))
            updated_weights[name] = round(w_new, 6)

        # Persist updated weights
        await self._weight_store.update_weights(agent_id, context_type, updated_weights)

        # Audit log
        await self._db.insert_rl_log(
            agent_id=agent_id,
            feedback_source=feedback_source,
            feedback_type=feedback_type,
            score=score,
            reward_signal=reward_signal,
            effective_reward=effective_reward,
            context_type=context_type,
            weights_before=weights_before,
            weights_after=updated_weights,
        )

        logger.info(
            "RL weight update applied",
            agent_id=agent_id,
            context_type=context_type,
            feedback_source=feedback_source,
            effective_reward=effective_reward,
            alpha=alpha,
        )

    # ── Stream consumer ───────────────────────────────────────────────────────

    async def consume_feedback_stream(self) -> None:
        """
        Blocking background consumer of the scoring:feedback Redis stream.
        Runs for the lifetime of the service process.
        """
        logger.info(
            "RL engine starting stream consumer",
            stream=STREAM_SCORING_FEEDBACK,
            group=CONSUMER_GROUP,
            consumer=CONSUMER_NAME,
        )
        await self._redis.ensure_consumer_group(
            STREAM_SCORING_FEEDBACK, CONSUMER_GROUP, start_id="$"
        )

        self._running = True
        while self._running:
            try:
                messages = await self._redis.read_group(
                    STREAM_SCORING_FEEDBACK,
                    CONSUMER_GROUP,
                    CONSUMER_NAME,
                    count=10,
                    block_ms=1000,
                )
                for msg_id, fields in messages:
                    try:
                        data = json.loads(fields.get("data", "{}"))
                        await self.process_feedback(data)
                        await self._redis.ack(
                            STREAM_SCORING_FEEDBACK, CONSUMER_GROUP, msg_id
                        )
                    except Exception as exc:
                        logger.error(
                            "Failed to process RL feedback message",
                            msg_id=msg_id,
                            error=str(exc),
                        )
            except asyncio.CancelledError:
                logger.info("RL consumer cancelled — shutting down gracefully")
                self._running = False
                break
            except Exception as exc:
                logger.error(
                    "RL consumer encountered unexpected error",
                    error=str(exc),
                )
                # Brief pause before retry to avoid tight-loop on persistent errors
                await asyncio.sleep(2)

    def stop(self) -> None:
        self._running = False
