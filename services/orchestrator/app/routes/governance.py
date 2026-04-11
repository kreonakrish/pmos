"""Model governance / inference traceability endpoints.

Aggregates the full reasoning chain for a single trace_id (or message/conversation)
across:
  - Gateway / orchestrator messages (pmos.messages, pmos.conversations)
  - Pipeline execution graph (pmos.execution_graph_log, pmos.task_assignments)
  - Tool calls (pmos.tool_execution_history)
  - Scoring decisions (pmos.score_history)
  - RL feedback (pmos.rl_feedback_log)
  - Episodic memory (pmos.execution_episodes)
  - Neo4j TaskGraph + TaskNodes
  - Agent and tool metadata (pmos.agents, pmos.tools)

Endpoints (all under /v1/governance):
  GET /traces                         — list recent traces
  GET /traces/{trace_id}              — full reasoning chain for a trace
  GET /traces/by-conversation/{id}    — traces for a conversation
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

import mysql.connector
from fastapi import APIRouter, HTTPException, Query, Request

from app.config import settings
from app.utils.logger import logger

router = APIRouter(prefix="/v1/governance", tags=["governance"])


# ── MySQL helper (sync; trace assembly is read-only and infrequent) ──────────
def _mysql_conn():
    return mysql.connector.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_db,
        connection_timeout=10,
    )


def _fetch_all(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    conn = _mysql_conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, params)
        rows = cur.fetchall() or []
        # JSONify any datetime/Decimal/JSON-string fields
        out: List[Dict[str, Any]] = []
        for r in rows:
            clean: Dict[str, Any] = {}
            for k, v in r.items():
                if v is None:
                    clean[k] = None
                elif hasattr(v, "isoformat"):
                    clean[k] = v.isoformat()
                elif isinstance(v, (bytes, bytearray)):
                    try:
                        clean[k] = v.decode("utf-8")
                    except Exception:
                        clean[k] = str(v)
                elif isinstance(v, str) and (v.startswith("{") or v.startswith("[")):
                    try:
                        clean[k] = json.loads(v)
                    except Exception:
                        clean[k] = v
                else:
                    try:
                        json.dumps(v)
                        clean[k] = v
                    except Exception:
                        clean[k] = str(v)
            out.append(clean)
        return out
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _get_neo4j(request: Request):
    return request.app.state.neo4j


def _serialize_neo4j(obj: Any) -> Any:
    """Recursively coerce Neo4j-native types (DateTime, Date, Duration, etc.)
    into JSON-safe primitives.
    """
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _serialize_neo4j(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize_neo4j(v) for v in obj]
    return str(obj)


# ── List recent traces ───────────────────────────────────────────────────────
@router.get("/traces")
async def list_traces(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
) -> Dict[str, Any]:
    """Return the most recent N traces with high-level summary stats."""
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))

    rows = _fetch_all(
        """
        SELECT
          m.trace_id,
          m.conversation_id,
          MAX(m.created_at) AS last_message_at,
          MAX(CASE WHEN m.role='user' THEN m.content END) AS user_request,
          MAX(CASE WHEN m.role='assistant' THEN m.content END) AS assistant_response,
          AVG(m.score) AS avg_score
        FROM messages m
        WHERE m.trace_id IS NOT NULL AND m.trace_id <> ''
        GROUP BY m.trace_id, m.conversation_id
        ORDER BY last_message_at DESC
        LIMIT %s
        """,
        (limit,),
    )

    # Augment with tool-call counts
    for r in rows:
        tid = r.get("trace_id")
        if not tid:
            continue
        tcount = _fetch_all(
            "SELECT COUNT(*) AS n, AVG(latency_ms) AS avg_latency FROM tool_execution_history WHERE trace_id=%s",
            (tid,),
        )
        if tcount:
            r["tool_call_count"] = tcount[0].get("n", 0)
            r["avg_tool_latency_ms"] = tcount[0].get("avg_latency")
        # Trim long content for the listing
        for col in ("user_request", "assistant_response"):
            v = r.get(col)
            if isinstance(v, str) and len(v) > 240:
                r[col] = v[:240] + "..."

    return {"traces": rows, "trace_id": trace_id}


# ── Full reasoning chain for a single trace ──────────────────────────────────
@router.get("/traces/{target_trace_id}")
async def get_trace(
    target_trace_id: str,
    request: Request,
) -> Dict[str, Any]:
    """Return the full inference reasoning chain for a single trace_id.

    The response is structured as a layered timeline so the UI can render
    each hop the orchestrator made before arriving at the final answer.
    """
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    neo4j = _get_neo4j(request)

    # 1. Messages (request + response on this trace)
    messages = _fetch_all(
        """
        SELECT m.message_id, m.conversation_id, m.role, m.content, m.score,
               m.metadata, m.created_at
        FROM messages m
        WHERE m.trace_id = %s
        ORDER BY m.created_at ASC
        """,
        (target_trace_id,),
    )

    conversation_id: Optional[str] = None
    if messages:
        conversation_id = messages[0].get("conversation_id")

    # 2. Conversation context
    conversation: Optional[Dict[str, Any]] = None
    if conversation_id:
        rows = _fetch_all(
            "SELECT conversation_id, user_id, team_id, title, status, created_at FROM conversations WHERE conversation_id=%s",
            (conversation_id,),
        )
        if rows:
            conversation = rows[0]

    # 3. Tool executions on this trace
    tool_calls = _fetch_all(
        """
        SELECT teh.execution_id, teh.tool_id, teh.tool_type, teh.status,
               teh.inputs, teh.output, teh.error_message, teh.latency_ms,
               teh.agent_id, teh.agent_name, teh.team_id, teh.team_name,
               teh.source, teh.created_at,
               t.name AS tool_name, t.description AS tool_description,
               t.endpoint AS tool_endpoint, t.hostname AS tool_hostname
        FROM tool_execution_history teh
        LEFT JOIN tools t ON t.tool_id = teh.tool_id
        WHERE teh.trace_id = %s
        ORDER BY teh.created_at ASC
        """,
        (target_trace_id,),
    )

    # 4. Try to find the matching pipeline execution graph via conversation_id
    graph_id: Optional[str] = None
    session_id: Optional[str] = None
    pipeline_steps: List[Dict[str, Any]] = []
    score_history: List[Dict[str, Any]] = []
    rl_feedback: List[Dict[str, Any]] = []
    episodes: List[Dict[str, Any]] = []

    if conversation_id:
        # Pipeline step rows from execution_graph_log
        steps = _fetch_all(
            """
            SELECT egl.id, egl.graph_id, egl.node_id, egl.session_id, egl.agent_id,
                   egl.iteration, egl.node_type, egl.status, egl.score,
                   egl.execution_time_ms, egl.correction_triggered,
                   egl.auto_corrected, egl.fallback_triggered, egl.created_at,
                   a.name AS agent_name, a.foundation_model
            FROM execution_graph_log egl
            LEFT JOIN agents a ON a.id = egl.agent_id
            WHERE egl.session_id = %s OR egl.session_id = %s
            ORDER BY egl.created_at ASC
            """,
            (conversation_id, f"conv-{conversation_id}"),
        )
        pipeline_steps = steps
        if steps:
            graph_id = steps[0].get("graph_id")
            session_id = steps[0].get("session_id")

        # Score history for any agent that touched this session
        agent_ids = sorted({s["agent_id"] for s in steps if s.get("agent_id")})
        if agent_ids:
            placeholders = ",".join(["%s"] * len(agent_ids))
            score_history = _fetch_all(
                f"""
                SELECT sh.id, sh.agent_id, sh.task_id, sh.context_type, sh.score,
                       sh.factors, sh.band_low, sh.band_high, sh.within_band,
                       sh.correction_triggered, sh.created_at,
                       a.name AS agent_name, a.foundation_model
                FROM score_history sh
                LEFT JOIN agents a ON a.id = sh.agent_id
                WHERE sh.agent_id IN ({placeholders})
                ORDER BY sh.created_at DESC
                LIMIT 50
                """,
                tuple(agent_ids),
            )
            rl_feedback = _fetch_all(
                f"""
                SELECT rl.id, rl.session_id, rl.node_id, rl.agent_id,
                       rl.feedback_source, rl.feedback_type,
                       rl.original_score, rl.adjusted_score, rl.reward_signal,
                       rl.band_low_before, rl.band_high_before,
                       rl.band_low_after, rl.band_high_after,
                       rl.feedback_payload, rl.processed_at
                FROM rl_feedback_log rl
                WHERE rl.agent_id IN ({placeholders})
                ORDER BY rl.processed_at DESC
                LIMIT 50
                """,
                tuple(agent_ids),
            )

        # Episodic memory snapshots
        episodes = _fetch_all(
            """
            SELECT episode_id, agent_id, session_id, task_description,
                   final_output, final_score, outcome, created_at
            FROM execution_episodes
            WHERE session_id = %s
            ORDER BY created_at DESC
            LIMIT 20
            """,
            (conversation_id,),
        )

    # 5. Neo4j TaskGraph + TaskNodes
    graph_node: Optional[Dict[str, Any]] = None
    task_nodes: List[Dict[str, Any]] = []
    task_edges: List[Dict[str, Any]] = []
    interactions: List[Dict[str, Any]] = []
    try:
        # Resolve graph_id via conversation_id if we don't have it from MySQL
        if not graph_id and conversation_id:
            rows = await neo4j.run_query(
                "MATCH (g:TaskGraph {conversation_id: $cid}) RETURN g ORDER BY g.created_at DESC LIMIT 1",
                {"cid": conversation_id},
                trace_id=trace_id,
            )
            if rows:
                graph_node = _serialize_neo4j(dict(rows[0]["g"]))
                graph_id = graph_node.get("graph_id")

        if graph_id:
            if not graph_node:
                rows = await neo4j.run_query(
                    "MATCH (g:TaskGraph {graph_id: $gid}) RETURN g LIMIT 1",
                    {"gid": graph_id},
                    trace_id=trace_id,
                )
                if rows:
                    graph_node = _serialize_neo4j(dict(rows[0]["g"]))

            node_rows = await neo4j.run_query(
                """
                MATCH (n:TaskNode {graph_id: $gid})
                RETURN n ORDER BY n.created_at
                """,
                {"gid": graph_id},
                trace_id=trace_id,
            )
            for r in node_rows or []:
                task_nodes.append(_serialize_neo4j(dict(r["n"])))

            edge_rows = await neo4j.run_query(
                """
                MATCH (a:TaskNode {graph_id: $gid})-[r]->(b:TaskNode {graph_id: $gid})
                RETURN type(r) AS type, a.node_id AS from_id, b.node_id AS to_id
                """,
                {"gid": graph_id},
                trace_id=trace_id,
            )
            task_edges = [_serialize_neo4j(dict(r)) for r in (edge_rows or [])]

            inter_rows = await neo4j.run_query(
                """
                MATCH (n:TaskNode {graph_id: $gid})-[:HAS_INTERACTION]->(i:AgentInteraction)
                RETURN i, n.node_id AS node_id ORDER BY i.timestamp
                """,
                {"gid": graph_id},
                trace_id=trace_id,
            )
            for r in inter_rows or []:
                row = _serialize_neo4j(dict(r["i"]))
                row["node_id"] = r.get("node_id")
                interactions.append(row)
    except Exception as exc:
        logger.warning(
            "Neo4j trace lookup failed (non-fatal)",
            layer="router",
            error=str(exc),
            trace_id=trace_id,
            target_trace_id=target_trace_id,
        )

    # 6. Build the layered reasoning chain (timeline) for the UI
    timeline: List[Dict[str, Any]] = []

    for m in messages:
        timeline.append({
            "layer": "USER_MESSAGE" if m.get("role") == "user" else "ASSISTANT_RESPONSE",
            "ts": m.get("created_at"),
            "title": "User request" if m.get("role") == "user" else "Final response",
            "detail": m.get("content"),
            "score": m.get("score"),
            "source": "messages",
            "ref_id": m.get("message_id"),
        })
    for n in task_nodes:
        timeline.append({
            "layer": "TASK_NODE",
            "ts": n.get("created_at") or n.get("updated_at"),
            "title": f"TaskNode {n.get('node_id','')[:8]} — {n.get('node_type','')}",
            "detail": n.get("description") or n.get("llm_response", ""),
            "score": n.get("score"),
            "source": "neo4j:TaskNode",
            "ref_id": n.get("node_id"),
            "agent": n.get("assigned_agent_name"),
            "status": n.get("status"),
        })
    for s in pipeline_steps:
        timeline.append({
            "layer": "PIPELINE_STEP",
            "ts": s.get("created_at"),
            "title": f"Pipeline step on node {str(s.get('node_id',''))[:8]}",
            "detail": f"agent={s.get('agent_name','?')} model={s.get('foundation_model','?')} corrected={s.get('correction_triggered')} auto={s.get('auto_corrected')}",
            "score": s.get("score"),
            "source": "execution_graph_log",
            "ref_id": str(s.get("id")),
            "agent": s.get("agent_name"),
            "status": s.get("status"),
        })
    for tc in tool_calls:
        timeline.append({
            "layer": "TOOL_CALL",
            "ts": tc.get("created_at"),
            "title": f"{tc.get('tool_name') or tc.get('tool_id','?')[:8]}  ({tc.get('tool_type','')})",
            "detail": {
                "endpoint": tc.get("tool_endpoint"),
                "inputs": tc.get("inputs"),
                "output": tc.get("output"),
                "error": tc.get("error_message"),
            },
            "score": None,
            "source": "tool_execution_history",
            "ref_id": tc.get("execution_id"),
            "agent": tc.get("agent_name"),
            "status": tc.get("status"),
            "latency_ms": tc.get("latency_ms"),
        })
    for sh in score_history:
        timeline.append({
            "layer": "SCORING",
            "ts": sh.get("created_at"),
            "title": f"Score {sh.get('score'):.2f} ({sh.get('context_type')})" if sh.get("score") is not None else "Score",
            "detail": {
                "factors": sh.get("factors"),
                "band": [sh.get("band_low"), sh.get("band_high")],
                "within_band": sh.get("within_band"),
                "correction_triggered": sh.get("correction_triggered"),
            },
            "score": sh.get("score"),
            "source": "score_history",
            "ref_id": str(sh.get("id")),
            "agent": sh.get("agent_name"),
        })
    for rl in rl_feedback:
        timeline.append({
            "layer": "RL_FEEDBACK",
            "ts": rl.get("processed_at"),
            "title": f"{rl.get('feedback_source')} → {rl.get('feedback_type')}",
            "detail": {
                "original": rl.get("original_score"),
                "adjusted": rl.get("adjusted_score"),
                "reward": rl.get("reward_signal"),
                "band_before": [rl.get("band_low_before"), rl.get("band_high_before")],
                "band_after": [rl.get("band_low_after"), rl.get("band_high_after")],
            },
            "score": rl.get("adjusted_score"),
            "source": "rl_feedback_log",
            "ref_id": str(rl.get("id")),
            "agent_id": rl.get("agent_id"),
        })
    for inter in interactions:
        timeline.append({
            "layer": "AGENT_INTERACTION",
            "ts": inter.get("timestamp") or inter.get("created_at"),
            "title": f"AgentInteraction: {inter.get('interaction_type','')}",
            "detail": inter.get("payload") or inter,
            "source": "neo4j:AgentInteraction",
            "ref_id": inter.get("interaction_id"),
            "agent": inter.get("agent_name"),
        })

    # Stable sort by ts (None last), preserving insertion order otherwise
    def _sort_key(e):
        ts = e.get("ts")
        return (0, ts) if ts else (1, "")
    timeline.sort(key=_sort_key)

    # 7. Summary band — confidence + provenance
    final_score = None
    for m in messages:
        if m.get("role") == "assistant" and m.get("score") is not None:
            final_score = m.get("score")
    if final_score is None and pipeline_steps:
        scores = [s.get("score") for s in pipeline_steps if s.get("score") is not None]
        if scores:
            final_score = sum(scores) / len(scores)

    summary = {
        "trace_id": target_trace_id,
        "conversation_id": conversation_id,
        "graph_id": graph_id,
        "session_id": session_id,
        "final_score": final_score,
        "n_messages": len(messages),
        "n_tool_calls": len(tool_calls),
        "n_pipeline_steps": len(pipeline_steps),
        "n_task_nodes": len(task_nodes),
        "n_score_records": len(score_history),
        "n_rl_feedback": len(rl_feedback),
        "n_interactions": len(interactions),
        "tools_used": sorted({tc.get("tool_name") for tc in tool_calls if tc.get("tool_name")}),
        "agents_involved": sorted({
            *(s.get("agent_name") for s in pipeline_steps if s.get("agent_name")),
            *(n.get("assigned_agent_name") for n in task_nodes if n.get("assigned_agent_name")),
        }),
    }

    return {
        "trace_id": trace_id,
        "summary": summary,
        "conversation": conversation,
        "messages": messages,
        "graph": graph_node,
        "task_nodes": task_nodes,
        "task_edges": task_edges,
        "pipeline_steps": pipeline_steps,
        "tool_calls": tool_calls,
        "score_history": score_history,
        "rl_feedback": rl_feedback,
        "interactions": interactions,
        "episodes": episodes,
        "timeline": timeline,
    }


# ── Traces for a conversation ────────────────────────────────────────────────
@router.get("/traces/by-conversation/{conversation_id}")
async def traces_by_conversation(
    conversation_id: str,
    request: Request,
) -> Dict[str, Any]:
    """Return all distinct trace_ids that belong to a conversation, with summaries."""
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    rows = _fetch_all(
        """
        SELECT trace_id, MIN(created_at) AS first_at, MAX(created_at) AS last_at,
               COUNT(*) AS n_messages,
               MAX(CASE WHEN role='user' THEN content END) AS user_request
        FROM messages
        WHERE conversation_id = %s AND trace_id IS NOT NULL AND trace_id <> ''
        GROUP BY trace_id
        ORDER BY last_at DESC
        """,
        (conversation_id,),
    )
    return {"trace_id": trace_id, "conversation_id": conversation_id, "traces": rows}
