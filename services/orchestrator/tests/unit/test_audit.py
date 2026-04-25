"""Unit tests for the AuditWriter (Phase E2).

The audit writer's load-bearing guarantee is "never raise". These tests
confirm that:
  * write() swallows any MySQL connect/insert exception.
  * write() correctly serializes payload + caps it at 8KB.
  * The module-level singleton ``audit`` proxies through.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.utils.audit import AuditWriter, _safe_json, audit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _settings():
    """Minimal stand-in for the orchestrator Settings object."""
    return SimpleNamespace(
        mysql_host="127.0.0.1",
        mysql_port=3306,
        mysql_user="root",
        mysql_password="bogus-no-such-password",
        mysql_db="pmos_definitely_does_not_exist",
    )


# ---------------------------------------------------------------------------
# write() swallows errors
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_write_swallows_connect_error():
    """If MySQL isn't reachable, write() must NOT raise."""
    writer = AuditWriter(_settings())
    # No host/port reachable — connect will raise inside the executor.
    # Audit must still complete cleanly.
    await writer.write(
        trace_id="t-1",
        actor="orchestrator",
        action="pipeline.intake",
        payload={"k": "v"},
    )
    # If we got here without an exception, the contract holds.


@pytest.mark.asyncio
async def test_write_swallows_executor_error():
    """If the underlying _insert_sync raises, write() must NOT propagate."""
    writer = AuditWriter(_settings())

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated DB outage")

    with patch.object(writer, "_insert_sync", side_effect=_boom):
        await writer.write(
            trace_id="t-2",
            actor="translator",
            action="translator.error",
            severity="ERROR",
            payload={"error": "boom"},
        )


@pytest.mark.asyncio
async def test_write_invokes_insert_with_correct_args():
    """Happy path: write() calls _insert_sync with normalized arguments."""
    writer = AuditWriter(_settings())
    captured = {}

    def _capture(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        # Pretend the insert succeeded.
        return None

    with patch.object(writer, "_insert_sync", side_effect=_capture):
        await writer.write(
            trace_id="t-3",
            actor="orchestrator",
            action="pipeline.intake",
            actor_type="service",       # lowercase; should be normalized.
            severity="info",            # lowercase; should be normalized.
            resource_type="TaskGraph",
            resource_id="g-123",
            payload={"hello": "world"},
        )

    args = captured["args"]
    # Positional order: event_id, trace_id, actor, actor_type, action,
    # resource_type, resource_id, severity, payload_json
    assert args[1] == "t-3"
    assert args[2] == "orchestrator"
    assert args[3] == "SERVICE"        # uppercased
    assert args[4] == "pipeline.intake"
    assert args[5] == "TaskGraph"
    assert args[6] == "g-123"
    assert args[7] == "INFO"           # uppercased
    payload_json = args[8]
    assert payload_json is not None
    assert json.loads(payload_json) == {"hello": "world"}


@pytest.mark.asyncio
async def test_write_normalizes_invalid_enums():
    """Bad actor_type / severity should fall back to defaults instead of failing."""
    writer = AuditWriter(_settings())
    captured = {}

    def _capture(*args, **kwargs):
        captured["args"] = args
        return None

    with patch.object(writer, "_insert_sync", side_effect=_capture):
        await writer.write(
            trace_id="t-4",
            actor="x",
            action="anything",
            actor_type="BANANA",        # invalid -> SYSTEM
            severity="LOUD",            # invalid -> INFO
        )

    args = captured["args"]
    assert args[3] == "SYSTEM"
    assert args[7] == "INFO"


# ---------------------------------------------------------------------------
# Payload truncation
# ---------------------------------------------------------------------------

def test_safe_json_caps_oversized_payload():
    """A payload >8KB must be truncated to fit, not blow past the cap."""
    huge = {"big": "x" * 20000}
    out = _safe_json(huge)
    assert out is not None
    # The result should be well under the 8KB cap.
    assert len(out.encode("utf-8")) <= 8 * 1024 + 64
    parsed = json.loads(out)
    # Either trimmed inline, or replaced with the truncation stub.
    assert parsed.get("__audit_truncated") is True or "<truncated>" in (
        parsed.get("big") or ""
    )


def test_safe_json_returns_none_for_none():
    assert _safe_json(None) is None


def test_safe_json_handles_unserializable():
    """Non-JSON-native values must not raise — default=str takes care of it."""

    class Weird:
        def __str__(self) -> str:
            return "weird-obj"

    out = _safe_json({"k": Weird()})
    assert out is not None
    parsed = json.loads(out)
    assert parsed["k"] == "weird-obj"


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_audit_singleton_proxy_swallows_errors():
    """``from app.utils.audit import audit`` -> audit.write() never raises."""
    # Even with the real (likely unreachable) settings the singleton should
    # swallow the connect error.
    await audit.write(
        trace_id="t-singleton",
        actor="orchestrator",
        action="pipeline.intake",
        payload={"smoke": True},
    )
