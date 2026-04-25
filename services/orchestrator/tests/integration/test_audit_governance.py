"""Integration test for audit-event governance endpoints (Phase E2).

This is a focused integration test: we don't spin up MySQL. Instead we patch
``app.routes.governance._fetch_all`` to simulate the table state after one
event has been written, and exercise the three new endpoints through FastAPI's
TestClient. That gives us end-to-end coverage of:
  * Route registration
  * Query parameter handling (filters, aliasing of ``from`` -> ``from_``)
  * Response shape ({trace_id, events, count} / by-trace / summary)

A second test runs through the AuditWriter swallow path so we verify the full
"write → read back via governance" pipeline at the contract level even when
MySQL is unreachable in the test environment.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import governance
from app.utils.audit import AuditWriter
from types import SimpleNamespace


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """Mount the governance router on a bare FastAPI app for direct testing."""
    app = FastAPI()
    app.include_router(governance.router)
    # Stub the neo4j attribute the trace endpoints expect — we don't use them
    # here but governance.py touches request.app.state.neo4j on import paths
    # that aren't exercised by this test, so a no-op is fine.
    app.state.neo4j = SimpleNamespace()
    return TestClient(app)


def _fake_event_row(**overrides) -> Dict[str, Any]:
    base = {
        "event_id": "11111111-1111-1111-1111-111111111111",
        "trace_id": "trace-abc",
        "actor": "orchestrator",
        "actor_type": "SERVICE",
        "action": "pipeline.intake",
        "resource_type": "Conversation",
        "resource_id": "conv-1",
        "severity": "INFO",
        "payload": {"team_id": "team-x"},
        "ts": "2026-04-24T12:00:00.000",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# /audit-events (list with filters)
# ---------------------------------------------------------------------------

def test_list_audit_events_default(client):
    """No filters → returns all events sorted by ts DESC."""
    captured_sql: Dict[str, Any] = {}

    def fake_fetch(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        captured_sql["sql"] = sql
        captured_sql["params"] = params
        return [_fake_event_row(), _fake_event_row(action="pipeline.responded")]

    with patch.object(governance, "_fetch_all", side_effect=fake_fetch):
        resp = client.get("/v1/governance/audit-events")

    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    assert "trace_id" in body
    assert isinstance(body["events"], list)
    assert body["events"][0]["action"] == "pipeline.intake"
    assert "ORDER BY ts DESC" in captured_sql["sql"]


def test_list_audit_events_with_filters(client):
    """trace_id + action + severity filters all hit the WHERE clause."""
    captured_sql: Dict[str, Any] = {}

    def fake_fetch(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        captured_sql["sql"] = sql
        captured_sql["params"] = params
        return [_fake_event_row(severity="ERROR", action="pipeline.error")]

    with patch.object(governance, "_fetch_all", side_effect=fake_fetch):
        resp = client.get(
            "/v1/governance/audit-events"
            "?trace_id=trace-abc&action=pipeline.error&severity=ERROR&limit=50"
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["events"][0]["action"] == "pipeline.error"
    sql = captured_sql["sql"]
    assert "trace_id = %s" in sql
    assert "action = %s" in sql
    assert "severity = %s" in sql
    assert captured_sql["params"] == ("trace-abc", "pipeline.error", "ERROR")


def test_list_audit_events_action_prefix(client):
    """action ending in '.' → LIKE prefix match."""
    captured: Dict[str, Any] = {}

    def fake_fetch(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        captured["sql"] = sql
        captured["params"] = params
        return []

    with patch.object(governance, "_fetch_all", side_effect=fake_fetch):
        resp = client.get("/v1/governance/audit-events?action=pipeline.")
    assert resp.status_code == 200
    assert "action LIKE %s" in captured["sql"]
    assert captured["params"] == ("pipeline.%",)


def test_list_audit_events_from_to_aliases(client):
    """`from`/`to` ISO datetimes flow into the ts BETWEEN filter."""
    captured: Dict[str, Any] = {}

    def fake_fetch(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        captured["sql"] = sql
        captured["params"] = params
        return []

    with patch.object(governance, "_fetch_all", side_effect=fake_fetch):
        resp = client.get(
            "/v1/governance/audit-events"
            "?from=2026-04-24T00:00:00&to=2026-04-25T00:00:00"
        )

    assert resp.status_code == 200
    sql = captured["sql"]
    assert "ts >= %s" in sql
    assert "ts <= %s" in sql
    assert captured["params"] == ("2026-04-24T00:00:00", "2026-04-25T00:00:00")


# ---------------------------------------------------------------------------
# /audit-events/by-trace/{trace_id}
# ---------------------------------------------------------------------------

def test_audit_events_by_trace_returns_chronological_list(client):
    """By-trace endpoint returns events ordered ASC and includes target_trace_id."""
    captured: Dict[str, Any] = {}

    def fake_fetch(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        captured["sql"] = sql
        captured["params"] = params
        return [
            _fake_event_row(action="pipeline.intake", ts="2026-04-24T12:00:00.000"),
            _fake_event_row(action="pipeline.decomposed", ts="2026-04-24T12:00:01.000"),
            _fake_event_row(action="pipeline.responded", ts="2026-04-24T12:00:05.000"),
        ]

    with patch.object(governance, "_fetch_all", side_effect=fake_fetch):
        resp = client.get("/v1/governance/audit-events/by-trace/trace-abc")

    assert resp.status_code == 200
    body = resp.json()
    assert body["target_trace_id"] == "trace-abc"
    assert body["count"] == 3
    assert [e["action"] for e in body["events"]] == [
        "pipeline.intake",
        "pipeline.decomposed",
        "pipeline.responded",
    ]
    assert "ORDER BY ts ASC" in captured["sql"]
    assert captured["params"] == ("trace-abc",)


# ---------------------------------------------------------------------------
# /audit-events/summary
# ---------------------------------------------------------------------------

def test_audit_events_summary(client):
    """Summary endpoint groups by action and severity."""
    calls: List[Dict[str, Any]] = []

    def fake_fetch(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        calls.append({"sql": sql, "params": params})
        if "GROUP BY action" in sql:
            return [
                {"action": "pipeline.intake", "n": 7},
                {"action": "pipeline.responded", "n": 5},
            ]
        if "GROUP BY severity" in sql:
            return [
                {"severity": "INFO", "n": 11},
                {"severity": "ERROR", "n": 1},
            ]
        # COUNT(*) total query
        return [{"n": 12}]

    with patch.object(governance, "_fetch_all", side_effect=fake_fetch):
        resp = client.get("/v1/governance/audit-events/summary")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 12
    assert body["by_action"][0]["action"] == "pipeline.intake"
    assert body["by_severity"][0]["severity"] == "INFO"
    # Ensure all three queries fired.
    assert len(calls) == 3


# ---------------------------------------------------------------------------
# End-to-end contract: write + read back
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_writer_swallow_then_endpoint_still_returns(client):
    """The writer's swallow contract + governance endpoint still answers.

    Even when MySQL is unreachable for the WRITE side, the READ side (via
    governance) must still produce a stable response shape. We simulate the
    read by patching _fetch_all.
    """
    settings = SimpleNamespace(
        mysql_host="127.0.0.1",
        mysql_port=3306,
        mysql_user="root",
        mysql_password="bogus",
        mysql_db="pmos_no_such_db",
    )
    writer = AuditWriter(settings)
    # Should NOT raise — connect will fail inside the executor.
    await writer.write(
        trace_id="trace-xyz",
        actor="orchestrator",
        action="pipeline.intake",
        payload={"k": "v"},
    )

    # Now pretend the row is in the table and read it back via the endpoint.
    def fake_fetch(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        return [_fake_event_row(trace_id="trace-xyz", action="pipeline.intake")]

    with patch.object(governance, "_fetch_all", side_effect=fake_fetch):
        resp = client.get("/v1/governance/audit-events/by-trace/trace-xyz")

    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["events"][0]["action"] == "pipeline.intake"
    assert body["events"][0]["trace_id"] == "trace-xyz"
