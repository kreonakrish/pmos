"""Per-task FinOps attribution context for the translator service.

Mirrors services/orchestrator/app/services/finops_context.py — see that
module for the full design rationale. Used by the translator's LLM adapter
to attach conversation_id / user_id / team_id / trace_id to every LLM call
without threading those args through every method on the pipeline.
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
    return {
        "trace_id": _trace_id.get(),
        "conversation_id": _conversation_id.get(),
        "user_id": _user_id.get(),
        "team_id": _team_id.get(),
        "agent_id": _agent_id.get(),
    }
