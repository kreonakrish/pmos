"""
MySQL adapter for the scoring service.

All DB operations are async-compatible using a thread pool executor so the
FastAPI event loop is never blocked.  The connection pool is managed as a
context manager to avoid resource leaks.
"""
from __future__ import annotations

import asyncio
import json
import time
from contextlib import contextmanager
from typing import Any, Dict, Generator, List, Optional

import mysql.connector
from mysql.connector import pooling

from app.config import settings
from app.utils.logger import StructuredLogger

logger = StructuredLogger(layer="adapter")

# Global connection pool — created once at startup
_pool: Optional[pooling.MySQLConnectionPool] = None


def get_pool() -> pooling.MySQLConnectionPool:
    global _pool
    if _pool is None:
        _pool = pooling.MySQLConnectionPool(
            pool_name="scoring_pool",
            pool_size=10,
            host=settings.mysql_host,
            port=settings.mysql_port,
            database=settings.mysql_db,
            user=settings.mysql_user,
            password=settings.mysql_password,
            autocommit=True,
        )
    return _pool


@contextmanager
def get_connection() -> Generator:
    conn = get_pool().get_connection()
    try:
        yield conn
    finally:
        conn.close()


class MySQLAdapter:
    """
    Low-level MySQL operations for the scoring service.
    Every method runs in a thread-pool executor to avoid blocking the event loop.
    """

    # ── Weight table operations ───────────────────────────────────────────────

    def _fetch_weights_sync(
        self, scope_type: str, scope_id: Optional[str]
    ) -> Optional[Dict[str, float]]:
        with get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            try:
                if scope_id is None:
                    cursor.execute(
                        """
                        SELECT parameter_name, parameter_value
                        FROM scoring_weights
                        WHERE scope_type = %s AND scope_id IS NULL
                        """,
                        (scope_type,),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT parameter_name, parameter_value
                        FROM scoring_weights
                        WHERE scope_type = %s AND scope_id = %s
                        """,
                        (scope_type, scope_id),
                    )
                rows = cursor.fetchall()
                if not rows:
                    return None
                return {row["parameter_name"]: float(row["parameter_value"]) for row in rows}
            finally:
                cursor.close()

    async def fetch_weights(
        self, scope_type: str, scope_id: Optional[str]
    ) -> Optional[Dict[str, float]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._fetch_weights_sync, scope_type, scope_id
        )

    def _upsert_weight_sync(
        self,
        scope_type: str,
        scope_id: Optional[str],
        parameter_name: str,
        parameter_value: float,
    ) -> None:
        with get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO scoring_weights
                        (scope_type, scope_id, parameter_name, parameter_value, updated_at)
                    VALUES (%s, %s, %s, %s, NOW())
                    ON DUPLICATE KEY UPDATE
                        parameter_value = VALUES(parameter_value),
                        updated_at   = NOW()
                    """,
                    (scope_type, scope_id, parameter_name, parameter_value),
                )
            finally:
                cursor.close()

    async def upsert_weight(
        self,
        scope_type: str,
        scope_id: Optional[str],
        parameter_name: str,
        parameter_value: float,
    ) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            self._upsert_weight_sync,
            scope_type,
            scope_id,
            parameter_name,
            parameter_value,
        )

    # ── Score history operations ───────────────────────────────────────────────

    def _insert_score_sync(
        self,
        agent_id: int,
        task_id: str,
        context_type: str,
        score: float,
        factors: str,
    ) -> None:
        with get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO score_history
                        (agent_id, task_id, context_type, score, factors, created_at)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                    """,
                    (agent_id, task_id, context_type, score, factors),
                )
            finally:
                cursor.close()

    async def insert_score(
        self,
        agent_id: int,
        task_id: str,
        context_type: str,
        score: float,
        factors: Dict[str, float],
    ) -> None:
        factors = json.dumps(factors)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            self._insert_score_sync,
            agent_id,
            task_id,
            context_type,
            score,
            factors,
        )

    def _fetch_recent_scores_sync(
        self, agent_id: int, context_type: str, limit: int
    ) -> List[float]:
        with get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    SELECT score FROM score_history
                    WHERE agent_id = %s AND context_type = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (agent_id, context_type, limit),
                )
                rows = cursor.fetchall()
                return [float(row[0]) for row in rows]
            finally:
                cursor.close()

    async def fetch_recent_scores(
        self, agent_id: int, context_type: str, limit: int
    ) -> List[float]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._fetch_recent_scores_sync, agent_id, context_type, limit
        )

    def _fetch_score_history_sync(
        self, agent_id: int, limit: int = 50
    ) -> List[Dict[str, Any]]:
        with get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            try:
                cursor.execute(
                    """
                    SELECT agent_id, task_id, context_type, score, factors, created_at
                    FROM score_history
                    WHERE agent_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (agent_id, limit),
                )
                rows = cursor.fetchall()
                result = []
                for row in rows:
                    entry: Dict[str, Any] = {
                        "agent_id": row["agent_id"],
                        "task_id": row["task_id"],
                        "context_type": row["context_type"],
                        "score": float(row["score"]),
                        "created_at": str(row["created_at"]),
                    }
                    try:
                        entry["factors"] = json.loads(row["factors"]) if row.get("factors") else {}
                    except (json.JSONDecodeError, TypeError):
                        entry["factors"] = {}
                    result.append(entry)
                return result
            finally:
                cursor.close()

    async def get_score_history(
        self, agent_id: int, limit: int = 50
    ) -> List[Dict[str, Any]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._fetch_score_history_sync, agent_id, limit
        )

    def _fetch_all_context_types_sync(self, agent_id: int) -> List[str]:
        with get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    SELECT DISTINCT context_type FROM score_history
                    WHERE agent_id = %s
                    """,
                    (agent_id,),
                )
                rows = cursor.fetchall()
                return [row[0] for row in rows]
            finally:
                cursor.close()

    async def fetch_all_context_types(self, agent_id: int) -> List[str]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._fetch_all_context_types_sync, agent_id
        )

    # ── RL feedback log ────────────────────────────────────────────────────────

    def _insert_rl_log_sync(
        self,
        agent_id: int,
        feedback_source: str,
        feedback_type: str,
        score: float,
        reward_signal: float,
        effective_reward: float,
        context_type: str,
        weights_before: str,
        weights_after: str,
    ) -> None:
        with get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO rl_feedback_log
                        (agent_id, feedback_source, feedback_type,
                         original_score, reward_signal, feedback_payload)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        agent_id,
                        feedback_source,
                        feedback_type,
                        score,
                        reward_signal,
                        json.dumps({
                            "effective_reward": effective_reward,
                            "context_type": context_type,
                            "weights_before": json.loads(weights_before) if isinstance(weights_before, str) else weights_before,
                            "weights_after": json.loads(weights_after) if isinstance(weights_after, str) else weights_after,
                        }),
                    ),
                )
            finally:
                cursor.close()

    async def insert_rl_log(
        self,
        agent_id: int,
        feedback_source: str,
        feedback_type: str,
        score: float,
        reward_signal: float,
        effective_reward: float,
        context_type: str,
        weights_before: Dict[str, float],
        weights_after: Dict[str, float],
    ) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            self._insert_rl_log_sync,
            agent_id,
            feedback_source,
            feedback_type,
            score,
            reward_signal,
            effective_reward,
            context_type,
            json.dumps(weights_before),
            json.dumps(weights_after),
        )
