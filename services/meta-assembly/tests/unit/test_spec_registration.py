"""Unit tests for CapabilityRegistrar — mock MySQL, Neo4j, Redis."""
from __future__ import annotations

import uuid
import pytest
from unittest.mock import AsyncMock

from app.services.capability_registrar import CapabilityRegistrar


@pytest.fixture
def mock_mysql():
    adapter = AsyncMock()
    adapter.insert_capability = AsyncMock(return_value=None)
    return adapter


@pytest.fixture
def mock_neo4j():
    adapter = AsyncMock()
    adapter.create_capability_node = AsyncMock(return_value=None)
    return adapter


@pytest.fixture
def mock_redis():
    adapter = AsyncMock()
    adapter.publish_capability_added = AsyncMock(return_value="mock-entry-id")
    return adapter


@pytest.fixture
def registrar(mock_mysql, mock_neo4j, mock_redis):
    return CapabilityRegistrar(
        mysql_adapter=mock_mysql,
        neo4j_adapter=mock_neo4j,
        redis_adapter=mock_redis,
    )


SAMPLE_SPEC = {
    "capability_type": "TOOL",
    "name": "csv_parser",
    "description": "Parses CSV files into structured data",
    "spec_json": {
        "code": "def run(**kwargs): return []",
        "dependencies": ["json"],
        "domains": ["data"],
        "test_cases": [],
    },
}


@pytest.mark.asyncio
async def test_register_inserts_mysql_row(registrar, mock_mysql):
    """register() must call insert_capability on the MySQL adapter."""
    cap_id = await registrar.register(
        spec=SAMPLE_SPEC,
        gap_id="gap-1",
        validation_score=1.0,
        trace_id="trace-1",
    )
    mock_mysql.insert_capability.assert_awaited_once()
    call_kwargs = mock_mysql.insert_capability.call_args
    assert call_kwargs.kwargs["capability_type"] == "TOOL"
    assert call_kwargs.kwargs["name"] == "csv_parser"
    assert call_kwargs.kwargs["gap_id"] == "gap-1"
    assert call_kwargs.kwargs["validation_score"] == 1.0


@pytest.mark.asyncio
async def test_register_creates_neo4j_node(registrar, mock_neo4j):
    """register() must create an AgentCapabilityNode in Neo4j."""
    await registrar.register(
        spec=SAMPLE_SPEC,
        gap_id="gap-2",
        validation_score=0.95,
        trace_id="trace-2",
    )
    mock_neo4j.create_capability_node.assert_awaited_once()
    call_kwargs = mock_neo4j.create_capability_node.call_args
    assert call_kwargs.kwargs["domains"] == ["data"]
    assert call_kwargs.kwargs["tool_ids"] == ["json"]


@pytest.mark.asyncio
async def test_register_publishes_to_redis(registrar, mock_redis):
    """register() must publish to the events:capability_added stream."""
    await registrar.register(
        spec=SAMPLE_SPEC,
        gap_id="gap-3",
        validation_score=1.0,
        trace_id="trace-3",
    )
    mock_redis.publish_capability_added.assert_awaited_once()
    call_kwargs = mock_redis.publish_capability_added.call_args
    assert call_kwargs.kwargs["capability_type"] == "TOOL"
    assert call_kwargs.kwargs["capability_name"] == "csv_parser"
    assert call_kwargs.kwargs["gap_id"] == "gap-3"


@pytest.mark.asyncio
async def test_register_returns_valid_uuid(registrar):
    """register() must return a valid UUID string."""
    cap_id = await registrar.register(
        spec=SAMPLE_SPEC,
        gap_id="gap-4",
        validation_score=0.8,
        trace_id="trace-4",
    )
    # Should not raise
    parsed = uuid.UUID(cap_id)
    assert str(parsed) == cap_id


@pytest.mark.asyncio
async def test_register_with_agent_type(registrar, mock_mysql, mock_neo4j):
    """register() works for AGENT capability type."""
    agent_spec = {
        "capability_type": "AGENT",
        "name": "legal_analyst",
        "description": "Handles legal domain tasks",
        "spec_json": {
            "code": "",
            "dependencies": [],
            "domains": ["legal", "compliance"],
            "test_cases": [],
        },
    }
    await registrar.register(
        spec=agent_spec,
        gap_id="gap-5",
        validation_score=0.9,
        trace_id="trace-5",
    )
    mysql_kwargs = mock_mysql.insert_capability.call_args.kwargs
    assert mysql_kwargs["capability_type"] == "AGENT"
    neo4j_kwargs = mock_neo4j.create_capability_node.call_args.kwargs
    assert neo4j_kwargs["domains"] == ["legal", "compliance"]


@pytest.mark.asyncio
async def test_register_mysql_failure_propagates(mock_mysql, mock_neo4j, mock_redis):
    """If MySQL insert fails, the error must propagate."""
    mock_mysql.insert_capability.side_effect = RuntimeError("MySQL connection refused")
    registrar = CapabilityRegistrar(mock_mysql, mock_neo4j, mock_redis)
    with pytest.raises(RuntimeError, match="MySQL connection refused"):
        await registrar.register(
            spec=SAMPLE_SPEC,
            gap_id="gap-6",
            validation_score=1.0,
        )
