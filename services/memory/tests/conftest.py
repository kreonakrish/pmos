"""Shared pytest fixtures for memory service tests."""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest


@pytest.fixture(scope="session")
def event_loop():
    """Provide a single event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_embedding_service():
    """Returns a fake embedding service that returns deterministic vectors."""
    svc = AsyncMock()
    svc.embed = AsyncMock(return_value=np.ones(768, dtype=np.float32))
    svc.embed_batch = AsyncMock(return_value=np.ones((2, 768), dtype=np.float32))
    return svc


@pytest.fixture
def mock_redis_adapter():
    adapter = AsyncMock()
    # Default hgetall returns empty dict
    adapter.hgetall = AsyncMock(return_value={})
    adapter.hset = AsyncMock()
    adapter.hget = AsyncMock(return_value=None)
    adapter.hdel = AsyncMock(return_value=1)
    adapter.expire = AsyncMock()
    adapter.ttl = AsyncMock(return_value=3600)
    adapter.delete = AsyncMock(return_value=1)
    adapter.exists = AsyncMock(return_value=False)
    adapter.xadd = AsyncMock(return_value="1-0")
    adapter.xreadgroup = AsyncMock(return_value=[])
    adapter.xack = AsyncMock(return_value=1)
    adapter.xgroup_create = AsyncMock()
    return adapter


@pytest.fixture
def mock_mysql_adapter():
    adapter = AsyncMock()
    adapter.execute = AsyncMock(return_value=None)
    adapter.insert = AsyncMock(return_value=1)
    adapter.select = AsyncMock(return_value=[])
    adapter.update = AsyncMock()
    return adapter


@pytest.fixture
def mock_faiss_adapter():
    adapter = AsyncMock()
    adapter.add = AsyncMock()
    adapter.search = AsyncMock(return_value=[])
    adapter.get_index_size = MagicMock(return_value=0)
    return adapter
