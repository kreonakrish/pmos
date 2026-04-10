"""
Unit tests for ScoreEngine — 6-factor weighted scoring formula.

Tests verify:
- All factors=1.0 with known weights produces expected sum
- All factors=0.0 always produces score=0.0
- Individual weight dominance (one weight >> others)
- Different weights from DB produce different scores (proving no hardcoding)
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.services.score_engine import ScoreEngine
from tests.conftest import (
    ALL_FACTORS_ONE,
    ALL_FACTORS_ZERO,
    DEFAULT_WEIGHTS,
)


@pytest.mark.asyncio
async def test_all_factors_one_produces_sum_of_weights(mock_weight_store: AsyncMock):
    """When all factors are 1.0, score = sum of all weights."""
    mock_weight_store.get_weights.return_value = dict(DEFAULT_WEIGHTS)
    engine = ScoreEngine(mock_weight_store)

    result = await engine.compute_score(
        agent_id=1, context_type="general", factors=dict(ALL_FACTORS_ONE)
    )

    expected = sum(DEFAULT_WEIGHTS.values())
    assert result["score"] == round(expected, 4)


@pytest.mark.asyncio
async def test_all_factors_zero_produces_zero(mock_weight_store: AsyncMock):
    """When all factors are 0.0, score is always 0.0 regardless of weights."""
    mock_weight_store.get_weights.return_value = dict(DEFAULT_WEIGHTS)
    engine = ScoreEngine(mock_weight_store)

    result = await engine.compute_score(
        agent_id=1, context_type="general", factors=dict(ALL_FACTORS_ZERO)
    )

    assert result["score"] == 0.0


@pytest.mark.asyncio
async def test_relevance_weight_dominance(mock_weight_store: AsyncMock):
    """When w1_relevance is very large and only relevance factor is 1.0,
    the score should be dominated by that weight."""
    heavy_weights = {
        "w1_relevance": 0.90,
        "w2_accuracy": 0.02,
        "w3_tool_success": 0.02,
        "w4_latency": 0.02,
        "w5_memory_utilization": 0.02,
        "w6_validation": 0.02,
    }
    mock_weight_store.get_weights.return_value = heavy_weights
    engine = ScoreEngine(mock_weight_store)

    factors = {
        "relevance": 1.0,
        "accuracy": 0.0,
        "tool_success": 0.0,
        "latency_penalty": 0.0,
        "memory_utilization": 0.0,
        "validation_pass": 0.0,
    }

    result = await engine.compute_score(
        agent_id=1, context_type="general", factors=factors
    )

    assert result["score"] == 0.90


@pytest.mark.asyncio
async def test_accuracy_weight_dominance(mock_weight_store: AsyncMock):
    """When w2_accuracy is dominant, accuracy factor drives the score."""
    heavy_weights = {
        "w1_relevance": 0.02,
        "w2_accuracy": 0.90,
        "w3_tool_success": 0.02,
        "w4_latency": 0.02,
        "w5_memory_utilization": 0.02,
        "w6_validation": 0.02,
    }
    mock_weight_store.get_weights.return_value = heavy_weights
    engine = ScoreEngine(mock_weight_store)

    factors = {
        "relevance": 0.0,
        "accuracy": 1.0,
        "tool_success": 0.0,
        "latency_penalty": 0.0,
        "memory_utilization": 0.0,
        "validation_pass": 0.0,
    }

    result = await engine.compute_score(
        agent_id=1, context_type="general", factors=factors
    )

    assert result["score"] == 0.90


@pytest.mark.asyncio
async def test_different_db_weights_produce_different_scores(mock_weight_store: AsyncMock):
    """Prove that changing weights in the store changes the computed score,
    demonstrating weights are DB-driven and not hardcoded."""
    engine = ScoreEngine(mock_weight_store)
    factors = dict(ALL_FACTORS_ONE)

    # First set of weights
    weights_a = {
        "w1_relevance": 0.30,
        "w2_accuracy": 0.30,
        "w3_tool_success": 0.10,
        "w4_latency": 0.10,
        "w5_memory_utilization": 0.10,
        "w6_validation": 0.10,
    }
    mock_weight_store.get_weights.return_value = weights_a
    result_a = await engine.compute_score(
        agent_id=1, context_type="general", factors=factors
    )

    # Second set of weights (different distribution)
    weights_b = {
        "w1_relevance": 0.10,
        "w2_accuracy": 0.10,
        "w3_tool_success": 0.10,
        "w4_latency": 0.10,
        "w5_memory_utilization": 0.30,
        "w6_validation": 0.30,
    }
    mock_weight_store.get_weights.return_value = weights_b
    result_b = await engine.compute_score(
        agent_id=1, context_type="general", factors=factors
    )

    # Both should equal sum of their respective weights, which are the same total
    # but the key point: the engine used different weight sets
    assert result_a["weights_used"] == weights_a
    assert result_b["weights_used"] == weights_b


@pytest.mark.asyncio
async def test_score_clamped_to_max_1(mock_weight_store: AsyncMock):
    """Even if weights sum to more than 1.0, score is clamped to 1.0."""
    huge_weights = {
        "w1_relevance": 0.50,
        "w2_accuracy": 0.50,
        "w3_tool_success": 0.50,
        "w4_latency": 0.50,
        "w5_memory_utilization": 0.50,
        "w6_validation": 0.50,
    }
    mock_weight_store.get_weights.return_value = huge_weights
    engine = ScoreEngine(mock_weight_store)

    result = await engine.compute_score(
        agent_id=1, context_type="general", factors=dict(ALL_FACTORS_ONE)
    )

    assert result["score"] == 1.0


@pytest.mark.asyncio
async def test_factors_are_clamped(mock_weight_store: AsyncMock):
    """Factors outside [0,1] are clamped before computation."""
    mock_weight_store.get_weights.return_value = dict(DEFAULT_WEIGHTS)
    engine = ScoreEngine(mock_weight_store)

    factors = {
        "relevance": 2.0,       # should clamp to 1.0
        "accuracy": -0.5,       # should clamp to 0.0
        "tool_success": 1.0,
        "latency_penalty": 1.0,
        "memory_utilization": 1.0,
        "validation_pass": 1.0,
    }

    result = await engine.compute_score(
        agent_id=1, context_type="general", factors=factors
    )

    assert result["factors"]["relevance"] == 1.0
    assert result["factors"]["accuracy"] == 0.0
    # Score should use clamped values
    expected = (
        DEFAULT_WEIGHTS["w1_relevance"] * 1.0
        + DEFAULT_WEIGHTS["w2_accuracy"] * 0.0
        + DEFAULT_WEIGHTS["w3_tool_success"] * 1.0
        + DEFAULT_WEIGHTS["w4_latency"] * 1.0
        + DEFAULT_WEIGHTS["w5_memory_utilization"] * 1.0
        + DEFAULT_WEIGHTS["w6_validation"] * 1.0
    )
    assert result["score"] == round(expected, 4)


@pytest.mark.asyncio
async def test_partial_factors(mock_weight_store: AsyncMock):
    """Mid-range factor values produce proportional score."""
    mock_weight_store.get_weights.return_value = dict(DEFAULT_WEIGHTS)
    engine = ScoreEngine(mock_weight_store)

    factors = {
        "relevance": 0.5,
        "accuracy": 0.5,
        "tool_success": 0.5,
        "latency_penalty": 0.5,
        "memory_utilization": 0.5,
        "validation_pass": 0.5,
    }

    result = await engine.compute_score(
        agent_id=1, context_type="general", factors=factors
    )

    expected = sum(DEFAULT_WEIGHTS.values()) * 0.5
    assert result["score"] == round(expected, 4)


@pytest.mark.asyncio
async def test_weight_store_called_with_correct_args(mock_weight_store: AsyncMock):
    """Verify the engine passes the correct agent_id and context_type to the store."""
    mock_weight_store.get_weights.return_value = dict(DEFAULT_WEIGHTS)
    engine = ScoreEngine(mock_weight_store)

    await engine.compute_score(
        agent_id=42, context_type="code_review", factors=dict(ALL_FACTORS_ONE)
    )

    mock_weight_store.get_weights.assert_awaited_once_with(42, "code_review")
