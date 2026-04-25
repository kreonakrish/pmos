"""Smoke test for the translator health endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    # Stub adapters so the test doesn't require Neo4j/Qdrant/LLM.
    from app import main as main_mod

    fake_neo4j = AsyncMock()
    fake_neo4j.connect = AsyncMock()
    fake_neo4j.close = AsyncMock()
    fake_neo4j.health_check = AsyncMock(return_value=True)

    fake_qdrant = AsyncMock()
    fake_qdrant.ensure_collection = AsyncMock()
    fake_qdrant.health_check = AsyncMock(return_value=True)

    fake_llm = AsyncMock()
    fake_llm.health_check = AsyncMock(return_value=True)

    fake_embedder = AsyncMock()
    fake_embedder.available = lambda: True
    fake_embedder.health_check = AsyncMock(return_value=True)

    monkeypatch.setattr(main_mod, "build_ontology_adapter", lambda: fake_neo4j)
    monkeypatch.setattr(main_mod, "QdrantAdapter", lambda: fake_qdrant)
    monkeypatch.setattr(main_mod, "LLMAdapter", lambda: fake_llm)
    monkeypatch.setattr(main_mod, "Embedder", lambda: fake_embedder)

    with TestClient(main_mod.app) as c:
        yield c


def test_health_returns_up(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "UP"
    assert body["service"] == "translator"
    assert body["neo4j"] is True
    assert body["qdrant"] is True
    assert body["llm"] is True
