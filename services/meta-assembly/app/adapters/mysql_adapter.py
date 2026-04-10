"""MySQL adapter for capability_registry writes."""
from __future__ import annotations

import json
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

import mysql.connector
from mysql.connector import Error as MySQLError

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(layer="adapter")


class MySQLAdapter:
    """Thin async-friendly wrapper around mysql-connector-python."""

    def _get_connection(self) -> mysql.connector.MySQLConnection:
        return mysql.connector.connect(
            host=settings.mysql_host,
            port=settings.mysql_port,
            database=settings.mysql_db,
            user=settings.mysql_user,
            password=settings.mysql_password,
            connection_timeout=10,
        )

    async def execute(
        self,
        query: str,
        params: tuple[Any, ...] = (),
        trace_id: str = "",
    ) -> int:
        """Execute a write query; returns last-insert-id or rowcount."""
        t0 = time.monotonic()
        trace_id = trace_id or str(uuid.uuid4())
        conn: mysql.connector.MySQLConnection | None = None
        cursor = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit()
            result = cursor.lastrowid if cursor.lastrowid else cursor.rowcount
            duration_ms = int((time.monotonic() - t0) * 1000)
            logger.info(
                "mysql_execute_ok",
                trace_id=trace_id,
                duration_ms=duration_ms,
                layer="adapter",
            )
            return result
        except MySQLError as exc:
            duration_ms = int((time.monotonic() - t0) * 1000)
            logger.error(
                "mysql_execute_failed",
                trace_id=trace_id,
                duration_ms=duration_ms,
                error=str(exc),
                layer="adapter",
            )
            raise
        finally:
            if cursor is not None:
                cursor.close()
            if conn is not None:
                conn.close()

    async def fetch_one(
        self,
        query: str,
        params: tuple[Any, ...] = (),
        trace_id: str = "",
    ) -> dict[str, Any] | None:
        """Fetch a single row as a dict."""
        trace_id = trace_id or str(uuid.uuid4())
        conn: mysql.connector.MySQLConnection | None = None
        cursor = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(query, params)
            row = cursor.fetchone()
            return row  # type: ignore[return-value]
        except MySQLError as exc:
            logger.error(
                "mysql_fetch_failed",
                trace_id=trace_id,
                error=str(exc),
                layer="adapter",
            )
            raise
        finally:
            if cursor is not None:
                cursor.close()
            if conn is not None:
                conn.close()

    async def insert_capability(
        self,
        capability_id: str,
        capability_type: str,
        name: str,
        description: str,
        spec_json: dict[str, Any],
        gap_id: str,
        validation_score: float,
        trace_id: str = "",
    ) -> None:
        """Insert a row into capability_registry."""
        query = """
            INSERT INTO capability_registry
                (capability_id, capability_type, name, description, spec_json,
                 source, gap_id, validation_score, is_active, created_at)
            VALUES (%s, %s, %s, %s, %s, 'DYNAMIC', %s, %s, TRUE, NOW())
        """
        params = (
            capability_id,
            capability_type,
            name,
            description,
            json.dumps(spec_json),
            gap_id,
            validation_score,
        )
        await self.execute(query, params, trace_id=trace_id)
