"""Shared auditor-issue writer.

Records open issues raised at runtime when the system can't resolve
something automatically — synonym ambiguity, column ambiguity (one BA with
multiple live MAPS_TO targets), zero-resolution for a phrased question,
orphan entities, low-confidence auto-mappings, etc.

Writes to MySQL ``auditor_issues``. Never raises — failures are logged.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any, Dict, Optional

import mysql.connector

logger = logging.getLogger("pmos.auditor_issues")

ISSUE_KINDS = (
    "SYNONYM_AMBIGUITY",
    "COLUMN_AMBIGUITY",
    "NO_RESOLUTION",
    "ORPHAN_ENTITY",
    "MAPPING_LOW_CONFIDENCE",
    "OTHER",
)
SEVERITIES = ("INFO", "WARN", "ERROR")


def _conn(settings: Optional[Any] = None):
    if settings is not None:
        return mysql.connector.connect(
            host=getattr(settings, "mysql_host", "localhost"),
            port=getattr(settings, "mysql_port", 3306),
            user=getattr(settings, "mysql_user", "root"),
            password=getattr(settings, "mysql_password", ""),
            database=getattr(settings, "mysql_db", "pmos"),
            connection_timeout=10,
        )
    return mysql.connector.connect(
        host=os.environ.get("MYSQL_HOST", "localhost"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ.get("MYSQL_USER", "root"),
        password=os.environ.get("MYSQL_PASSWORD", ""),
        database=os.environ.get("MYSQL_DB", "pmos"),
        connection_timeout=10,
    )


def raise_issue(
    *,
    kind: str,
    title: str,
    description: str = "",
    severity: str = "WARN",
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    raised_by: str = "system",
    raised_trace: Optional[str] = None,
    settings: Optional[Any] = None,
) -> Optional[str]:
    """Insert an OPEN auditor issue. Returns the new issue_id, or None on error."""
    if kind not in ISSUE_KINDS:
        kind = "OTHER"
    if severity not in SEVERITIES:
        severity = "WARN"

    issue_id = str(uuid.uuid4())
    payload_json = None
    if payload is not None:
        try:
            blob = json.dumps(payload, default=str)
            if len(blob) > 8000:
                blob = json.dumps({"_truncated": True, "size": len(blob)})
            payload_json = blob
        except Exception:
            payload_json = json.dumps({"_unserializable": True})

    try:
        c = _conn(settings)
        try:
            cur = c.cursor()
            cur.execute(
                """
                INSERT INTO auditor_issues
                  (issue_id, kind, severity, status, title, description,
                   resource_type, resource_id, payload, raised_by, raised_trace)
                VALUES (%s,%s,%s,'OPEN',%s,%s,%s,%s,%s,%s,%s)
                """,
                (issue_id, kind, severity, title[:255], description[:8000] if description else None,
                 resource_type, resource_id, payload_json, raised_by, raised_trace),
            )
            c.commit()
        finally:
            c.close()
        logger.info(
            "auditor_issue raised",
            extra={
                "issue_id": issue_id, "kind": kind, "severity": severity,
                "trace_id": raised_trace, "title": title[:120],
            },
        )
        return issue_id
    except Exception as exc:
        logger.warning(
            "auditor_issue write failed: %s", exc,
            extra={"kind": kind, "trace_id": raised_trace},
        )
        return None


def find_existing_open(
    *,
    kind: str,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    title: Optional[str] = None,
    settings: Optional[Any] = None,
) -> Optional[str]:
    """Look up an existing OPEN issue with the same kind+resource — used to
    avoid duplicate issues when the same gap surfaces repeatedly.
    """
    try:
        c = _conn(settings)
        try:
            cur = c.cursor()
            sql = "SELECT issue_id FROM auditor_issues WHERE status='OPEN' AND kind=%s"
            params = [kind]
            if resource_type:
                sql += " AND resource_type=%s"
                params.append(resource_type)
            if resource_id:
                sql += " AND resource_id=%s"
                params.append(resource_id)
            if title:
                sql += " AND title=%s"
                params.append(title[:255])
            sql += " ORDER BY raised_at DESC LIMIT 1"
            cur.execute(sql, tuple(params))
            row = cur.fetchone()
            return row[0] if row else None
        finally:
            c.close()
    except Exception as exc:
        logger.warning("auditor_issue dedupe lookup failed: %s", exc)
        return None


def raise_or_dedupe(
    *,
    kind: str,
    title: str,
    description: str = "",
    severity: str = "WARN",
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    raised_by: str = "system",
    raised_trace: Optional[str] = None,
    settings: Optional[Any] = None,
) -> Optional[str]:
    """Idempotent variant of ``raise_issue``: returns the existing OPEN
    issue's id if one matches the (kind, resource_type, resource_id, title)
    tuple; otherwise creates a new one. Use this from any path that may run
    repeatedly (e.g. each user question that hits the same ambiguity).
    """
    existing = find_existing_open(
        kind=kind,
        resource_type=resource_type,
        resource_id=resource_id,
        title=title,
        settings=settings,
    )
    if existing:
        return existing
    return raise_issue(
        kind=kind, title=title, description=description, severity=severity,
        resource_type=resource_type, resource_id=resource_id,
        payload=payload, raised_by=raised_by, raised_trace=raised_trace,
        settings=settings,
    )
