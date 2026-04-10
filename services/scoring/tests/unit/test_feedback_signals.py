"""
Unit tests for feedback signal processing — all 4 signal types.

Tests verify:
- AUTOMATED, USER, INTER_AGENT, ORCHESTRATOR each use the correct weight multiplier
- rl_feedback_log is written for each signal type
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.rl_engine import RLEngine
from tests.conftest import DEFAULT_WEIGHTS


FEEDBACK_WEIGHTS = {
    "automated": 0.4,
    "user": 0.3,
    "inter_agent": 0.2,
    "orchestrator": 0.1,
}


def _make_feedback(source: str) -> dict:
    return {
        "agent_id": 1,
        "feedback_source": source,
        "feedback_type": "SCORE",
        "score": 0.8,
        "reward_signal": 1.0,
        "context_type": "general",
    }


@pytest.mark.asyncio
async def test_automated_feedback_weight(
    mock_mysql: AsyncMock,
    mock_redis: AsyncMock,
    mock_weight_store: AsyncMock,
):
    """AUTOMATED feedback uses source weight 0.4."""
    mock_weight_store.get_weights.return_value = dict(DEFAULT_WEIGHTS)
    engine = RLEngine(mock_mysql, mock_redis, mock_weight_store)

    with patch("app.services.rl_engine.settings") as mock_settings:
        mock_settings.rl_learning_rate = 0.1
        mock_settings.rl_feedback_weights_dict = FEEDBACK_WEIGHTS

        await engine.process_feedback(_make_feedback("AUTOMATED"))

    call_kwargs = mock_mysql.insert_rl_log.call_args[1]
    # effective_reward = 1.0 * 0.4 = 0.4
    assert call_kwargs["effective_reward"] == pytest.approx(0.4, abs=1e-6)
    assert call_kwargs["feedback_source"] == "AUTOMATED"


@pytest.mark.asyncio
async def test_user_feedback_weight(
    mock_mysql: AsyncMock,
    mock_redis: AsyncMock,
    mock_weight_store: AsyncMock,
):
    """USER feedback uses source weight 0.3."""
    mock_weight_store.get_weights.return_value = dict(DEFAULT_WEIGHTS)
    engine = RLEngine(mock_mysql, mock_redis, mock_weight_store)

    with patch("app.services.rl_engine.settings") as mock_settings:
        mock_settings.rl_learning_rate = 0.1
        mock_settings.rl_feedback_weights_dict = FEEDBACK_WEIGHTS

        await engine.process_feedback(_make_feedback("USER"))

    call_kwargs = mock_mysql.insert_rl_log.call_args[1]
    assert call_kwargs["effective_reward"] == pytest.approx(0.3, abs=1e-6)
    assert call_kwargs["feedback_source"] == "USER"


@pytest.mark.asyncio
async def test_inter_agent_feedback_weight(
    mock_mysql: AsyncMock,
    mock_redis: AsyncMock,
    mock_weight_store: AsyncMock,
):
    """INTER_AGENT feedback uses source weight 0.2."""
    mock_weight_store.get_weights.return_value = dict(DEFAULT_WEIGHTS)
    engine = RLEngine(mock_mysql, mock_redis, mock_weight_store)

    with patch("app.services.rl_engine.settings") as mock_settings:
        mock_settings.rl_learning_rate = 0.1
        mock_settings.rl_feedback_weights_dict = FEEDBACK_WEIGHTS

        await engine.process_feedback(_make_feedback("INTER_AGENT"))

    call_kwargs = mock_mysql.insert_rl_log.call_args[1]
    assert call_kwargs["effective_reward"] == pytest.approx(0.2, abs=1e-6)
    assert call_kwargs["feedback_source"] == "INTER_AGENT"


@pytest.mark.asyncio
async def test_orchestrator_feedback_weight(
    mock_mysql: AsyncMock,
    mock_redis: AsyncMock,
    mock_weight_store: AsyncMock,
):
    """ORCHESTRATOR feedback uses source weight 0.1."""
    mock_weight_store.get_weights.return_value = dict(DEFAULT_WEIGHTS)
    engine = RLEngine(mock_mysql, mock_redis, mock_weight_store)

    with patch("app.services.rl_engine.settings") as mock_settings:
        mock_settings.rl_learning_rate = 0.1
        mock_settings.rl_feedback_weights_dict = FEEDBACK_WEIGHTS

        await engine.process_feedback(_make_feedback("ORCHESTRATOR"))

    call_kwargs = mock_mysql.insert_rl_log.call_args[1]
    assert call_kwargs["effective_reward"] == pytest.approx(0.1, abs=1e-6)
    assert call_kwargs["feedback_source"] == "ORCHESTRATOR"


@pytest.mark.asyncio
async def test_all_signal_types_write_rl_log(
    mock_mysql: AsyncMock,
    mock_redis: AsyncMock,
    mock_weight_store: AsyncMock,
):
    """Every feedback source type results in an rl_feedback_log write."""
    engine = RLEngine(mock_mysql, mock_redis, mock_weight_store)

    for source in ["AUTOMATED", "USER", "INTER_AGENT", "ORCHESTRATOR"]:
        mock_mysql.insert_rl_log.reset_mock()
        mock_weight_store.get_weights.return_value = dict(DEFAULT_WEIGHTS)

        with patch("app.services.rl_engine.settings") as mock_settings:
            mock_settings.rl_learning_rate = 0.1
            mock_settings.rl_feedback_weights_dict = FEEDBACK_WEIGHTS

            await engine.process_feedback(_make_feedback(source))

        mock_mysql.insert_rl_log.assert_awaited_once()
        call_kwargs = mock_mysql.insert_rl_log.call_args[1]
        assert call_kwargs["agent_id"] == 1
        assert call_kwargs["feedback_source"] == source
        assert "weights_before" in call_kwargs
        assert "weights_after" in call_kwargs


@pytest.mark.asyncio
async def test_different_feedback_types_accepted(
    mock_mysql: AsyncMock,
    mock_redis: AsyncMock,
    mock_weight_store: AsyncMock,
):
    """All feedback_type values (SCORE, CORRECTION, RETRY, etc.) are processed."""
    mock_weight_store.get_weights.return_value = dict(DEFAULT_WEIGHTS)
    engine = RLEngine(mock_mysql, mock_redis, mock_weight_store)

    for ftype in ["SCORE", "CORRECTION", "BAND_ADJUST", "RETRY", "FALLBACK", "AUTOCORRECT"]:
        mock_mysql.insert_rl_log.reset_mock()

        feedback = {
            "agent_id": 1,
            "feedback_source": "AUTOMATED",
            "feedback_type": ftype,
            "score": 0.7,
            "reward_signal": 0.8,
            "context_type": "general",
        }

        with patch("app.services.rl_engine.settings") as mock_settings:
            mock_settings.rl_learning_rate = 0.1
            mock_settings.rl_feedback_weights_dict = FEEDBACK_WEIGHTS

            await engine.process_feedback(feedback)

        call_kwargs = mock_mysql.insert_rl_log.call_args[1]
        assert call_kwargs["feedback_type"] == ftype
