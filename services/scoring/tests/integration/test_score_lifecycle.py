"""
Integration tests for the scoring service lifecycle.

Full flow with mocked MySQL + Redis adapters:
  1. POST /v1/scoring/evaluate -> score computed and persisted
  2. POST /v1/scoring/feedback -> published to scoring:feedback stream
  3. GET /v1/scoring/weights/{agent_id} -> returns weights

Uses FastAPI TestClient with app state overridden to use mocks.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.adapters.mysql_adapter import MySQLAdapter
from app.adapters.redis_adapter import RedisAdapter
from app.main import create_app
from app.services.band_engine import BandEngine
from app.services.rl_engine import RLEngine
from app.services.score_engine import ScoreEngine
from app.services.weight_store import WeightStore
from tests.conftest import DEFAULT_WEIGHTS


@pytest.fixture
def mock_mysql() -> AsyncMock:
    mysql = AsyncMock(spec=MySQLAdapter)
    mysql.fetch_weights = AsyncMock(return_value=None)
    mysql.upsert_weight = AsyncMock()
    mysql.insert_score = AsyncMock()
    mysql.fetch_recent_scores = AsyncMock(return_value=[0.7, 0.8, 0.75, 0.72, 0.78])
    mysql.fetch_all_context_types = AsyncMock(return_value=["general", "code_review"])
    mysql.insert_rl_log = AsyncMock()
    return mysql


@pytest.fixture
def mock_redis() -> AsyncMock:
    redis = AsyncMock(spec=RedisAdapter)
    redis.publish_feedback = AsyncMock(return_value="msg-123")
    redis.ensure_consumer_group = AsyncMock()
    redis.read_group = AsyncMock(return_value=[])
    redis.ack = AsyncMock()
    redis.ping = AsyncMock(return_value=True)
    redis.close = AsyncMock()
    return redis


@pytest.fixture
def mock_weight_store(mock_mysql: AsyncMock) -> WeightStore:
    """A real WeightStore wired to the mock MySQL adapter."""
    ws = AsyncMock(spec=WeightStore)
    ws.get_weights = AsyncMock(return_value=dict(DEFAULT_WEIGHTS))
    ws.update_weights = AsyncMock()
    ws.update_weight = AsyncMock()
    ws.get_all_weights = AsyncMock(return_value=dict(DEFAULT_WEIGHTS))
    ws.get_all_context_types = AsyncMock(return_value=["general", "code_review"])
    return ws


@pytest.fixture
def test_app(
    mock_mysql: AsyncMock,
    mock_redis: AsyncMock,
    mock_weight_store: AsyncMock,
):
    """Create a FastAPI app with mocked dependencies injected into state."""
    from fastapi import FastAPI
    from prometheus_client import make_asgi_app
    from app.routes.health import router as health_router
    from app.routes.scoring import router as scoring_router

    app = FastAPI()
    app.include_router(health_router)
    app.include_router(scoring_router)
    metrics_app = make_asgi_app()
    app.mount("/metrics", metrics_app)

    score_engine = ScoreEngine(mock_weight_store)
    band_engine = BandEngine(mock_mysql)
    rl_engine = RLEngine(mock_mysql, mock_redis, mock_weight_store)

    app.state.mysql = mock_mysql
    app.state.redis = mock_redis
    app.state.weight_store = mock_weight_store
    app.state.score_engine = score_engine
    app.state.band_engine = band_engine
    app.state.rl_engine = rl_engine

    return app


@pytest.mark.asyncio
async def test_evaluate_endpoint(test_app, mock_mysql: AsyncMock):
    """POST /v1/scoring/evaluate computes a score and persists it."""
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/scoring/evaluate",
            json={
                "agent_id": 1,
                "task_id": "task-001",
                "context_type": "general",
                "response_text": "The answer is 42.",
                "used_knowledge": True,
                "latency_ms": 500,
                "tool_calls": [],
            },
        )

    assert response.status_code == 200
    data = response.json()

    assert "score" in data
    assert 0.0 <= data["score"] <= 1.0
    assert "band" in data
    assert "recommendation" in data
    assert data["recommendation"] in ["proceed", "course_correct", "escalate", "halt"]
    assert "factors" in data
    assert "weights_used" in data
    assert "trace_id" in data

    # Score was persisted to MySQL
    mock_mysql.insert_score.assert_awaited_once()


@pytest.mark.asyncio
async def test_evaluate_with_explicit_factors(test_app, mock_mysql: AsyncMock):
    """POST /v1/scoring/evaluate with explicit factors uses them directly."""
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/scoring/evaluate",
            json={
                "agent_id": 1,
                "task_id": "task-002",
                "context_type": "general",
                "response_text": "Some response",
                "used_knowledge": False,
                "latency_ms": 100,
                "tool_calls": [],
                "factors": {
                    "relevance": 1.0,
                    "accuracy": 1.0,
                    "tool_success": 1.0,
                    "latency_penalty": 1.0,
                    "memory_utilization": 1.0,
                    "validation_pass": 1.0,
                },
            },
        )

    assert response.status_code == 200
    data = response.json()
    expected_score = sum(DEFAULT_WEIGHTS.values())
    assert data["score"] == pytest.approx(expected_score, abs=1e-3)


@pytest.mark.asyncio
async def test_feedback_endpoint(test_app, mock_redis: AsyncMock):
    """POST /v1/scoring/feedback publishes to the scoring:feedback stream."""
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/scoring/feedback",
            json={
                "agent_id": 1,
                "task_id": "task-001",
                "session_id": "sess-001",
                "feedback_source": "USER",
                "feedback_type": "SCORE",
                "score": 0.85,
                "reward_signal": 0.9,
                "context_type": "general",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["accepted"] is True
    assert "trace_id" in data

    # Feedback was published to Redis stream
    mock_redis.publish_feedback.assert_awaited_once()


@pytest.mark.asyncio
async def test_weights_endpoint(test_app, mock_weight_store: AsyncMock):
    """GET /v1/scoring/weights/{agent_id} returns the current weights."""
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as client:
        response = await client.get("/v1/scoring/weights/1")

    assert response.status_code == 200
    data = response.json()
    assert data["agent_id"] == 1
    assert "weights" in data
    assert len(data["weights"]) == 6
    assert "context_types" in data

    mock_weight_store.get_all_weights.assert_awaited_once_with(1)
    mock_weight_store.get_all_context_types.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_band_endpoint(test_app, mock_mysql: AsyncMock):
    """POST /v1/scoring/band returns the adaptive band."""
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/scoring/band",
            json={
                "agent_id": 1,
                "context_type": "general",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert "low" in data
    assert "high" in data
    assert "mean" in data
    assert "std" in data
    assert "n" in data
    assert data["low"] >= 0.0
    assert data["high"] <= 1.0


@pytest.mark.asyncio
async def test_health_endpoint(test_app):
    """GET /health returns service status."""
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "scoring"
    assert data["status"] in ["ok", "degraded"]


@pytest.mark.asyncio
async def test_full_lifecycle(test_app, mock_mysql: AsyncMock, mock_redis: AsyncMock):
    """Full lifecycle: evaluate -> feedback -> check weights."""
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as client:
        # Step 1: Evaluate
        eval_resp = await client.post(
            "/v1/scoring/evaluate",
            json={
                "agent_id": 10,
                "task_id": "task-lifecycle",
                "context_type": "qa",
                "response_text": "Answer to the question.",
                "used_knowledge": True,
                "latency_ms": 1200,
                "tool_calls": ["search"],
            },
        )
        assert eval_resp.status_code == 200
        eval_data = eval_resp.json()
        score = eval_data["score"]

        # Step 2: Submit feedback based on the score
        fb_resp = await client.post(
            "/v1/scoring/feedback",
            json={
                "agent_id": 10,
                "task_id": "task-lifecycle",
                "session_id": "sess-lifecycle",
                "feedback_source": "AUTOMATED",
                "feedback_type": "SCORE",
                "score": score,
                "reward_signal": 0.9,
                "context_type": "qa",
            },
        )
        assert fb_resp.status_code == 200
        assert fb_resp.json()["accepted"] is True

        # Step 3: Fetch weights
        weights_resp = await client.get("/v1/scoring/weights/10")
        assert weights_resp.status_code == 200
        weights_data = weights_resp.json()
        assert weights_data["agent_id"] == 10
        assert len(weights_data["weights"]) == 6
