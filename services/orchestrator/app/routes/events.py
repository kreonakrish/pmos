"""Pipeline events endpoints — live SSE stream + replay (Phase A).

Surfaces the typed events emitted by ``app.utils.events.EventPublisher`` so the
client's Decomposition Timeline view can render the agentic loop's progress.

Two endpoints:

* ``GET /v1/events/conversations/{conversation_id}/stream`` — Server-Sent Events.
  Tails the Redis stream ``pmos:events:<conversation_id>`` from a configurable
  starting point (``last_event_id`` query param, default ``$`` = only new
  messages). Each SSE message is one event.

* ``GET /v1/events/conversations/{conversation_id}/replay`` — JSON list of all
  events for this conversation, sourced from MySQL ``pipeline_events`` so the
  UI can reconstruct a completed timeline without keeping the stream alive.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional

import mysql.connector
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import settings
from app.utils.events import EventPublisher
from app.utils.logger import logger

router = APIRouter(prefix="/v1/events", tags=["events"])


# ---------------------------------------------------------------------------
# Live SSE stream
# ---------------------------------------------------------------------------


def _format_sse(event: Dict[str, Any], event_id: str) -> str:
    """Format one event as an SSE message. Each line is `field: value`."""
    data = json.dumps(event, default=str)
    # SSE spec: id + event + data + blank line.
    return f"id: {event_id}\nevent: {event.get('kind', 'pipeline.event')}\ndata: {data}\n\n"


async def _tail_stream(
    redis_client: Any,
    stream: str,
    last_id: str,
    block_ms: int = 15000,
) -> AsyncGenerator[bytes, None]:
    """Yield SSE-formatted bytes from the Redis stream.

    Falls through with a heartbeat when ``XREAD`` blocks long enough so the
    HTTP connection stays alive behind proxies that close idle sockets.
    """
    cursor = last_id
    # Initial comment so the EventSource fires `open` and proxies flush headers.
    yield b": connected\n\n"

    while True:
        try:
            results = await redis_client.xread(
                {stream: cursor},
                count=20,
                block=block_ms,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "events_sse_xread_error",
                layer="router",
                stream=stream,
                error=str(exc)[:300],
            )
            # Brief pause then retry — don't hammer redis if it's flapping.
            await asyncio.sleep(1)
            yield b": redis-retry\n\n"
            continue

        if not results:
            # Heartbeat keeps middleboxes from killing the connection.
            yield b": heartbeat\n\n"
            continue

        for _, messages in results:
            for msg_id, raw in messages:
                cursor = msg_id
                event = _decode_redis_event(raw, msg_id)
                yield _format_sse(event, msg_id).encode("utf-8")
                # If the pipeline signals completion, the client can choose to
                # close the stream. We still keep yielding in case more events
                # arrive (e.g. delayed memory writes).


def _decode_redis_event(raw: Dict[str, Any], msg_id: str) -> Dict[str, Any]:
    """Best-effort decode of Redis stream message back into the publisher's shape."""
    # publish_to_stream stringifies non-string values; payload is JSON-string.
    out: Dict[str, Any] = {"redis_id": msg_id}
    for k, v in (raw.items() if isinstance(raw, dict) else []):
        if k == "payload" and isinstance(v, str):
            try:
                out["payload"] = json.loads(v)
                continue
            except Exception:
                pass
        if k in ("iteration", "round") and isinstance(v, str):
            try:
                out[k] = int(v)
                continue
            except Exception:
                pass
        out[k] = v
    return out


@router.get("/conversations/{conversation_id}/stream")
async def stream_events(
    conversation_id: str,
    request: Request,
    last_event_id: Optional[str] = Query(default=None),
) -> StreamingResponse:
    """Live SSE feed of pipeline events for one conversation.

    The browser ``EventSource`` API automatically reconnects with the
    ``Last-Event-ID`` header on disconnect; we honor it via the
    ``last_event_id`` query param too for explicit control.
    """
    if not conversation_id or len(conversation_id) > 255:
        raise HTTPException(400, "invalid conversation_id")

    redis = request.app.state.redis
    if redis is None or redis._client is None:
        raise HTTPException(503, "redis not connected")

    stream = EventPublisher.stream_key(conversation_id)
    # Prefer header (set automatically by browsers on reconnect), fall back to
    # query param, default to ``$`` which means "only events arriving from now".
    cursor = (
        request.headers.get("last-event-id")
        or last_event_id
        or "$"
    )

    async def gen() -> AsyncGenerator[bytes, None]:
        async for chunk in _tail_stream(redis._client, stream, cursor):
            if await request.is_disconnected():
                logger.info(
                    "events_sse_client_disconnected",
                    layer="router",
                    conversation_id=conversation_id,
                )
                return
            yield chunk

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            # Disable nginx buffering so events flush immediately.
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


# ---------------------------------------------------------------------------
# Replay from MySQL
# ---------------------------------------------------------------------------


def _mysql_cfg() -> Dict[str, Any]:
    return {
        "host": getattr(settings, "mysql_host", "localhost"),
        "port": getattr(settings, "mysql_port", 3306),
        "user": getattr(settings, "mysql_user", "root"),
        "password": getattr(settings, "mysql_password", ""),
        "database": getattr(settings, "mysql_db", "pmos"),
    }


def _replay_sync(conversation_id: str, limit: int) -> List[Dict[str, Any]]:
    """Synchronous fetch of replay rows. Runs in a thread executor."""
    conn = mysql.connector.connect(connection_timeout=5, **_mysql_cfg())
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT event_id, trace_id, conversation_id, graph_id, node_id,
                   iteration, round, kind, status, payload, ts
            FROM pipeline_events
            WHERE conversation_id = %s
            ORDER BY ts ASC, event_id ASC
            LIMIT %s
            """,
            (conversation_id, int(limit)),
        )
        rows = cur.fetchall()
        cur.close()
        return rows
    finally:
        try:
            conn.close()
        except Exception:
            pass


@router.get("/conversations/{conversation_id}/replay")
async def replay_events(
    conversation_id: str,
    limit: int = Query(default=2000, ge=1, le=10000),
) -> JSONResponse:
    """Reconstruct the timeline for a conversation from MySQL."""
    if not conversation_id or len(conversation_id) > 255:
        raise HTTPException(400, "invalid conversation_id")

    try:
        loop = asyncio.get_event_loop()
        rows = await loop.run_in_executor(None, _replay_sync, conversation_id, limit)
    except Exception as exc:
        logger.error(
            "events_replay_failed",
            layer="router",
            conversation_id=conversation_id,
            error=str(exc)[:300],
        )
        raise HTTPException(500, "replay failed")

    # Decode payload JSON from MySQL string column for client convenience.
    decoded: List[Dict[str, Any]] = []
    for r in rows:
        payload = r.get("payload")
        if isinstance(payload, str):
            try:
                r["payload"] = json.loads(payload)
            except Exception:
                pass
        # Datetime → ISO for JSON.
        ts = r.get("ts")
        if hasattr(ts, "isoformat"):
            r["ts"] = ts.isoformat()
        decoded.append(r)

    return JSONResponse({"conversation_id": conversation_id, "events": decoded})
