"""Shared test fixtures — mock adapters and services for meta-assembly tests."""
from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


# ── Mock LLM Adapter ────────────────────────────────────────────────────────


class MockLLMAdapter:
    """Fake LLM adapter that returns configurable responses."""

    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self._response = response or {}
        self.complete = AsyncMock(return_value=json.dumps(self._response))
        self.complete_json = AsyncMock(return_value=self._response)

    def set_response(self, response: dict[str, Any]) -> None:
        self._response = response
        self.complete.return_value = json.dumps(response)
        self.complete_json.return_value = response


@pytest.fixture
def mock_llm() -> MockLLMAdapter:
    return MockLLMAdapter()


# ── Mock MySQL Adapter ───────────────────────────────────────────────────────


class MockMySQLAdapter:
    """Fake MySQL adapter that records calls."""

    def __init__(self) -> None:
        self.execute = AsyncMock(return_value=1)
        self.fetch_one = AsyncMock(return_value={"ok": 1})
        self.insert_capability = AsyncMock(return_value=None)
        self.calls: list[dict[str, Any]] = []

    async def _track_execute(self, query: str, params: tuple = (), trace_id: str = "") -> int:
        self.calls.append({"query": query, "params": params, "trace_id": trace_id})
        return 1


@pytest.fixture
def mock_mysql() -> MockMySQLAdapter:
    return MockMySQLAdapter()


# ── Mock Neo4j Adapter ───────────────────────────────────────────────────────


class MockNeo4jAdapter:
    """Fake Neo4j adapter that records calls."""

    def __init__(self) -> None:
        self.create_capability_node = AsyncMock(return_value=None)
        self.nodes_created: list[dict[str, Any]] = []


@pytest.fixture
def mock_neo4j() -> MockNeo4jAdapter:
    return MockNeo4jAdapter()


# ── Mock Redis Adapter ───────────────────────────────────────────────────────


class MockRedisAdapter:
    """Fake Redis adapter that records published messages."""

    def __init__(self) -> None:
        self.publish_capability_added = AsyncMock(return_value="mock-stream-id")
        self.published: list[dict[str, Any]] = []


@pytest.fixture
def mock_redis() -> MockRedisAdapter:
    return MockRedisAdapter()


# ── Mock Settings ─────────────────────────────────────────────────────────────


class MockSettings:
    """Minimal settings object for tests that need config."""

    meta_sandbox_timeout_sec: int = 5
    meta_sandbox_memory_mb: int = 128
    meta_allowed_imports: str = "json,re,math,datetime,collections"
    service_name: str = "meta-assembly-test"

    @property
    def allowed_imports_list(self) -> list[str]:
        return [i.strip() for i in self.meta_allowed_imports.split(",")]


@pytest.fixture
def mock_settings() -> MockSettings:
    return MockSettings()
