"""Audit-event writer for the orchestrator (Phase E2).

A single dedicated table — ``audit_events`` — records meaningful hops in the
pipeline so we have a tamper-evident, queryable log that's separate from the
scattered execution traces in ``execution_graph_log``, ``score_history`` and
the Neo4j TaskGraph.

Design contract (must always hold):
  * ``write()`` NEVER raises.  Audit must not break the pipeline.
  * Inserts run in a thread executor so they don't block the event loop
    (``mysql.connector`` is sync).
  * Payloads are serialized to JSON and capped at <8KB to keep the table tidy.

Usage:
    from app.utils.audit import audit
    await audit.write(
        trace_id=trace_id,
        actor="orchestrator",
        actor_type="SERVICE",
        action="pipeline.intake",
        resource_type="Conversation",
        resource_id=conversation_id,
        payload={"team_id": team_id, "message_len": len(message)},
    )
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Dict, Optional

import mysql.connector

from app.config import settings
from app.utils.logger import logger


_PAYLOAD_BYTE_CAP = 8 * 1024  # 8KB hard cap on serialized payload


def _safe_json(payload: Optional[Dict[str, Any]]) -> Optional[str]:
    """Serialize payload to JSON, truncating values that blow past the cap.

    Never raises — falls back to ``{"__audit_serialize_error": "..."}`` so the
    insert can still succeed.
    """
    if payload is None:
        return None
    try:
        s = json.dumps(payload, default=str)
    except Exception as exc:
        return json.dumps({"__audit_serialize_error": str(exc)[:200]})

    if len(s.encode("utf-8")) <= _PAYLOAD_BYTE_CAP:
        return s

    # Too big — try truncating string fields, then fall back to a stub.
    try:
        trimmed: Dict[str, Any] = {}
        for k, v in (payload.items() if isinstance(payload, dict) else []):
            if isinstance(v, str) and len(v) > 512:
                trimmed[k] = v[:512] + "...<truncated>"
            else:
                trimmed[k] = v
        s2 = json.dumps(trimmed, default=str)
        if len(s2.encode("utf-8")) <= _PAYLOAD_BYTE_CAP:
            return s2
    except Exception:
        pass

    return json.dumps({
        "__audit_truncated": True,
        "original_size_bytes": len(s.encode("utf-8")),
        "preview": s[:512],
    })


class AuditWriter:
    """Async-safe wrapper around ``mysql.connector`` for ``audit_events`` inserts."""

    def __init__(self, mysql_settings: Any) -> None:
        # Store config; don't open a connection here — short-lived per-insert
        # connections match the pattern used in routes/catalog.py:_conn().
        self._cfg = {
            "host": getattr(mysql_settings, "mysql_host", "localhost"),
            "port": getattr(mysql_settings, "mysql_port", 3306),
            "user": getattr(mysql_settings, "mysql_user", "root"),
            "password": getattr(mysql_settings, "mysql_password", ""),
            "database": getattr(mysql_settings, "mysql_db", "pmos"),
        }

    # ------------------------------------------------------------------
    # Sync insert (runs in a thread executor)
    # ------------------------------------------------------------------
    def _insert_sync(
        self,
        event_id: str,
        trace_id: str,
        actor: str,
        actor_type: str,
        action: str,
        resource_type: Optional[str],
        resource_id: Optional[str],
        severity: str,
        payload_json: Optional[str],
    ) -> None:
        conn = mysql.connector.connect(connection_timeout=5, **self._cfg)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO audit_events
                    (event_id, trace_id, actor, actor_type, action,
                     resource_type, resource_id, severity, payload)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    event_id, trace_id, actor, actor_type, action,
                    resource_type, resource_id, severity, payload_json,
                ),
            )
            conn.commit()
            cur.close()
        finally:
            try:
                conn.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Public async write — swallow-all-errors contract
    # ------------------------------------------------------------------
    async def write(
        self,
        trace_id: str,
        actor: str,
        action: str,
        *,
        actor_type: str = "SYSTEM",
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        severity: str = "INFO",
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Insert one ``audit_events`` row. NEVER raises."""
        try:
            event_id = str(uuid.uuid4())
            payload_json = _safe_json(payload)
            actor_type_u = (actor_type or "SYSTEM").upper()
            if actor_type_u not in ("USER", "AGENT", "SERVICE", "SYSTEM"):
                actor_type_u = "SYSTEM"
            severity_u = (severity or "INFO").upper()
            if severity_u not in ("INFO", "WARN", "ERROR"):
                severity_u = "INFO"

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self._insert_sync,
                event_id,
                trace_id or str(uuid.uuid4()),
                actor or "system",
                actor_type_u,
                action,
                resource_type,
                resource_id,
                severity_u,
                payload_json,
            )
        except Exception as exc:  # never propagate
            try:
                logger.warning(
                    "audit_write_failed",
                    layer="audit",
                    action=action,
                    error=str(exc)[:300],
                    trace_id=trace_id,
                )
            except Exception:
                pass


# Module-level singleton, initialized lazily so unit tests can monkeypatch
# ``settings`` before first use.
_audit_singleton: Optional[AuditWriter] = None


def _get_audit() -> AuditWriter:
    global _audit_singleton
    if _audit_singleton is None:
        _audit_singleton = AuditWriter(settings)
    return _audit_singleton


class _AuditProxy:
    """Thin proxy so callers can do ``from app.utils.audit import audit``."""

    async def write(self, *args: Any, **kwargs: Any) -> None:
        await _get_audit().write(*args, **kwargs)


audit = _AuditProxy()
