"""Pipeline event publisher (Phase A — perpetual agentic loop observability).

Every meaningful action in the orchestrator/sandbox/course-corrector publishes a
typed event so the UI can render a live Decomposition Timeline. Two sinks:

* MySQL ``pipeline_events`` — durable replay log keyed by ``conversation_id``.
* Redis stream ``pmos:events:<conversation_id>`` — live SSE feed.

Design contract (must always hold):
  * ``publish()`` NEVER raises. Observability must not break the pipeline.
  * MySQL inserts run in a thread executor (mysql.connector is sync).
  * Redis publish reuses the existing async RedisAdapter.
  * Both sinks are best-effort — a failure in one does not block the other.

Event ``kind`` taxonomy (Phase A scope; phases B/C extend):
  decomposition.created, decomposition.revised,
  bid.opened, bid.closed,
  agent.iteration, tool.call, tool.result,
  score.evaluated, sufficiency.checked,
  blackboard.published, memory.refreshed,
  pipeline.completed
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Dict, Optional

import mysql.connector

from app.adapters.redis_adapter import RedisAdapter
from app.config import settings
from app.utils.logger import logger


_PAYLOAD_BYTE_CAP = 16 * 1024  # 16KB — slightly larger than audit_events (8KB)
                               # because timeline events carry sub-task lists.


def _safe_json(payload: Optional[Dict[str, Any]]) -> Optional[str]:
    """Serialize payload, truncating string values past the cap. Never raises."""
    if payload is None:
        return None
    try:
        s = json.dumps(payload, default=str)
    except Exception as exc:
        return json.dumps({"__events_serialize_error": str(exc)[:200]})

    if len(s.encode("utf-8")) <= _PAYLOAD_BYTE_CAP:
        return s

    try:
        trimmed: Dict[str, Any] = {}
        for k, v in (payload.items() if isinstance(payload, dict) else []):
            if isinstance(v, str) and len(v) > 1024:
                trimmed[k] = v[:1024] + "...<truncated>"
            elif isinstance(v, list) and len(v) > 50:
                trimmed[k] = v[:50] + ["...<truncated>"]
            else:
                trimmed[k] = v
        s2 = json.dumps(trimmed, default=str)
        if len(s2.encode("utf-8")) <= _PAYLOAD_BYTE_CAP:
            return s2
    except Exception:
        pass

    return json.dumps({
        "__events_truncated": True,
        "original_size_bytes": len(s.encode("utf-8")),
        "preview": s[:1024],
    })


class EventPublisher:
    """Async-safe publisher for pipeline_events + Redis events stream."""

    # Stream key pattern. Kept as classvar so callers can reference it.
    STREAM_PREFIX = "pmos:events:"

    def __init__(self, redis: Optional[RedisAdapter], mysql_settings: Any) -> None:
        self._redis = redis
        self._cfg = {
            "host": getattr(mysql_settings, "mysql_host", "localhost"),
            "port": getattr(mysql_settings, "mysql_port", 3306),
            "user": getattr(mysql_settings, "mysql_user", "root"),
            "password": getattr(mysql_settings, "mysql_password", ""),
            "database": getattr(mysql_settings, "mysql_db", "pmos"),
        }

    @classmethod
    def stream_key(cls, conversation_id: str) -> str:
        return f"{cls.STREAM_PREFIX}{conversation_id}"

    # ------------------------------------------------------------------
    # Sync MySQL insert (runs in thread executor)
    # ------------------------------------------------------------------
    def _insert_sync(
        self,
        event_id: str,
        trace_id: str,
        conversation_id: str,
        graph_id: Optional[str],
        node_id: Optional[str],
        iteration: int,
        round_n: int,
        kind: str,
        status: str,
        payload_json: Optional[str],
    ) -> None:
        conn = mysql.connector.connect(connection_timeout=5, **self._cfg)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO pipeline_events
                    (event_id, trace_id, conversation_id, graph_id, node_id,
                     iteration, round, kind, status, payload)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    event_id, trace_id, conversation_id, graph_id, node_id,
                    iteration, round_n, kind, status, payload_json,
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
    # Public async publish
    # ------------------------------------------------------------------
    async def publish(
        self,
        *,
        conversation_id: str,
        kind: str,
        trace_id: str = "",
        graph_id: Optional[str] = None,
        node_id: Optional[str] = None,
        iteration: int = 0,
        round_n: int = 0,
        status: str = "IN_PROGRESS",
        payload: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Publish one timeline event. Returns event_id, or None on full failure.

        NEVER raises. Both sinks are attempted; either failing does not block
        the other.
        """
        event_id = str(uuid.uuid4())
        trace_id = trace_id or str(uuid.uuid4())
        ts_iso = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
        payload_json = _safe_json(payload)

        # Sink 1: MySQL pipeline_events (durable, replayable)
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self._insert_sync,
                event_id,
                trace_id,
                conversation_id,
                graph_id,
                node_id,
                int(iteration or 0),
                int(round_n or 0),
                kind,
                (status or "IN_PROGRESS").upper(),
                payload_json,
            )
        except Exception as exc:
            try:
                logger.warning(
                    "pipeline_event_mysql_failed",
                    layer="events",
                    kind=kind,
                    error=str(exc)[:300],
                    trace_id=trace_id,
                )
            except Exception:
                pass

        # Sink 2: Redis stream (live SSE feed). Only attempted if redis is wired.
        if self._redis is not None and conversation_id:
            try:
                stream = self.stream_key(conversation_id)
                # publish_to_stream flattens dict values via json.dumps; pass
                # primitives directly so the SSE consumer can do one decode.
                await self._redis.publish_to_stream(
                    stream,
                    {
                        "event_id": event_id,
                        "kind": kind,
                        "graph_id": graph_id or "",
                        "node_id": node_id or "",
                        "iteration": str(int(iteration or 0)),
                        "round": str(int(round_n or 0)),
                        "status": (status or "IN_PROGRESS").upper(),
                        "ts": ts_iso,
                        "payload": payload_json or "{}",
                    },
                    trace_id=trace_id,
                    maxlen=5000,
                )
            except Exception as exc:
                try:
                    logger.warning(
                        "pipeline_event_redis_failed",
                        layer="events",
                        kind=kind,
                        error=str(exc)[:300],
                        trace_id=trace_id,
                    )
                except Exception:
                    pass

        return event_id


# Module-level singleton, initialized lazily so unit tests can monkeypatch
# settings/redis before first use.
_publisher_singleton: Optional[EventPublisher] = None


def init_event_publisher(redis: RedisAdapter) -> EventPublisher:
    """Wire the singleton to the live RedisAdapter. Call once at app startup."""
    global _publisher_singleton
    _publisher_singleton = EventPublisher(redis, settings)
    return _publisher_singleton


def get_event_publisher() -> Optional[EventPublisher]:
    """Return the wired publisher, or None if startup hasn't run yet."""
    return _publisher_singleton


class _EventsProxy:
    """Lazy proxy so callers can ``from app.utils.events import events``."""

    async def publish(self, **kwargs: Any) -> Optional[str]:
        pub = _publisher_singleton
        if pub is None:
            # Startup hasn't wired Redis yet — fall back to MySQL-only via a
            # transient publisher. Keeps tests and early-boot calls working.
            try:
                pub = EventPublisher(None, settings)
            except Exception:
                return None
        try:
            return await pub.publish(**kwargs)
        except Exception:
            return None


events = _EventsProxy()
