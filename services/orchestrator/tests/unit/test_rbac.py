"""Unit tests for the orchestrator RBAC dependency.

The MySQL connection inside ``app.middleware.rbac`` is monkey-patched so
these tests run hermetically with no DB.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException, Request


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_request(
    headers: Optional[dict] = None,
    method: str = "POST",
    path: str = "/v1/catalog/crawlers",
) -> Request:
    """Build a minimal FastAPI ``Request`` with an ASGI scope."""
    raw_headers: List[Tuple[bytes, bytes]] = []
    for k, v in (headers or {}).items():
        raw_headers.append((k.lower().encode(), v.encode()))
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "headers": raw_headers,
        "query_string": b"",
        "scheme": "http",
        "server": ("testserver", 80),
    }
    return Request(scope)


class _FakeCursor:
    def __init__(self, rows: List[Tuple[str, ...]]) -> None:
        self._rows = rows

    def execute(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def fetchall(self) -> List[Tuple[str, ...]]:
        return self._rows


class _FakeConn:
    def __init__(self, rows: List[Tuple[str, ...]]) -> None:
        self._rows = rows

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._rows)

    def close(self) -> None:
        return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _reset_cache():
    from app.middleware import rbac as rbac_mod
    rbac_mod._clear_rbac_cache()
    yield
    rbac_mod._clear_rbac_cache()


def test_missing_x_user_id_returns_401() -> None:
    """No identity at all → 401, not 403."""
    from app.middleware.rbac import require_permission

    dep = require_permission("catalog.write")
    req = _make_request(headers={})

    with pytest.raises(HTTPException) as exc_info:
        dep(req)

    assert exc_info.value.status_code == 401
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail.get("code") == "AUTH_FAILED"


def test_missing_permission_returns_403() -> None:
    from app.middleware import rbac as rbac_mod

    fake_conn = _FakeConn([("catalog.read",)])
    with patch.object(rbac_mod, "_conn", return_value=fake_conn):
        dep = rbac_mod.require_permission("catalog.write")
        req = _make_request(headers={"x-user-id": "42"})
        with pytest.raises(HTTPException) as exc_info:
            dep(req)

    assert exc_info.value.status_code == 403
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail.get("code") == "FORBIDDEN"
    assert "catalog.write" in detail.get("missing", [])


def test_present_permission_passes() -> None:
    """When the user holds the permission, the dep returns None (no raise)."""
    from app.middleware import rbac as rbac_mod

    fake_conn = _FakeConn([("catalog.write",), ("catalog.read",)])
    with patch.object(rbac_mod, "_conn", return_value=fake_conn):
        dep = rbac_mod.require_permission("catalog.write")
        req = _make_request(headers={"x-user-id": "42"})
        # Must not raise
        result = dep(req)

    assert result is None


def test_db_outage_fails_closed_for_mutating_route() -> None:
    """A POST against an unreachable MySQL → 403 (deny)."""
    from app.middleware import rbac as rbac_mod
    import mysql.connector

    def _boom(*_a: Any, **_kw: Any) -> None:
        raise mysql.connector.Error("connection refused")

    with patch.object(rbac_mod, "_conn", side_effect=_boom):
        dep = rbac_mod.require_permission("catalog.write")
        req = _make_request(
            headers={"x-user-id": "1"}, method="POST", path="/v1/catalog/crawlers"
        )
        with pytest.raises(HTTPException) as exc_info:
            dep(req)

    assert exc_info.value.status_code == 403


def test_db_outage_fails_open_for_read_route() -> None:
    """A GET against an unreachable MySQL → success (read fail-open)."""
    from app.middleware import rbac as rbac_mod
    import mysql.connector

    def _boom(*_a: Any, **_kw: Any) -> None:
        raise mysql.connector.Error("connection refused")

    with patch.object(rbac_mod, "_conn", side_effect=_boom):
        dep = rbac_mod.require_permission("catalog.read")
        req = _make_request(
            headers={"x-user-id": "1"}, method="GET", path="/v1/catalog/assets"
        )
        # Must not raise
        result = dep(req)

    assert result is None


def test_api_key_bypasses_rbac() -> None:
    """The gateway already authenticated x-api-key — orchestrator trusts it."""
    from app.middleware import rbac as rbac_mod

    # _conn must NOT be called when x-api-key is present
    with patch.object(rbac_mod, "_conn", side_effect=AssertionError("DB hit!")):
        dep = rbac_mod.require_permission("catalog.write")
        req = _make_request(headers={"x-api-key": "anything"})
        result = dep(req)

    assert result is None


def test_permissions_are_cached() -> None:
    """Two calls within the TTL should hit MySQL only once."""
    from app.middleware import rbac as rbac_mod

    fake_conn = _FakeConn([("catalog.write",)])
    conn_factory = MagicMock(return_value=fake_conn)
    with patch.object(rbac_mod, "_conn", conn_factory):
        dep = rbac_mod.require_permission("catalog.write")
        req1 = _make_request(headers={"x-user-id": "99"})
        req2 = _make_request(headers={"x-user-id": "99"})
        dep(req1)
        dep(req2)

    assert conn_factory.call_count == 1


def test_require_any_permission_passes_when_one_held() -> None:
    from app.middleware import rbac as rbac_mod

    fake_conn = _FakeConn([("ml_insights.read",)])
    with patch.object(rbac_mod, "_conn", return_value=fake_conn):
        dep = rbac_mod.require_any_permission("models.read", "ml_insights.read")
        req = _make_request(
            headers={"x-user-id": "1"}, method="GET", path="/v1/governance/traces"
        )
        result = dep(req)

    assert result is None


def test_require_any_permission_denies_when_none_held() -> None:
    from app.middleware import rbac as rbac_mod

    fake_conn = _FakeConn([("agents.read",)])
    with patch.object(rbac_mod, "_conn", return_value=fake_conn):
        dep = rbac_mod.require_any_permission("models.read", "ml_insights.read")
        req = _make_request(
            headers={"x-user-id": "1"}, method="GET", path="/v1/governance/traces"
        )
        with pytest.raises(HTTPException) as exc_info:
            dep(req)

    assert exc_info.value.status_code == 403
