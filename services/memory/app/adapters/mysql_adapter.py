"""MySQL adapter — wraps mysql-connector-python with async-friendly context managers."""
from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from typing import Any, Generator, Optional

import mysql.connector
from mysql.connector import pooling

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger()

_pool: Optional[pooling.MySQLConnectionPool] = None
_pool_lock = asyncio.Lock()


def _get_pool() -> pooling.MySQLConnectionPool:
    global _pool
    if _pool is None:
        _pool = pooling.MySQLConnectionPool(
            pool_name="memory_pool",
            pool_size=5,
            host=settings.mysql_host,
            port=settings.mysql_port,
            database=settings.mysql_db,
            user=settings.mysql_user,
            password=settings.mysql_password,
            charset="utf8mb4",
            collation="utf8mb4_unicode_ci",
            autocommit=False,
        )
        logger.info(
            "MySQL connection pool created",
            layer="adapter",
            host=settings.mysql_host,
            db=settings.mysql_db,
        )
    return _pool


class MySQLAdapter:
    """Sync MySQL adapter. For async FastAPI handlers wrap calls via run_in_executor."""

    def execute(
        self,
        query: str,
        params: tuple | None = None,
        fetch: bool = False,
        fetch_one: bool = False,
    ) -> Any:
        pool = _get_pool()
        conn = pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(query, params or ())
            if fetch_one:
                result = cursor.fetchone()
            elif fetch:
                result = cursor.fetchall()
            else:
                conn.commit()
                result = cursor.lastrowid
            return result
        except Exception as exc:
            conn.rollback()
            logger.error("MySQL execute error", layer="adapter", error=str(exc), query=query)
            raise
        finally:
            cursor.close()
            conn.close()

    def executemany(self, query: str, params_list: list[tuple]) -> None:
        pool = _get_pool()
        conn = pool.get_connection()
        cursor = conn.cursor()
        try:
            cursor.executemany(query, params_list)
            conn.commit()
        except Exception as exc:
            conn.rollback()
            logger.error("MySQL executemany error", layer="adapter", error=str(exc))
            raise
        finally:
            cursor.close()
            conn.close()

    def insert(self, table: str, data: dict[str, Any]) -> int:
        cols = ", ".join(data.keys())
        placeholders = ", ".join(["%s"] * len(data))
        query = f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"
        return self.execute(query, tuple(data.values()))

    def select(
        self,
        table: str,
        where: str = "",
        params: tuple = (),
        columns: str = "*",
        limit: int | None = None,
        order_by: str | None = None,
    ) -> list[dict[str, Any]]:
        query = f"SELECT {columns} FROM {table}"
        if where:
            query += f" WHERE {where}"
        if order_by:
            query += f" ORDER BY {order_by}"
        if limit is not None:
            query += f" LIMIT {limit}"
        rows = self.execute(query, params, fetch=True)
        return rows or []

    def update(self, table: str, data: dict[str, Any], where: str, where_params: tuple) -> None:
        set_clause = ", ".join(f"{k} = %s" for k in data.keys())
        query = f"UPDATE {table} SET {set_clause} WHERE {where}"
        self.execute(query, tuple(data.values()) + where_params)


class AsyncMySQLAdapter:
    """Thin async wrapper — executes sync calls in a thread pool executor."""

    def __init__(self) -> None:
        self._sync = MySQLAdapter()
        self._executor = None  # uses default executor

    async def execute(self, query: str, params: tuple | None = None, fetch: bool = False, fetch_one: bool = False) -> Any:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor, self._sync.execute, query, params, fetch, fetch_one
        )

    async def insert(self, table: str, data: dict[str, Any]) -> int:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, self._sync.insert, table, data)

    async def select(
        self,
        table: str,
        where: str = "",
        params: tuple = (),
        columns: str = "*",
        limit: int | None = None,
        order_by: str | None = None,
    ) -> list[dict[str, Any]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor, self._sync.select, table, where, params, columns, limit, order_by
        )

    async def update(self, table: str, data: dict[str, Any], where: str, where_params: tuple) -> None:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor, self._sync.update, table, data, where, where_params
        )


_mysql_adapter: Optional[AsyncMySQLAdapter] = None


def get_mysql_adapter() -> AsyncMySQLAdapter:
    global _mysql_adapter
    if _mysql_adapter is None:
        _mysql_adapter = AsyncMySQLAdapter()
    return _mysql_adapter
