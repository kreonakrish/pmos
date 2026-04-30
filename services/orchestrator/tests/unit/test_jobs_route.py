"""Unit tests for the /v1/orchestrator/jobs/{graph_id} route.

Phase 2 added a `pattern_decision` field that deserialises the JSON
string Neo4j stores. These tests pin that down: the field comes back
as a structured dict, not a string; malformed JSON falls through to
None without 500ing the request.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes.orchestrator import router as orchestrator_router


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_app(neo4j_rows_by_query: Dict[str, List[Dict[str, Any]]]) -> FastAPI:
    """Build a FastAPI app with a stubbed neo4j adapter.

    ``neo4j_rows_by_query`` maps a substring of the cypher to the rows
    we want returned. The stub picks the first key contained in the
    cypher being executed.
    """
    app = FastAPI()
    app.include_router(orchestrator_router)

    neo4j = AsyncMock()

    async def fake_run_query(cypher: str, params: Dict[str, Any] = None,
                             trace_id: str = "") -> List[Dict[str, Any]]:
        for marker, rows in neo4j_rows_by_query.items():
            if marker in cypher:
                return list(rows)
        return []

    neo4j.run_query = AsyncMock(side_effect=fake_run_query)
    app.state.neo4j = neo4j

    # The route guards on require_permission("conversations.write") for
    # mutations only; reads bypass when x-user-id is set.
    return app


def _client(app: FastAPI) -> TestClient:
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# pattern_decision is parsed from the JSON property on TaskGraph
# ---------------------------------------------------------------------------

def test_get_job_includes_parsed_pattern_decision():
    trace = {
        "candidates": [
            {
                "name": "metadata",
                "priority": 70,
                "score": 0.85,
                "threshold": 0.5,
                "accepted": True,
                "evidence": ["regex 'how many tables have X' matched"],
                "explanation": "schema-meta phrasing",
                "error": None,
                "duration_ms": 1,
            },
            {
                "name": "report",
                "priority": 90,
                "score": 0.0,
                "threshold": 12.0,
                "accepted": False,
                "evidence": [],
                "explanation": "",
                "error": None,
                "duration_ms": 0,
            },
        ],
        "winner": "metadata",
        "duration_ms": 5,
        "translator_summary": {
            "intent": "schema_meta_question",
            "schema_meta_column": "loan_id",
        },
        "shadow": True,
    }

    app = _make_app({
        "MATCH (g:TaskGraph": [{"g": {
            "graph_id": "g-1",
            "status": "COMPLETED",
            "pattern_decision_trace": json.dumps(trace),
            "pattern_winner": "metadata",
            "pattern_shadow": True,
        }}],
        "MATCH (n:TaskNode": [],
        "MATCH (a:TaskNode": [],
    })

    resp = _client(app).get(
        "/v1/orchestrator/jobs/g-1",
        headers={"x-api-key": "dev"},
    )
    assert resp.status_code == 200
    body = resp.json()

    # The route deserialises the JSON string into a structured dict.
    assert body["pattern_decision"] is not None
    assert body["pattern_decision"]["winner"] == "metadata"
    assert body["pattern_decision"]["shadow"] is True
    assert len(body["pattern_decision"]["candidates"]) == 2
    metadata_cand = next(
        c for c in body["pattern_decision"]["candidates"] if c["name"] == "metadata"
    )
    assert metadata_cand["accepted"] is True
    assert metadata_cand["evidence"] == ["regex 'how many tables have X' matched"]


def test_get_job_returns_null_pattern_decision_when_unset():
    """Pre-Phase-1 graphs (or graphs where shadow stamping failed) must
    not break the endpoint; they just have no decision recorded."""
    app = _make_app({
        "MATCH (g:TaskGraph": [{"g": {
            "graph_id": "g-2",
            "status": "COMPLETED",
            # no pattern_decision_trace property
        }}],
        "MATCH (n:TaskNode": [],
        "MATCH (a:TaskNode": [],
    })

    resp = _client(app).get(
        "/v1/orchestrator/jobs/g-2",
        headers={"x-api-key": "dev"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["pattern_decision"] is None


def test_get_job_returns_null_when_trace_is_garbled():
    """A corrupted trace string is logged and surfaced as None — the
    endpoint must NOT 500 on bad data we wrote ourselves."""
    app = _make_app({
        "MATCH (g:TaskGraph": [{"g": {
            "graph_id": "g-3",
            "status": "COMPLETED",
            "pattern_decision_trace": "{not valid json",
        }}],
        "MATCH (n:TaskNode": [],
        "MATCH (a:TaskNode": [],
    })

    resp = _client(app).get(
        "/v1/orchestrator/jobs/g-3",
        headers={"x-api-key": "dev"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["pattern_decision"] is None


def test_get_job_404_when_graph_missing():
    app = _make_app({})  # all queries return []

    resp = _client(app).get(
        "/v1/orchestrator/jobs/missing",
        headers={"x-api-key": "dev"},
    )
    assert resp.status_code == 404
