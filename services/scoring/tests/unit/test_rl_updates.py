"""
Unit tests for RLEngine — Q-learning-inspired weight updates.

Tests verify:
- reward > w_old results in w_new > w_old
- reward < w_old results in w_new < w_old
- learning_rate=0 leaves weights unchanged
- Different feedback sources have different effective weights
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.rl_engine import RLEngine
from tests.conftest import DEFAULT_WEIGHTS


@pytest.mark.asyncio
async def test_high_reward_increases_weights(
    mock_mysql: AsyncMock,
    mock_redis: AsyncMock,
    mock_weight_store: AsyncMock,
):
    """When reward_signal > w_old, the updated weight should increase."""
    initial_weights = dict(DEFAULT_WEIGHTS)
    mock_weight_store.get_weights.return_value = initial_weights
    engine = RLEngine(mock_mysql, mock_redis, mock_weight_store)

    feedback = {
        "agent_id": 1,
        "feedback_source": "AUTOMATED",
        "feedback_type": "SCORE",
        "score": 0.9,
        "reward_signal": 1.0,  # High reward
        "context_type": "general",
    }

    with patch("app.services.rl_engine.settings") as mock_settings:
        mock_settings.rl_learning_rate = 0.1
        mock_settings.rl_feedback_weights_dict = {
            "automated": 0.4, "user": 0.3, "inter_agent": 0.2, "orchestrator": 0.1
        }

        await engine.process_feedback(feedback)

    # Verify update_weights was called
    call_args = mock_weight_store.update_weights.call_args
    updated = call_args[0][2]  # third positional arg = weights dict

    # effective_reward = 1.0 * 0.4 = 0.4
    # For w1_relevance (0.25): w_new = 0.25 + 0.1 * (0.4 - 0.25) = 0.265
    for name, w_old in initial_weights.items():
        assert updated[name] > w_old or updated[name] == pytest.approx(w_old, abs=1e-6)


@pytest.mark.asyncio
async def test_low_reward_decreases_weights(
    mock_mysql: AsyncMock,
    mock_redis: AsyncMock,
    mock_weight_store: AsyncMock,
):
    """When reward_signal results in effective_reward < w_old, weights decrease."""
    # Set initial weights higher than the effective reward will be
    high_weights = {k: 0.80 for k in DEFAULT_WEIGHTS}
    mock_weight_store.get_weights.return_value = high_weights
    engine = RLEngine(mock_mysql, mock_redis, mock_weight_store)

    feedback = {
        "agent_id": 1,
        "feedback_source": "AUTOMATED",
        "feedback_type": "SCORE",
        "score": 0.1,
        "reward_signal": 0.1,  # Low reward
        "context_type": "general",
    }

    with patch("app.services.rl_engine.settings") as mock_settings:
        mock_settings.rl_learning_rate = 0.1
        mock_settings.rl_feedback_weights_dict = {
            "automated": 0.4, "user": 0.3, "inter_agent": 0.2, "orchestrator": 0.1
        }

        await engine.process_feedback(feedback)

    call_args = mock_weight_store.update_weights.call_args
    updated = call_args[0][2]

    # effective_reward = 0.1 * 0.4 = 0.04, which is < 0.80
    for name in high_weights:
        assert updated[name] < high_weights[name]


@pytest.mark.asyncio
async def test_zero_learning_rate_no_change(
    mock_mysql: AsyncMock,
    mock_redis: AsyncMock,
    mock_weight_store: AsyncMock,
):
    """When learning_rate=0, weights remain exactly unchanged."""
    initial_weights = dict(DEFAULT_WEIGHTS)
    mock_weight_store.get_weights.return_value = initial_weights
    engine = RLEngine(mock_mysql, mock_redis, mock_weight_store)

    feedback = {
        "agent_id": 1,
        "feedback_source": "USER",
        "feedback_type": "SCORE",
        "score": 0.9,
        "reward_signal": 1.0,
        "context_type": "general",
    }

    with patch("app.services.rl_engine.settings") as mock_settings:
        mock_settings.rl_learning_rate = 0.0  # Zero learning rate
        mock_settings.rl_feedback_weights_dict = {
            "automated": 0.4, "user": 0.3, "inter_agent": 0.2, "orchestrator": 0.1
        }

        await engine.process_feedback(feedback)

    call_args = mock_weight_store.update_weights.call_args
    updated = call_args[0][2]

    for name, w_old in initial_weights.items():
        assert updated[name] == pytest.approx(w_old, abs=1e-6)


@pytest.mark.asyncio
async def test_different_sources_different_effective_weights(
    mock_mysql: AsyncMock,
    mock_redis: AsyncMock,
    mock_weight_store: AsyncMock,
):
    """Different feedback_source values produce different effective_reward,
    thus different weight updates."""
    initial_weights = {k: 0.50 for k in DEFAULT_WEIGHTS}

    feedback_weights = {
        "automated": 0.4, "user": 0.3, "inter_agent": 0.2, "orchestrator": 0.1
    }

    results = {}
    for source in ["AUTOMATED", "USER", "INTER_AGENT", "ORCHESTRATOR"]:
        mock_weight_store.get_weights.return_value = dict(initial_weights)
        engine = RLEngine(mock_mysql, mock_redis, mock_weight_store)

        feedback = {
            "agent_id": 1,
            "feedback_source": source,
            "feedback_type": "SCORE",
            "score": 0.8,
            "reward_signal": 1.0,
            "context_type": "general",
        }

        with patch("app.services.rl_engine.settings") as mock_settings:
            mock_settings.rl_learning_rate = 0.1
            mock_settings.rl_feedback_weights_dict = feedback_weights

            await engine.process_feedback(feedback)

        call_args = mock_weight_store.update_weights.call_args
        updated = call_args[0][2]
        results[source] = updated["w1_relevance"]

    # AUTOMATED has highest source weight (0.4), so effective_reward is highest
    # Therefore AUTOMATED update should move weight the most
    assert results["AUTOMATED"] > results["USER"]
    assert results["USER"] > results["INTER_AGENT"]
    assert results["INTER_AGENT"] > results["ORCHESTRATOR"]


@pytest.mark.asyncio
async def test_rl_log_written(
    mock_mysql: AsyncMock,
    mock_redis: AsyncMock,
    mock_weight_store: AsyncMock,
):
    """Verify that insert_rl_log is called after processing feedback."""
    mock_weight_store.get_weights.return_value = dict(DEFAULT_WEIGHTS)
    engine = RLEngine(mock_mysql, mock_redis, mock_weight_store)

    feedback = {
        "agent_id": 5,
        "feedback_source": "USER",
        "feedback_type": "CORRECTION",
        "score": 0.7,
        "reward_signal": 0.8,
        "context_type": "code_review",
    }

    with patch("app.services.rl_engine.settings") as mock_settings:
        mock_settings.rl_learning_rate = 0.1
        mock_settings.rl_feedback_weights_dict = {
            "automated": 0.4, "user": 0.3, "inter_agent": 0.2, "orchestrator": 0.1
        }

        await engine.process_feedback(feedback)

    mock_mysql.insert_rl_log.assert_awaited_once()
    call_kwargs = mock_mysql.insert_rl_log.call_args[1]
    assert call_kwargs["agent_id"] == 5
    assert call_kwargs["feedback_source"] == "USER"
    assert call_kwargs["feedback_type"] == "CORRECTION"
    assert call_kwargs["context_type"] == "code_review"


@pytest.mark.asyncio
async def test_weights_clamped_to_unit_interval(
    mock_mysql: AsyncMock,
    mock_redis: AsyncMock,
    mock_weight_store: AsyncMock,
):
    """Weights should never exceed [0, 1] after RL update."""
    # Weights near 1.0 with high reward that could push beyond 1.0
    near_max = {k: 0.99 for k in DEFAULT_WEIGHTS}
    mock_weight_store.get_weights.return_value = near_max
    engine = RLEngine(mock_mysql, mock_redis, mock_weight_store)

    feedback = {
        "agent_id": 1,
        "feedback_source": "AUTOMATED",
        "feedback_type": "SCORE",
        "score": 1.0,
        "reward_signal": 1.0,
        "context_type": "general",
    }

    with patch("app.services.rl_engine.settings") as mock_settings:
        mock_settings.rl_learning_rate = 0.5  # Large learning rate
        mock_settings.rl_feedback_weights_dict = {
            "automated": 0.4, "user": 0.3, "inter_agent": 0.2, "orchestrator": 0.1
        }

        await engine.process_feedback(feedback)

    call_args = mock_weight_store.update_weights.call_args
    updated = call_args[0][2]

    for name, val in updated.items():
        assert 0.0 <= val <= 1.0, f"{name} = {val} is outside [0, 1]"
