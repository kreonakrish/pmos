"""
Shared test fixtures for the scoring service.

All fixtures use mocks — no real DB, Redis, or LLM connections.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from app.adapters.mysql_adapter import MySQLAdapter
from app.adapters.redis_adapter import RedisAdapter
from app.services.band_engine import BandEngine
from app.services.rl_engine import RLEngine
from app.services.score_engine import ScoreEngine
from app.services.weight_store import WeightStore


# ── Default weight vectors used across tests ─────────────────────────────────

DEFAULT_WEIGHTS: Dict[str, float] = {
    "w1_relevance": 0.25,
    "w2_accuracy": 0.25,
    "w3_tool_success": 0.15,
    "w4_latency": 0.15,
    "w5_memory_utilization": 0.10,
    "w6_validation": 0.10,
}

EQUAL_WEIGHTS: Dict[str, float] = {
    "w1_relevance": 1.0 / 6,
    "w2_accuracy": 1.0 / 6,
    "w3_tool_success": 1.0 / 6,
    "w4_latency": 1.0 / 6,
    "w5_memory_utilization": 1.0 / 6,
    "w6_validation": 1.0 / 6,
}

ALL_FACTORS_ONE: Dict[str, float] = {
    "relevance": 1.0,
    "accuracy": 1.0,
    "tool_success": 1.0,
    "latency_penalty": 1.0,
    "memory_utilization": 1.0,
    "validation_pass": 1.0,
}

ALL_FACTORS_ZERO: Dict[str, float] = {
    "relevance": 0.0,
    "accuracy": 0.0,
    "tool_success": 0.0,
    "latency_penalty": 0.0,
    "memory_utilization": 0.0,
    "validation_pass": 0.0,
}


# ── Mock adapters ────────────────────────────────────────────────────────────

@pytest.fixture
def mock_mysql() -> AsyncMock:
    """Mock MySQLAdapter with all async methods stubbed."""
    mysql = AsyncMock(spec=MySQLAdapter)
    mysql.fetch_weights = AsyncMock(return_value=None)
    mysql.upsert_weight = AsyncMock()
    mysql.insert_score = AsyncMock()
    mysql.fetch_recent_scores = AsyncMock(return_value=[])
    mysql.fetch_all_context_types = AsyncMock(return_value=[])
    mysql.insert_rl_log = AsyncMock()
    return mysql


@pytest.fixture
def mock_redis() -> AsyncMock:
    """Mock RedisAdapter with all async methods stubbed."""
    redis = AsyncMock(spec=RedisAdapter)
    redis.publish_feedback = AsyncMock(return_value="mock-msg-id")
    redis.ensure_consumer_group = AsyncMock()
    redis.read_group = AsyncMock(return_value=[])
    redis.ack = AsyncMock()
    redis.ping = AsyncMock(return_value=True)
    redis.close = AsyncMock()
    return redis


@pytest.fixture
def mock_weight_store() -> AsyncMock:
    """Mock WeightStore that returns DEFAULT_WEIGHTS by default."""
    ws = AsyncMock(spec=WeightStore)
    ws.get_weights = AsyncMock(return_value=dict(DEFAULT_WEIGHTS))
    ws.update_weights = AsyncMock()
    ws.update_weight = AsyncMock()
    ws.get_all_weights = AsyncMock(return_value=dict(DEFAULT_WEIGHTS))
    ws.get_all_context_types = AsyncMock(return_value=["general"])
    return ws


# ── Service instances wired to mocks ─────────────────────────────────────────

@pytest.fixture
def score_engine(mock_weight_store: AsyncMock) -> ScoreEngine:
    return ScoreEngine(mock_weight_store)


@pytest.fixture
def band_engine(mock_mysql: AsyncMock) -> BandEngine:
    return BandEngine(mock_mysql)


@pytest.fixture
def rl_engine(
    mock_mysql: AsyncMock,
    mock_redis: AsyncMock,
    mock_weight_store: AsyncMock,
) -> RLEngine:
    return RLEngine(mock_mysql, mock_redis, mock_weight_store)
