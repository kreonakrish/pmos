"""Shared audit-event writer (Phase E2).

Mirror of ``services/orchestrator/app/utils/audit.py`` but free of any
service-specific imports so it can be reused by the translator (which copies
the ``shared/`` package into its image — see ``services/translator/Dockerfile``).

Contract:
  * ``write()`` NEVER raises.
  * Inserts run in a thread executor (``mysql.connector`` is sync).
  * Payloads are JSON-serialized and capped at <8KB.

Usage from any service whose Dockerfile copies ``shared/`` to ``/app/shared/``:

    from shared.audit import AuditWriter, get_audit

    audit = get_audit(settings)            # one-time at startup
    await audit.write(trace_id=..., actor="translator", action="translator.start")
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Dict, Optional

import mysql.connector


_PAYLOAD_BYTE_CAP = 8 * 1024
_logger = logging.getLogger("shared.audit")


def _safe_json(payload: Optional[Dict[str, Any]]) -> Optional[str]:
    if payload is None:
        return None
    try:
        s = json.dumps(payload, default=str)
    except Exception as exc:
        return json.dumps({"__audit_serialize_error": str(exc)[:200]})

    if len(s.encode("utf-8")) <= _PAYLOAD_BYTE_CAP:
        return s

    try:
        trimmed: Dict[str, Any] = {}
        if isinstance(payload, dict):
            for k, v in payload.items():
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
        self._cfg = {
            "host": getattr(mysql_settings, "mysql_host", "localhost"),
            "port": getattr(mysql_settings, "mysql_port", 3306),
            "user": getattr(mysql_settings, "mysql_user", "root"),
            "password": getattr(mysql_settings, "mysql_password", ""),
            "database": getattr(mysql_settings, "mysql_db", "pmos"),
        }

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
        """Insert one audit_events row. NEVER raises."""
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
        except Exception as exc:  # swallow
            try:
                _logger.warning(
                    "audit_write_failed action=%s error=%s trace_id=%s",
                    action, str(exc)[:300], trace_id,
                )
            except Exception:
                pass


_singleton: Optional[AuditWriter] = None


def get_audit(mysql_settings: Any) -> AuditWriter:
    """Lazy module-level singleton."""
    global _singleton
    if _singleton is None:
        _singleton = AuditWriter(mysql_settings)
    return _singleton
