"""
Unit tests for BandEngine — adaptive scoring band computation.

Tests verify:
- 50 identical scores produce a narrow band (min_width enforced)
- High variance produces a wide band
- Fewer than 2 scores returns the default wide band (0.0, 1.0)
- min_width enforcement
- band_low never < 0.0, band_high never > 1.0
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.band_engine import BandEngine


@pytest.mark.asyncio
async def test_identical_scores_narrow_band(mock_mysql: AsyncMock):
    """50 identical scores produce std=0 and the band collapses to min_width."""
    mock_mysql.fetch_recent_scores.return_value = [0.75] * 50
    engine = BandEngine(mock_mysql)

    with patch("app.services.band_engine.settings") as mock_settings:
        mock_settings.scoring_history_window = 50
        mock_settings.band_sensitivity_factor = 1.0
        mock_settings.band_min_width = 0.05

        band = await engine.compute_band(agent_id=1, context_type="general")

    # std is ~0, so band should be enforced to min_width
    assert band["std"] == pytest.approx(0.0, abs=1e-6)
    width = band["high"] - band["low"]
    assert width == pytest.approx(0.05, abs=1e-4)
    assert band["mean"] == pytest.approx(0.75, abs=1e-4)


@pytest.mark.asyncio
async def test_high_variance_wide_band(mock_mysql: AsyncMock):
    """Alternating high/low scores produce a wide band."""
    scores = [0.1, 0.9] * 25  # 50 scores alternating between 0.1 and 0.9
    mock_mysql.fetch_recent_scores.return_value = scores
    engine = BandEngine(mock_mysql)

    with patch("app.services.band_engine.settings") as mock_settings:
        mock_settings.scoring_history_window = 50
        mock_settings.band_sensitivity_factor = 1.0
        mock_settings.band_min_width = 0.05

        band = await engine.compute_band(agent_id=1, context_type="general")

    # Mean should be ~0.5, std should be ~0.4
    assert band["mean"] == pytest.approx(0.5, abs=0.01)
    assert band["std"] > 0.3
    # Band should be significantly wider than min_width
    width = band["high"] - band["low"]
    assert width > 0.5


@pytest.mark.asyncio
async def test_fewer_than_2_scores_returns_wide_default(mock_mysql: AsyncMock):
    """With 0 or 1 score, the band should default to (0.0, 1.0)."""
    engine = BandEngine(mock_mysql)

    with patch("app.services.band_engine.settings") as mock_settings:
        mock_settings.scoring_history_window = 50

        # Zero scores
        mock_mysql.fetch_recent_scores.return_value = []
        band = await engine.compute_band(agent_id=1, context_type="general")
        assert band["low"] == 0.0
        assert band["high"] == 1.0
        assert band["n"] == 0

        # One score
        mock_mysql.fetch_recent_scores.return_value = [0.6]
        band = await engine.compute_band(agent_id=1, context_type="general")
        assert band["low"] == 0.0
        assert band["high"] == 1.0
        assert band["n"] == 1


@pytest.mark.asyncio
async def test_min_width_enforcement(mock_mysql: AsyncMock):
    """Even with very consistent scores, the band never shrinks below min_width."""
    # Scores with very tiny variance
    scores = [0.50, 0.50, 0.50, 0.501, 0.499] * 10
    mock_mysql.fetch_recent_scores.return_value = scores
    engine = BandEngine(mock_mysql)

    with patch("app.services.band_engine.settings") as mock_settings:
        mock_settings.scoring_history_window = 50
        mock_settings.band_sensitivity_factor = 1.0
        mock_settings.band_min_width = 0.10  # Larger min_width for this test

        band = await engine.compute_band(agent_id=1, context_type="general")

    width = band["high"] - band["low"]
    assert width >= 0.10 - 1e-6


@pytest.mark.asyncio
async def test_band_low_never_below_zero(mock_mysql: AsyncMock):
    """Band low is clamped to 0.0 even if mean - band_width would be negative."""
    # Very low scores with some variance
    scores = [0.01, 0.02, 0.03, 0.01, 0.02] * 10
    mock_mysql.fetch_recent_scores.return_value = scores
    engine = BandEngine(mock_mysql)

    with patch("app.services.band_engine.settings") as mock_settings:
        mock_settings.scoring_history_window = 50
        mock_settings.band_sensitivity_factor = 5.0  # High sensitivity to push below 0
        mock_settings.band_min_width = 0.05

        band = await engine.compute_band(agent_id=1, context_type="general")

    assert band["low"] >= 0.0


@pytest.mark.asyncio
async def test_band_high_never_above_one(mock_mysql: AsyncMock):
    """Band high is clamped to 1.0 even if mean + band_width would exceed 1."""
    # Very high scores with some variance
    scores = [0.97, 0.98, 0.99, 0.97, 0.98] * 10
    mock_mysql.fetch_recent_scores.return_value = scores
    engine = BandEngine(mock_mysql)

    with patch("app.services.band_engine.settings") as mock_settings:
        mock_settings.scoring_history_window = 50
        mock_settings.band_sensitivity_factor = 5.0  # High sensitivity to push above 1
        mock_settings.band_min_width = 0.05

        band = await engine.compute_band(agent_id=1, context_type="general")

    assert band["high"] <= 1.0


@pytest.mark.asyncio
async def test_band_uses_config_window_size(mock_mysql: AsyncMock):
    """Verify the engine passes the window size from config to the DB query."""
    mock_mysql.fetch_recent_scores.return_value = [0.5] * 10
    engine = BandEngine(mock_mysql)

    with patch("app.services.band_engine.settings") as mock_settings:
        mock_settings.scoring_history_window = 30
        mock_settings.band_sensitivity_factor = 1.0
        mock_settings.band_min_width = 0.05

        await engine.compute_band(agent_id=7, context_type="qa")

    mock_mysql.fetch_recent_scores.assert_awaited_once_with(7, "qa", 30)


@pytest.mark.asyncio
async def test_sensitivity_factor_affects_band_width(mock_mysql: AsyncMock):
    """Higher sensitivity_factor should produce a wider band."""
    scores = [0.4, 0.5, 0.6, 0.5, 0.4] * 10
    mock_mysql.fetch_recent_scores.return_value = scores
    engine = BandEngine(mock_mysql)

    with patch("app.services.band_engine.settings") as mock_settings:
        mock_settings.scoring_history_window = 50
        mock_settings.band_min_width = 0.01

        # Low sensitivity
        mock_settings.band_sensitivity_factor = 0.5
        band_narrow = await engine.compute_band(agent_id=1, context_type="general")

        # High sensitivity
        mock_settings.band_sensitivity_factor = 3.0
        band_wide = await engine.compute_band(agent_id=1, context_type="general")

    width_narrow = band_narrow["high"] - band_narrow["low"]
    width_wide = band_wide["high"] - band_wide["low"]
    assert width_wide > width_narrow
