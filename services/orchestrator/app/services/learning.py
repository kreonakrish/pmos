"""Durable learning artifact writer (Phase C.2 — perpetual agentic loop).

Writes three kinds of structured artifacts at the end of each successful
outer-loop round so the next conversation on a similar question can
short-circuit work the team has already done:

* ``entity_resolution_log`` — resolved phrase → canonical_entity per intent.
* ``effective_decompositions`` — sub-task list that produced sufficient=true.
* ``agent_tool_affinity`` — per-(agent, tool, intent) score evidence.

Design contract:
  * All writes are best-effort. NEVER raise — durable learning must not
    break the live response.
  * MySQL inserts run in a thread executor (mysql.connector is sync).
  * Each writer returns the number of rows inserted so the caller can
    publish a ``memory.written`` event with concrete counts.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Iterable, List, Optional

import mysql.connector

from app.config import settings
from app.utils.logger import logger


def _cfg() -> Dict[str, Any]:
    return {
        "host": getattr(settings, "mysql_host", "localhost"),
        "port": getattr(settings, "mysql_port", 3306),
        "user": getattr(settings, "mysql_user", "root"),
        "password": getattr(settings, "mysql_password", ""),
        "database": getattr(settings, "mysql_db", "pmos"),
    }


# ---------------------------------------------------------------------------
# entity_resolution_log
# ---------------------------------------------------------------------------


def _insert_entity_resolutions_sync(rows: List[Dict[str, Any]]) -> int:
    if not rows:
        return 0
    conn = mysql.connector.connect(connection_timeout=5, **_cfg())
    inserted = 0
    try:
        cur = conn.cursor()
        for r in rows:
            try:
                cur.execute(
                    """
                    INSERT INTO entity_resolution_log
                        (conversation_id, graph_id, intent, raw_phrase,
                         canonical_entity, ontology_version, score, source)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        r.get("conversation_id"),
                        r.get("graph_id"),
                        r.get("intent"),
                        (r.get("raw_phrase") or "")[:500],
                        (r.get("canonical_entity") or "")[:500] or None,
                        (r.get("ontology_version") or "")[:60] or None,
                        r.get("score"),
                        (r.get("source") or "pipeline")[:60],
                    ),
                )
                inserted += 1
            except Exception:
                continue
        conn.commit()
        cur.close()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return inserted


async def write_entity_resolutions(rows: List[Dict[str, Any]]) -> int:
    if not rows:
        return 0
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _insert_entity_resolutions_sync, rows)
    except Exception as exc:
        try:
            logger.warning(
                "entity_resolution_write_failed",
                layer="service",
                error=str(exc)[:300],
            )
        except Exception:
            pass
        return 0


# ---------------------------------------------------------------------------
# effective_decompositions
# ---------------------------------------------------------------------------


def _insert_effective_decomposition_sync(row: Dict[str, Any]) -> int:
    conn = mysql.connector.connect(connection_timeout=5, **_cfg())
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO effective_decompositions
                (conversation_id, graph_id, intent, user_question,
                 subtask_list, n_subtasks, rounds_to_success, avg_score)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                row.get("conversation_id"),
                row.get("graph_id"),
                (row.get("intent") or "")[:120] or None,
                (row.get("user_question") or "")[:8000],
                json.dumps(row.get("subtask_list") or [], default=str),
                int(row.get("n_subtasks") or 0),
                int(row.get("rounds_to_success") or 1),
                row.get("avg_score"),
            ),
        )
        conn.commit()
        cur.close()
        return 1
    finally:
        try:
            conn.close()
        except Exception:
            pass


async def write_effective_decomposition(row: Dict[str, Any]) -> int:
    if not row or not row.get("graph_id"):
        return 0
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, _insert_effective_decomposition_sync, row
        )
    except Exception as exc:
        try:
            logger.warning(
                "effective_decomposition_write_failed",
                layer="service",
                error=str(exc)[:300],
            )
        except Exception:
            pass
        return 0


# ---------------------------------------------------------------------------
# agent_tool_affinity
# ---------------------------------------------------------------------------


def _insert_agent_tool_affinity_sync(rows: List[Dict[str, Any]]) -> int:
    if not rows:
        return 0
    conn = mysql.connector.connect(connection_timeout=5, **_cfg())
    inserted = 0
    try:
        cur = conn.cursor()
        for r in rows:
            try:
                cur.execute(
                    """
                    INSERT INTO agent_tool_affinity
                        (agent_id, agent_name, tool_id, tool_name,
                         intent, score, success, graph_id, node_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        (r.get("agent_id") or "")[:36] or None,
                        (r.get("agent_name") or "")[:255] or None,
                        (r.get("tool_id") or "")[:36] or None,
                        (r.get("tool_name") or "")[:255] or None,
                        (r.get("intent") or "")[:120] or None,
                        float(r.get("score") or 0.0),
                        1 if r.get("success", True) else 0,
                        r.get("graph_id"),
                        r.get("node_id"),
                    ),
                )
                inserted += 1
            except Exception:
                continue
        conn.commit()
        cur.close()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return inserted


async def write_agent_tool_affinity(rows: List[Dict[str, Any]]) -> int:
    if not rows:
        return 0
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _insert_agent_tool_affinity_sync, rows)
    except Exception as exc:
        try:
            logger.warning(
                "agent_tool_affinity_write_failed",
                layer="service",
                error=str(exc)[:300],
            )
        except Exception:
            pass
        return 0


# ---------------------------------------------------------------------------
# Convenience: build affinity rows from node_results.
# ---------------------------------------------------------------------------


def affinity_rows_from_results(
    node_results: Iterable[Dict[str, Any]],
    *,
    graph_id: str,
    intent: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Project the node_results list into agent_tool_affinity rows.

    One row per (node, tool) pair where the node ended SUCCESS / AUTO_CORRECTED
    AND we know which tools the agent actually called. Skips below-band and
    failed nodes — we only learn from what worked.
    """
    rows: List[Dict[str, Any]] = []
    for nr in node_results or []:
        status = (nr.get("status") or "").upper()
        if status not in ("SUCCESS", "AUTO_CORRECTED"):
            continue
        score = nr.get("score")
        if score is None:
            continue
        agent_id = nr.get("agent_id") or ""
        agent_name = nr.get("agent_name") or ""
        tools = nr.get("tools_used") or []
        # tools_used is a list of tool names from the sandbox; we don't have
        # tool_id at this level, but the affinity table tolerates NULL
        # tool_id. Future extension can join through agent-mgmt to fill it.
        for tool_name in tools:
            rows.append({
                "agent_id": str(agent_id),
                "agent_name": str(agent_name),
                "tool_id": None,
                "tool_name": str(tool_name)[:255],
                "intent": intent,
                "score": float(score),
                "success": True,
                "graph_id": graph_id,
                "node_id": nr.get("node_id"),
            })
    return rows
