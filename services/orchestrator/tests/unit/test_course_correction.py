"""Unit tests for the severity-aware course correction decision tree."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from app.services.course_corrector import CourseAction, CourseCorrector


@pytest.mark.asyncio
async def test_score_above_band_returns_pass(mock_neo4j, mock_redis):
    """score >= band_low → PASS, no Neo4j/Redis calls."""
    corrector = CourseCorrector(neo4j=mock_neo4j, redis=mock_redis)

    result = await corrector.handle_score_failure(
        node_id="n1", score=0.80, band_low=0.75,
        criticality="LOW", agent_id=1, task_id="t1", trace_id="tr1",
    )

    assert result.action == CourseAction.PASS
    mock_neo4j.create_execution_event.assert_not_called()
    mock_redis.publish_to_stream.assert_not_called()


@pytest.mark.asyncio
async def test_low_criticality_fail_escalates_to_orchestrator(mock_neo4j, mock_redis):
    """LOW criticality fail → ESCALATE_TO_ORCHESTRATOR."""
    corrector = CourseCorrector(neo4j=mock_neo4j, redis=mock_redis)

    result = await corrector.handle_score_failure(
        node_id="n2", score=0.40, band_low=0.70,
        criticality="LOW", agent_id=2, task_id="t2", trace_id="tr2",
    )

    assert result.action == CourseAction.ESCALATE_TO_ORCHESTRATOR
    mock_neo4j.create_execution_event.assert_called_once()


@pytest.mark.asyncio
async def test_medium_criticality_fail_escalates_to_orchestrator(mock_neo4j, mock_redis):
    """MEDIUM criticality fail → ESCALATE_TO_ORCHESTRATOR."""
    corrector = CourseCorrector(neo4j=mock_neo4j, redis=mock_redis)

    result = await corrector.handle_score_failure(
        node_id="n3", score=0.35, band_low=0.60,
        criticality="MEDIUM", agent_id=3, task_id="t3", trace_id="tr3",
    )

    assert result.action == CourseAction.ESCALATE_TO_ORCHESTRATOR


@pytest.mark.asyncio
async def test_high_criticality_fail_auto_corrects_locally(mock_neo4j, mock_redis):
    """HIGH criticality fail → AUTO_CORRECT_LOCAL immediately."""
    corrector = CourseCorrector(neo4j=mock_neo4j, redis=mock_redis)

    result = await corrector.handle_score_failure(
        node_id="n4", score=0.20, band_low=0.70,
        criticality="HIGH", agent_id=4, task_id="t4", trace_id="tr4",
    )

    assert result.action == CourseAction.AUTO_CORRECT_LOCAL
    assert result.correction_applied is True
    # Must log event to Neo4j AND publish async feedback
    mock_neo4j.create_execution_event.assert_called_once()
    mock_redis.publish_to_stream.assert_called_once()


@pytest.mark.asyncio
async def test_critical_severity_fail_auto_corrects_immediately(mock_neo4j, mock_redis):
    """CRITICAL criticality fail → AUTO_CORRECT_LOCAL (same path as HIGH)."""
    corrector = CourseCorrector(neo4j=mock_neo4j, redis=mock_redis)

    result = await corrector.handle_score_failure(
        node_id="n5", score=0.10, band_low=0.80,
        criticality="CRITICAL", agent_id=5, task_id="t5", trace_id="tr5",
    )

    assert result.action == CourseAction.AUTO_CORRECT_LOCAL
    assert result.correction_applied is True
