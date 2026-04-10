"""Shared pytest fixtures for orchestrator tests."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Event loop
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ---------------------------------------------------------------------------
# Mock Neo4j adapter
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_neo4j():
    neo4j = AsyncMock()
    neo4j.create_task_graph = AsyncMock()
    neo4j.create_task_node = AsyncMock()
    neo4j.link_spawned_by = AsyncMock()
    neo4j.update_task_node_status = AsyncMock()
    neo4j.update_graph_status = AsyncMock()
    neo4j.get_graph_nodes = AsyncMock(return_value=[])
    neo4j.get_team_agents = AsyncMock(return_value=[])
    neo4j.create_execution_event = AsyncMock()
    neo4j.run_query = AsyncMock(return_value=[])
    neo4j.health_check = AsyncMock(return_value=True)
    return neo4j


# ---------------------------------------------------------------------------
# Mock Redis adapter
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.publish_to_stream = AsyncMock(return_value="1-0")
    redis.publish_memory_write = AsyncMock(return_value="1-0")
    redis.publish_telemetry = AsyncMock(return_value="1-0")
    redis.publish_task = AsyncMock(return_value="1-0")
    redis.health_check = AsyncMock(return_value=True)
    return redis


# ---------------------------------------------------------------------------
# Mock LLM adapter
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value='["Sub-task 1", "Sub-task 2"]')
    return llm


# ---------------------------------------------------------------------------
# Mock downstream service adapters
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_memory():
    m = AsyncMock()
    m.assemble_prompt = AsyncMock(return_value={
        "system_prompt": "You are an expert assistant.",
        "sources": {"short_term_hits": 1, "long_term_hits": 2, "reasoning_hits": 0, "episodic_hits": 1},
        "trace_id": "test-trace",
    })
    return m


@pytest.fixture
def mock_scoring():
    s = AsyncMock()
    s.evaluate = AsyncMock(return_value={
        "score": 0.85,
        "band": {"low": 0.5, "high": 1.0},
        "recommendation": "proceed",
        "factors": {},
        "trace_id": "test-trace",
    })
    s.submit_feedback = AsyncMock()
    return s


@pytest.fixture
def mock_rag():
    r = AsyncMock()
    r.query = AsyncMock(return_value={
        "results": [],
        "sources_queried": [],
        "latency_ms": 50,
        "trace_id": "test-trace",
    })
    return r


@pytest.fixture
def mock_meta():
    m = AsyncMock()
    m.detect_gap = AsyncMock(return_value={
        "gap_description": "Missing capability",
        "suggested_capability_type": "tool",
        "confidence": 0.7,
        "trace_id": "test-trace",
    })
    return m
