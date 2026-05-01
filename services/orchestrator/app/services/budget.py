"""Per-conversation cost budget (Phase B.2 — principled sub-agent termination).

Tracks total LLM tokens spent across a conversation in a single Redis hash so
the agent loop can refuse further sub-agent spawns once the cap is hit. Pairs
with a score-plateau check in the orchestrator's outer loop: if the team has
spent N tokens without lifting the average node score by ε in two consecutive
rounds, stop iterating regardless of the round cap.

Design contract:
  * All operations NEVER raise. A flaky redis must not block the agent loop.
  * Increments are atomic via Redis HINCRBY.
  * One hash per conversation_id, expires after 24h (TTL).

Hash key:    ``pmos:budget:<conversation_id>``
Hash fields: tokens_in, tokens_out, sub_agent_spawns, conversations_started_at
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from app.adapters.redis_adapter import RedisAdapter
from app.utils.logger import logger


HASH_PREFIX = "pmos:budget:"
DEFAULT_TTL_SEC = 24 * 60 * 60  # 24h

# Per-conversation caps. Generous enough that ordinary multi-round runs
# don't trip them; tight enough to bound cost when an outer loop is
# iterating a hard question. Tunable via env later if needed.
DEFAULT_TOKEN_CAP = 250_000          # input + output combined
DEFAULT_SUB_AGENT_SPAWN_CAP = 8      # max sub-agent calls per conversation


def hash_key(conversation_id: str) -> str:
    return f"{HASH_PREFIX}{conversation_id}"


async def add_tokens(
    redis: Optional[RedisAdapter],
    *,
    conversation_id: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
) -> None:
    """Atomically add input/output tokens to the conversation's running tally.

    First call also stamps the start time + sets a 24h TTL so we don't leak
    keys on stale conversations.
    """
    if redis is None or redis._client is None or not conversation_id:
        return
    try:
        key = hash_key(conversation_id)
        pipe = redis._client.pipeline()
        if tokens_in:
            pipe.hincrby(key, "tokens_in", int(tokens_in))
        if tokens_out:
            pipe.hincrby(key, "tokens_out", int(tokens_out))
        # Set start_at only if missing (HSETNX), and refresh TTL.
        pipe.hsetnx(
            key,
            "started_at",
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        pipe.expire(key, DEFAULT_TTL_SEC)
        await pipe.execute()
    except Exception as exc:
        try:
            logger.warning(
                "budget_add_tokens_failed",
                layer="service",
                conversation_id=conversation_id,
                error=str(exc)[:300],
            )
        except Exception:
            pass


async def add_sub_agent_spawn(
    redis: Optional[RedisAdapter],
    *,
    conversation_id: str,
) -> None:
    """Increment the sub-agent spawn counter for this conversation."""
    if redis is None or redis._client is None or not conversation_id:
        return
    try:
        key = hash_key(conversation_id)
        pipe = redis._client.pipeline()
        pipe.hincrby(key, "sub_agent_spawns", 1)
        pipe.expire(key, DEFAULT_TTL_SEC)
        await pipe.execute()
    except Exception:
        pass


async def get(
    redis: Optional[RedisAdapter],
    *,
    conversation_id: str,
) -> Dict[str, Any]:
    """Fetch the current budget snapshot. Returns zeros when the hash is empty."""
    if redis is None or redis._client is None or not conversation_id:
        return {"tokens_in": 0, "tokens_out": 0, "sub_agent_spawns": 0}
    try:
        raw = await redis._client.hgetall(hash_key(conversation_id))
    except Exception:
        raw = {}
    return {
        "tokens_in": int(raw.get("tokens_in") or 0),
        "tokens_out": int(raw.get("tokens_out") or 0),
        "sub_agent_spawns": int(raw.get("sub_agent_spawns") or 0),
        "started_at": raw.get("started_at") or "",
    }


async def can_spawn_sub_agent(
    redis: Optional[RedisAdapter],
    *,
    conversation_id: str,
    token_cap: int = DEFAULT_TOKEN_CAP,
    spawn_cap: int = DEFAULT_SUB_AGENT_SPAWN_CAP,
) -> Dict[str, Any]:
    """Decide whether a new sub-agent spawn is allowed.

    Returns ``{"allowed": bool, "reason": str, "snapshot": {…}}``. The reason
    is empty when allowed; otherwise names which cap tripped so the timeline
    UI can surface it.
    """
    snap = await get(redis, conversation_id=conversation_id)
    total_tokens = snap["tokens_in"] + snap["tokens_out"]
    if total_tokens >= token_cap:
        return {
            "allowed": False,
            "reason": f"token_cap_reached ({total_tokens}/{token_cap})",
            "snapshot": snap,
        }
    if snap["sub_agent_spawns"] >= spawn_cap:
        return {
            "allowed": False,
            "reason": f"sub_agent_spawn_cap_reached ({snap['sub_agent_spawns']}/{spawn_cap})",
            "snapshot": snap,
        }
    return {"allowed": True, "reason": "", "snapshot": snap}
