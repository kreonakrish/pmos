"""Unit tests for the agent fallback chain."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from app.services.agent_selector import Agent, AgentSelector


@pytest.fixture
def three_agent_rows():
    return [
        {"agent_id": "1", "name": "Alpha", "status": "IDLE", "accuracy_rate": 0.95, "success_rate": 0.93, "foundation_model": "gpt-4o"},
        {"agent_id": "2", "name": "Beta",  "status": "IDLE", "accuracy_rate": 0.80, "success_rate": 0.78, "foundation_model": "gpt-4o"},
        {"agent_id": "3", "name": "Gamma", "status": "IDLE", "accuracy_rate": 0.60, "success_rate": 0.55, "foundation_model": "gpt-3.5"},
    ]


@pytest.mark.asyncio
async def test_primary_agent_is_highest_accuracy(mock_neo4j, three_agent_rows):
    """Primary agent should be the one with the highest accuracy_rate."""
    mock_neo4j.get_team_agents.return_value = three_agent_rows
    selector = AgentSelector(neo4j=mock_neo4j)

    primary, fallbacks = await selector.select_primary_and_fallbacks(
        team_id="team-1", trace_id="t1"
    )

    assert primary is not None
    assert primary.agent_id == "1"
    assert primary.accuracy_rate == 0.95


@pytest.mark.asyncio
async def test_fallbacks_are_remaining_agents_in_order(mock_neo4j, three_agent_rows):
    """Fallbacks should be the next agents by accuracy (already sorted by Neo4j query)."""
    mock_neo4j.get_team_agents.return_value = three_agent_rows
    selector = AgentSelector(neo4j=mock_neo4j)

    primary, fallbacks = await selector.select_primary_and_fallbacks(
        team_id="team-1", trace_id="t2"
    )

    assert len(fallbacks) == 2
    assert fallbacks[0].agent_id == "2"
    assert fallbacks[1].agent_id == "3"


@pytest.mark.asyncio
async def test_no_agents_returns_none_primary(mock_neo4j):
    """No eligible agents → primary is None and fallbacks is empty."""
    mock_neo4j.get_team_agents.return_value = []
    selector = AgentSelector(neo4j=mock_neo4j)

    primary, fallbacks = await selector.select_primary_and_fallbacks(
        team_id="team-empty", trace_id="t3"
    )

    assert primary is None
    assert fallbacks == []


@pytest.mark.asyncio
async def test_single_agent_no_fallbacks(mock_neo4j):
    """Single agent → primary set, empty fallback list."""
    mock_neo4j.get_team_agents.return_value = [
        {"agent_id": "99", "name": "Solo", "status": "IDLE", "accuracy_rate": 0.7, "success_rate": 0.7, "foundation_model": "gpt-4o"},
    ]
    selector = AgentSelector(neo4j=mock_neo4j)

    primary, fallbacks = await selector.select_primary_and_fallbacks(
        team_id="team-solo", trace_id="t4"
    )

    assert primary is not None
    assert primary.agent_id == "99"
    assert fallbacks == []
