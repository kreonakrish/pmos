"""Per-task FinOps attribution context.

The orchestrator makes ~12 distinct ``await self._llm.complete(...)`` calls
spread across pipeline.py and capability_negotiation.py. Threading
conversation_id / user_id / team_id / agent_id through every method signature
would be a wide and risky refactor.

contextvars.ContextVar is the right tool here: it is *per asyncio task*, so a
single conversation's pipeline run gets its own attribution that the LLM
adapter reads automatically. The adapter still accepts explicit kwargs which
take precedence when callers want to override (e.g. for sub-agent calls that
need to attribute to a different agent_id than the outer conversation).

Usage:

    from app.services.finops_context import set_finops_context, finops_attribution

    # At the top of a chat request handler:
    with set_finops_context(trace_id=..., conversation_id=..., user_id=...,
                            team_id=..., agent_id=...):
        await pipeline.run(...)

    # Inside the adapter, with no caller kwargs, this returns the active context:
    ctx = finops_attribution()
    # → {"trace_id": "...", "conversation_id": "...", ...}
"""

from __future__ import annotations

import contextlib
from contextvars import ContextVar
from typing import Optional


_trace_id: ContextVar[Optional[str]] = ContextVar("finops_trace_id", default=None)
_conversation_id: ContextVar[Optional[str]] = ContextVar("finops_conversation_id", default=None)
_user_id: ContextVar[Optional[str]] = ContextVar("finops_user_id", default=None)
_team_id: ContextVar[Optional[str]] = ContextVar("finops_team_id", default=None)
_agent_id: ContextVar[Optional[str]] = ContextVar("finops_agent_id", default=None)


@contextlib.contextmanager
def set_finops_context(
    *,
    trace_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    user_id: Optional[str] = None,
    team_id: Optional[str] = None,
    agent_id: Optional[str] = None,
):
    """Like set_finops_context but with proper token-based reset."""
    pairs = []
    if trace_id is not None:
        pairs.append((_trace_id, _trace_id.set(trace_id)))
    if conversation_id is not None:
        pairs.append((_conversation_id, _conversation_id.set(conversation_id)))
    if user_id is not None:
        pairs.append((_user_id, _user_id.set(user_id)))
    if team_id is not None:
        pairs.append((_team_id, _team_id.set(team_id)))
    if agent_id is not None:
        pairs.append((_agent_id, _agent_id.set(agent_id)))
    try:
        yield
    finally:
        for var, tok in reversed(pairs):
            try:
                var.reset(tok)
            except Exception:
                pass


def finops_attribution() -> dict:
    """Snapshot the active FinOps attribution. Returns a dict with all five
    keys (values may be None if not set)."""
    return {
        "trace_id": _trace_id.get(),
        "conversation_id": _conversation_id.get(),
        "user_id": _user_id.get(),
        "team_id": _team_id.get(),
        "agent_id": _agent_id.get(),
    }
