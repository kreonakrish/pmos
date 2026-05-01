"""Per-conversation blackboard (Phase A — perpetual agentic loop, Property 6).

A live Redis stream that lets agents on the same conversation see each other's
intermediate findings — discovered entities, tool result summaries, bid contract
violations, and orchestrator-published decomposition revisions — *while they are
still executing*. The pre-existing pipeline only exposed final node results to
sibling agents at Step 8 aggregation, which is too late.

Stream key:    ``pmos:blackboard:<conversation_id>``
Stream maxlen: 500 (approximate; older entries trimmed).
Producers:     sandbox (per-iteration tool result), pipeline (decomposition revised),
               course corrector (auto-correct).
Consumers:     sandbox loop reads new entries before each LLM turn.

Design contract:
  * ``publish()`` and ``consume_new()`` NEVER raise. Observability must not
    break the inner agent loop.
  * ``consume_new()`` is non-blocking — call between LLM turns; never blocks
    the event loop.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional, Tuple

from app.adapters.redis_adapter import RedisAdapter
from app.utils.logger import logger


STREAM_PREFIX = "pmos:blackboard:"
STREAM_MAXLEN = 500
DEFAULT_READ_COUNT = 20
DEFAULT_READ_BLOCK_MS = 50  # non-blocking-ish; returns fast if nothing new


def stream_key(conversation_id: str) -> str:
    return f"{STREAM_PREFIX}{conversation_id}"


# ---------------------------------------------------------------------------
# Producer
# ---------------------------------------------------------------------------


async def publish(
    redis: Optional[RedisAdapter],
    *,
    conversation_id: str,
    kind: str,
    agent_id: str = "",
    agent_name: str = "",
    node_id: str = "",
    iteration: int = 0,
    payload: Optional[Dict[str, Any]] = None,
    trace_id: str = "",
) -> Optional[str]:
    """XADD a blackboard message. Returns the new entry id, or None on failure."""
    if redis is None or not conversation_id:
        return None
    try:
        body: Dict[str, Any] = {
            "kind": kind,
            "agent_id": agent_id or "",
            "agent_name": agent_name or "",
            "node_id": node_id or "",
            "iteration": str(int(iteration or 0)),
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
            "payload": json.dumps(payload or {}, default=str),
        }
        return await redis.publish_to_stream(
            stream_key(conversation_id),
            body,
            trace_id=trace_id,
            maxlen=STREAM_MAXLEN,
        )
    except Exception as exc:
        try:
            logger.warning(
                "blackboard_publish_failed",
                layer="service",
                conversation_id=conversation_id,
                kind=kind,
                error=str(exc)[:300],
                trace_id=trace_id,
            )
        except Exception:
            pass
        return None


# ---------------------------------------------------------------------------
# Consumer
# ---------------------------------------------------------------------------


async def consume_new(
    redis: Optional[RedisAdapter],
    *,
    conversation_id: str,
    last_id: str = "0",
    count: int = DEFAULT_READ_COUNT,
    block_ms: int = DEFAULT_READ_BLOCK_MS,
    exclude_agent_id: str = "",
) -> Tuple[List[Dict[str, Any]], str]:
    """XREAD new blackboard entries since ``last_id``.

    Returns ``(decoded_entries, new_cursor)``. If nothing new, the cursor is
    unchanged. ``exclude_agent_id`` filters out entries the caller themselves
    produced so an agent doesn't read its own publishes back.
    """
    if redis is None or redis._client is None or not conversation_id:
        return [], last_id

    try:
        results = await redis._client.xread(
            {stream_key(conversation_id): last_id},
            count=count,
            block=block_ms,
        )
    except Exception as exc:
        try:
            logger.warning(
                "blackboard_consume_failed",
                layer="service",
                conversation_id=conversation_id,
                error=str(exc)[:300],
            )
        except Exception:
            pass
        return [], last_id

    if not results:
        return [], last_id

    decoded: List[Dict[str, Any]] = []
    cursor = last_id
    for _, messages in results:
        for msg_id, raw in messages:
            cursor = msg_id
            entry = _decode(raw, msg_id)
            if exclude_agent_id and entry.get("agent_id") == exclude_agent_id:
                continue
            decoded.append(entry)
    return decoded, cursor


def _decode(raw: Dict[str, Any], msg_id: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {"redis_id": msg_id}
    for k, v in (raw.items() if isinstance(raw, dict) else []):
        if k == "payload" and isinstance(v, str):
            try:
                out["payload"] = json.loads(v)
                continue
            except Exception:
                pass
        if k == "iteration" and isinstance(v, str):
            try:
                out[k] = int(v)
                continue
            except Exception:
                pass
        out[k] = v
    return out


# ---------------------------------------------------------------------------
# Context formatter — turn N entries into a single user-message string.
# ---------------------------------------------------------------------------


def format_team_context(entries: List[Dict[str, Any]], *, max_entries: int = 10) -> str:
    """Render blackboard entries as a compact team-context string.

    Used by the sandbox loop as a synthetic ``user`` message injected before the
    next LLM turn. Keep it short so it doesn't dominate the prompt.
    """
    if not entries:
        return ""
    lines: List[str] = ["[TEAM CONTEXT UPDATES — what your teammates have reported since your last turn]"]
    for e in entries[:max_entries]:
        agent = e.get("agent_name") or e.get("agent_id") or "teammate"
        kind = e.get("kind") or "update"
        payload = e.get("payload") or {}
        summary = payload.get("summary") or payload.get("text") or ""
        if isinstance(summary, str) and len(summary) > 240:
            summary = summary[:240] + "…"
        # Compact one-liner per entry; the LLM can ask for more if it cares.
        if summary:
            lines.append(f"- [{kind}] {agent}: {summary}")
        else:
            # Show the kind + a couple payload keys so the LLM knows what's there.
            keys = ", ".join(list(payload.keys())[:5]) if isinstance(payload, dict) else ""
            lines.append(f"- [{kind}] {agent} (keys: {keys})")
    if len(entries) > max_entries:
        lines.append(f"- …{len(entries) - max_entries} more entries omitted")
    lines.append("[END TEAM CONTEXT]")
    return "\n".join(lines)
