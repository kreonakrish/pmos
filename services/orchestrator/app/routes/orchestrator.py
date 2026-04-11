"""Orchestrator HTTP routes.

POST /v1/orchestrator/chat
GET  /v1/orchestrator/sessions/{session_id}
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, AsyncIterator, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from typing import Literal
from pydantic import BaseModel
from app.models.pipeline import ChatRequest, ChatResponse, SessionResponse, StreamChunk
from app.utils.logger import logger
from app.utils.telemetry import REQUEST_DURATION, REQUEST_TOTAL

router = APIRouter(prefix="/v1/orchestrator", tags=["orchestrator"])


def _get_pipeline(request: Request):
    return request.app.state.pipeline


def _get_neo4j(request: Request):
    return request.app.state.neo4j


@router.post("/chat", response_model=None)
async def chat(
    body: ChatRequest,
    request: Request,
) -> Any:
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    pipeline = _get_pipeline(request)
    start = time.monotonic()

    logger.info(
        "Chat request received",
        layer="router",
        conversation_id=body.conversation_id,
        team_id=body.team_id,
        stream=body.stream,
        trace_id=trace_id,
    )

    if body.stream:
        return StreamingResponse(
            _stream_pipeline(pipeline, body, trace_id),
            media_type="text/event-stream",
        )

    try:
        result = await pipeline.execute(
            conversation_id=body.conversation_id,
            message=body.message,
            team_id=body.team_id,
            trace_id=trace_id,
        )
        elapsed = time.monotonic() - start
        REQUEST_DURATION.labels(method="POST", path="/v1/orchestrator/chat").observe(elapsed)
        REQUEST_TOTAL.labels(method="POST", path="/v1/orchestrator/chat", status="200").inc()

        return ChatResponse(
            session_id=result["session_id"],
            conversation_id=body.conversation_id,
            response=result["response"],
            graph_id=result["graph_id"],
            score=result.get("score"),
            trace_id=trace_id,
        )

    except Exception as exc:
        elapsed = time.monotonic() - start
        REQUEST_DURATION.labels(method="POST", path="/v1/orchestrator/chat").observe(elapsed)
        REQUEST_TOTAL.labels(method="POST", path="/v1/orchestrator/chat", status="500").inc()
        logger.error(
            "Chat endpoint error",
            layer="router",
            error=str(exc),
            trace_id=trace_id,
        )
        raise HTTPException(status_code=500, detail={"error": str(exc), "code": "PIPELINE_ERROR", "trace_id": trace_id})


async def _stream_pipeline(pipeline, body: ChatRequest, trace_id: str) -> AsyncIterator[str]:
    """Yield SSE chunks while executing the pipeline."""
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        chunk = StreamChunk(
            type="step",
            agent_name="orchestrator",
            content="Pipeline started",
            score=None,
            trace_id=trace_id,
            timestamp=timestamp,
        )
        yield f"data: {chunk.model_dump_json()}\n\n"

        result = await pipeline.execute(
            conversation_id=body.conversation_id,
            message=body.message,
            team_id=body.team_id,
            trace_id=trace_id,
        )

        final_chunk = StreamChunk(
            type="complete",
            agent_name="orchestrator",
            content=result["response"],
            score=result.get("score"),
            trace_id=trace_id,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        yield f"data: {final_chunk.model_dump_json()}\n\n"

    except Exception as exc:
        error_chunk = StreamChunk(
            type="error",
            agent_name="orchestrator",
            content=str(exc),
            score=None,
            trace_id=trace_id,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        yield f"data: {error_chunk.model_dump_json()}\n\n"


# ── Task-based endpoints (thin wrappers over the pipeline) ───────────────────


class TaskCreateRequest(BaseModel):
    task_type: str
    description: str
    context: Dict[str, Any] = {}

    class Config:
        extra = "allow"


class TaskResponse(BaseModel):
    task_id: str
    status: str
    trace_id: str
    response: str = ""
    score: Any = None
    graph_id: str = ""
    assigned_agent_id: int | None = None
    fallback_used: bool = False
    events: list = []


@router.post("/tasks", response_model=None)
async def create_task(
    body: TaskCreateRequest,
    request: Request,
) -> Any:
    """Create a task by forwarding it through the chat pipeline."""
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    pipeline = _get_pipeline(request)
    task_id = str(uuid.uuid4())

    logger.info(
        "Task creation request",
        layer="router",
        task_type=body.task_type,
        trace_id=trace_id,
    )

    try:
        # Use the chat pipeline to process the task
        result = await pipeline.execute(
            conversation_id=f"task-{task_id}",
            message=f"[{body.task_type}] {body.description}",
            team_id=body.context.get("team_id", "default"),
            trace_id=trace_id,
        )

        return {
            "task_id": task_id,
            "status": "completed",
            "trace_id": trace_id,
            "response": result.get("response", ""),
            "score": result.get("score"),
            "graph_id": result.get("graph_id", ""),
            "session_id": result.get("session_id", ""),
        }
    except Exception as exc:
        logger.error(
            "Task creation failed",
            layer="router",
            error=str(exc),
            trace_id=trace_id,
        )
        # Return a pending/failed task instead of raising
        return {
            "task_id": task_id,
            "status": "failed",
            "trace_id": trace_id,
            "error": str(exc),
        }


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: str,
    request: Request,
) -> Any:
    """Get task status. Looks up the associated session/graph."""
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    neo4j = _get_neo4j(request)

    # Try to find the task graph in Neo4j
    try:
        rows = await neo4j.run_query(
            "MATCH (g:TaskGraph {session_id: $session_id}) RETURN g LIMIT 1",
            {"session_id": f"task-{task_id}"},
            trace_id=trace_id,
        )
        if rows:
            graph = dict(rows[0]["g"])
            return {
                "task_id": task_id,
                "status": graph.get("status", "completed"),
                "graph_id": graph.get("graph_id", ""),
                "trace_id": trace_id,
            }
    except Exception:
        pass

    # If not found in Neo4j, return a generic completed status
    return {
        "task_id": task_id,
        "status": "completed",
        "trace_id": trace_id,
    }


@router.get("/tasks/{task_id}/graph")
async def get_task_graph(
    task_id: str,
    request: Request,
) -> Any:
    """Get the execution graph for a task."""
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    neo4j = _get_neo4j(request)

    try:
        nodes = await neo4j.run_query(
            """
            MATCH (n:TaskNode)
            WHERE n.session_id = $session_id OR n.task_id = $task_id
            RETURN n
            """,
            {"session_id": f"task-{task_id}", "task_id": task_id},
            trace_id=trace_id,
        )
        edges = await neo4j.run_query(
            """
            MATCH (a:TaskNode)-[r]->(b:TaskNode)
            WHERE a.session_id = $session_id OR a.task_id = $task_id
            RETURN type(r) as type, a.task_id as from_id, b.task_id as to_id
            """,
            {"session_id": f"task-{task_id}", "task_id": task_id},
            trace_id=trace_id,
        )
        return {
            "task_id": task_id,
            "nodes": [dict(r["n"]) for r in (nodes or [])],
            "edges": [dict(r) for r in (edges or [])],
            "children": [],
            "trace_id": trace_id,
        }
    except Exception as exc:
        return {
            "task_id": task_id,
            "nodes": [{"task_id": task_id, "status": "completed"}],
            "edges": [],
            "children": [],
            "trace_id": trace_id,
        }


@router.get("/tasks/{task_id}/bids")
async def get_task_bids(
    task_id: str,
    request: Request,
) -> Any:
    """Get all bid ExecutionEvents for a task from Neo4j."""
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    neo4j = _get_neo4j(request)

    try:
        # Query all bid events: BID_WON, BID_SUBMITTED, BID_ACCURACY
        rows = await neo4j.run_query(
            """
            MATCH (e:ExecutionEvent)
            WHERE e.node_id = $task_id AND e.event_type IN ['BID_WON', 'BID_SUBMITTED', 'BID_ACCURACY']
            RETURN e ORDER BY e.timestamp
            """,
            {"task_id": task_id},
            trace_id=trace_id,
        )
        bids = []
        for r in (rows or []):
            event = {k: (str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v)
                     for k, v in dict(r["e"]).items()}
            # Parse action_taken JSON to expose structured bid details
            action_raw = event.get("action_taken", "")
            if action_raw and isinstance(action_raw, str) and action_raw.startswith("{"):
                try:
                    import json as _json
                    details = _json.loads(action_raw)
                    event.update(details)
                except Exception:
                    pass
            bids.append(event)

        # Also query AgentInteraction nodes for bid interactions
        interaction_rows = await neo4j.run_query(
            """
            MATCH (n:TaskNode {node_id: $task_id})-[:HAS_INTERACTION]->(i:AgentInteraction)
            WHERE i.interaction_type IN ['BID_WON', 'BID_SUBMITTED']
            RETURN i ORDER BY i.timestamp
            """,
            {"task_id": task_id},
            trace_id=trace_id,
        )
        for r in (interaction_rows or []):
            interaction = {k: (str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v)
                          for k, v in dict(r["i"]).items()}
            interaction["source"] = "agent_interaction"
            bids.append(interaction)

        # If no bid events found, fall back to reading TaskNode properties
        if not bids:
            node_rows = await neo4j.run_query(
                """
                MATCH (n:TaskNode {node_id: $task_id})
                RETURN n.assigned_agent_id as agent_id,
                       n.assigned_agent_name as agent_name,
                       n.bid_confidence as confidence,
                       n.fallback_agent_ids as fallback_ids
                """,
                {"task_id": task_id},
                trace_id=trace_id,
            )
            for r in (node_rows or []):
                if r.get("agent_id"):
                    bids.append({
                        "event_type": "BID_WON",
                        "agent_id": str(r["agent_id"]),
                        "agent_name": r.get("agent_name", ""),
                        "confidence": r.get("confidence", 0),
                        "is_winner": True,
                        "source": "task_node_property",
                    })

        return {"bids": bids, "trace_id": trace_id}
    except Exception as exc:
        logger.error(
            "Failed to fetch task bids",
            layer="router",
            task_id=task_id,
            error=str(exc),
            trace_id=trace_id,
        )
        return {"bids": [], "error": str(exc), "trace_id": trace_id}


@router.get("/tasks/{task_id}/events")
async def get_task_events(
    task_id: str,
    request: Request,
) -> Any:
    """Get execution events for a task."""
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    neo4j = _get_neo4j(request)

    try:
        rows = await neo4j.run_query(
            """
            MATCH (e:ExecutionEvent)
            WHERE e.task_id = $task_id
            RETURN e ORDER BY e.timestamp
            """,
            {"task_id": task_id},
            trace_id=trace_id,
        )
        events = [dict(r["e"]) for r in (rows or [])]
        return {"events": events, "trace_id": trace_id}
    except Exception:
        return {"events": [], "trace_id": trace_id}


@router.get("/circuit-breakers")
async def get_circuit_breakers(
    request: Request,
) -> Any:
    """Return circuit breaker status for all downstream services."""
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    pipeline = _get_pipeline(request)

    # If pipeline has circuit breaker states, return them
    breakers = {}
    if hasattr(pipeline, "_breakers"):
        for name, cb in pipeline._breakers.items():
            breakers[name] = {
                "state": cb.state if hasattr(cb, "state") else "unknown",
                "failure_count": getattr(cb, "failure_count", 0),
            }
    elif hasattr(pipeline, "circuit_breakers"):
        breakers = pipeline.circuit_breakers
    else:
        breakers = {
            "memory_service": {"state": "closed", "failure_count": 0},
            "scoring_service": {"state": "closed", "failure_count": 0},
            "rag_service": {"state": "closed", "failure_count": 0},
        }

    return {"circuit_breakers": breakers, "trace_id": trace_id}


@router.get("/graph/tasks")
async def get_graph_tasks(
    request: Request,
    team_id: str = "",
    graph_id: str = "",
    conversation_id: str = "",
) -> Any:
    """Return TaskNode entries from Neo4j for the graph view, with optional filters."""
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    neo4j = _get_neo4j(request)

    try:
        # Build filter conditions
        where_clauses = []
        params: Dict[str, Any] = {}

        if graph_id:
            where_clauses.append("t.graph_id = $filter_graph_id")
            params["filter_graph_id"] = graph_id
        if team_id:
            # Find graph_ids for this team
            team_graphs = await neo4j.run_query(
                "MATCH (g:TaskGraph {team_id: $tid}) RETURN g.graph_id as gid",
                {"tid": team_id}, trace_id=trace_id,
            )
            gids = [r["gid"] for r in (team_graphs or [])]
            if gids:
                where_clauses.append("t.graph_id IN $filter_graph_ids")
                params["filter_graph_ids"] = gids
            else:
                return {"nodes": [], "edges": [], "teams": [], "trace_id": trace_id}
        if conversation_id:
            conv_graphs = await neo4j.run_query(
                "MATCH (g:TaskGraph {conversation_id: $cid}) RETURN g.graph_id as gid",
                {"cid": conversation_id}, trace_id=trace_id,
            )
            gids = [r["gid"] for r in (conv_graphs or [])]
            if gids:
                where_clauses.append("t.graph_id IN $filter_conv_graph_ids")
                params["filter_conv_graph_ids"] = gids
            else:
                return {"nodes": [], "edges": [], "teams": [], "trace_id": trace_id}

        where = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        rows = await neo4j.run_query(
            f"""
            MATCH (t:TaskNode)
            {where}
            OPTIONAL MATCH (t)-[r:SPAWNED_BY]->(p:TaskNode)
            RETURN t, p.node_id AS parent_node_id
            ORDER BY t.created_at DESC LIMIT 500
            """,
            params,
            trace_id=trace_id,
        )
        nodes = []
        edges = []
        for row in (rows or []):
            node = {k: (str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v)
                    for k, v in dict(row["t"]).items()}
            nodes.append(node)
            parent_id = row.get("parent_node_id")
            if parent_id:
                edges.append({"from": node.get("node_id", ""), "to": parent_id, "type": "SPAWNED_BY"})

        # Also return available teams for the filter dropdown
        team_rows = await neo4j.run_query(
            "MATCH (t:Team) RETURN t.team_id as team_id, t.name as name", {},
            trace_id=trace_id,
        )
        teams = [{"team_id": r["team_id"], "name": r["name"]} for r in (team_rows or [])]

        return {"nodes": nodes, "edges": edges, "teams": teams, "trace_id": trace_id}
    except Exception as exc:
        logger.error("Graph tasks query failed", layer="router", error=str(exc), trace_id=trace_id)
        return {"nodes": [], "edges": [], "teams": [], "trace_id": trace_id}


@router.get("/sops")
async def list_sops(
    request: Request,
) -> Any:
    """List all Standard Operating Procedures from Neo4j."""
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    neo4j = _get_neo4j(request)

    try:
        rows = await neo4j.run_query(
            "MATCH (s:SOPNode) RETURN s ORDER BY s.created_at DESC LIMIT 50",
            {},
            trace_id=trace_id,
        )
        # Coerce neo4j.time.DateTime and other native types to JSON-safe values
        sops = []
        for r in (rows or []):
            sop = {
                k: (str(v) if not isinstance(v, (str, int, float, bool, list, type(None))) else v)
                for k, v in dict(r["s"]).items()
            }
            sops.append(sop)
        return {"sops": sops, "trace_id": trace_id}
    except Exception:
        return {"sops": [], "trace_id": trace_id}


# ── Jobs / Graphs list endpoints ──────────────────────────────────────────────


@router.get("/jobs")
async def list_jobs(
    request: Request,
    limit: int = 50,
    offset: int = 0,
) -> Any:
    """List all pipeline executions (TaskGraphs) with summary stats."""
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    neo4j = _get_neo4j(request)

    try:
        rows = await neo4j.run_query(
            """
            MATCH (g:TaskGraph)
            OPTIONAL MATCH (n:TaskNode {graph_id: g.graph_id})
            WITH g,
                 count(n) as total_nodes,
                 count(CASE WHEN n.status = 'SUCCESS' THEN 1 END) as success_nodes,
                 count(CASE WHEN n.status = 'FAILED' THEN 1 END) as failed_nodes,
                 count(CASE WHEN n.status = 'PENDING' THEN 1 END) as pending_nodes,
                 avg(n.score) as avg_score,
                 collect(DISTINCT n.assigned_agent_name) as agents_used
            RETURN g, total_nodes, success_nodes, failed_nodes, pending_nodes, avg_score, agents_used
            ORDER BY g.created_at DESC
            SKIP $offset LIMIT $limit
            """,
            {"offset": offset, "limit": limit},
            trace_id=trace_id,
        )

        jobs = []
        for row in (rows or []):
            graph = dict(row["g"])
            jobs.append({
                **{k: (str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v)
                   for k, v in graph.items()},
                "total_nodes": row["total_nodes"],
                "success_nodes": row["success_nodes"],
                "failed_nodes": row["failed_nodes"],
                "pending_nodes": row["pending_nodes"],
                "avg_score": row["avg_score"],
                "agents_used": [a for a in row["agents_used"] if a],
            })
        return {"jobs": jobs, "trace_id": trace_id}

    except Exception as exc:
        logger.error(
            "Failed to list jobs",
            layer="router",
            error=str(exc),
            trace_id=trace_id,
        )
        return {"jobs": [], "error": str(exc), "trace_id": trace_id}


@router.get("/jobs/{graph_id}")
async def get_job(
    graph_id: str,
    request: Request,
) -> Any:
    """Get detailed view of a single TaskGraph with all its nodes and relationships."""
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    neo4j = _get_neo4j(request)

    try:
        # Fetch the graph itself
        graph_rows = await neo4j.run_query(
            "MATCH (g:TaskGraph {graph_id: $graph_id}) RETURN g LIMIT 1",
            {"graph_id": graph_id},
            trace_id=trace_id,
        )
        if not graph_rows:
            raise HTTPException(
                status_code=404,
                detail={"error": "Graph not found", "code": "GRAPH_NOT_FOUND", "trace_id": trace_id},
            )

        graph = dict(graph_rows[0]["g"])
        graph_serialized = {
            k: (str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v)
            for k, v in graph.items()
        }

        # Fetch all nodes in this graph
        node_rows = await neo4j.run_query(
            """
            MATCH (n:TaskNode {graph_id: $graph_id})
            RETURN n ORDER BY n.created_at
            """,
            {"graph_id": graph_id},
            trace_id=trace_id,
        )
        nodes = []
        for r in (node_rows or []):
            node = {k: (str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v)
                    for k, v in dict(r["n"]).items()}
            nodes.append(node)

        # Fetch relationships between nodes
        edge_rows = await neo4j.run_query(
            """
            MATCH (a:TaskNode {graph_id: $graph_id})-[r]->(b:TaskNode {graph_id: $graph_id})
            RETURN type(r) as type, a.node_id as from_id, b.node_id as to_id
            """,
            {"graph_id": graph_id},
            trace_id=trace_id,
        )
        edges = [dict(r) for r in (edge_rows or [])]

        return {
            "graph": graph_serialized,
            "nodes": nodes,
            "edges": edges,
            "trace_id": trace_id,
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "Failed to get job details",
            layer="router",
            graph_id=graph_id,
            error=str(exc),
            trace_id=trace_id,
        )
        raise HTTPException(
            status_code=500,
            detail={"error": str(exc), "code": "JOB_DETAIL_ERROR", "trace_id": trace_id},
        )


@router.post("/jobs/{graph_id}/resume")
async def resume_job(
    graph_id: str,
    request: Request,
) -> Any:
    """Resume an interrupted pipeline execution.

    Finds PENDING nodes in the graph and re-runs them through the pipeline.
    Only works on graphs with status INTERRUPTED.
    """
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    neo4j = _get_neo4j(request)
    pipeline = _get_pipeline(request)

    logger.info(
        "Job resume requested",
        layer="router",
        graph_id=graph_id,
        trace_id=trace_id,
    )

    try:
        # 1. Verify the graph exists and is in a resumable state
        graph_rows = await neo4j.run_query(
            "MATCH (g:TaskGraph {graph_id: $graph_id}) RETURN g LIMIT 1",
            {"graph_id": graph_id},
            trace_id=trace_id,
        )
        if not graph_rows:
            raise HTTPException(
                status_code=404,
                detail={"error": "Graph not found", "code": "GRAPH_NOT_FOUND", "trace_id": trace_id},
            )

        graph = dict(graph_rows[0]["g"])
        status = graph.get("status", "")
        if status not in ("INTERRUPTED", "COMPLETED_PARTIAL"):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": f"Graph status is '{status}'; only INTERRUPTED or COMPLETED_PARTIAL graphs can be resumed",
                    "code": "INVALID_GRAPH_STATUS",
                    "trace_id": trace_id,
                },
            )

        # 2. Mark graph as EXECUTING again
        await neo4j.run_query(
            """
            MATCH (g:TaskGraph {graph_id: $graph_id})
            SET g.status = 'EXECUTING', g.updated_at = datetime(),
                g.recovery_note = 'Resumed manually'
            """,
            {"graph_id": graph_id},
            trace_id=trace_id,
        )

        # 3. Find PENDING nodes
        pending_rows = await neo4j.run_query(
            """
            MATCH (n:TaskNode {graph_id: $graph_id})
            WHERE n.status = 'PENDING'
            RETURN n ORDER BY n.created_at
            """,
            {"graph_id": graph_id},
            trace_id=trace_id,
        )

        if not pending_rows:
            await neo4j.run_query(
                """
                MATCH (g:TaskGraph {graph_id: $graph_id})
                SET g.status = 'COMPLETED', g.updated_at = datetime()
                """,
                {"graph_id": graph_id},
                trace_id=trace_id,
            )
            return {
                "graph_id": graph_id,
                "status": "COMPLETED",
                "resumed_nodes": 0,
                "message": "No pending nodes to resume; marked as COMPLETED",
                "trace_id": trace_id,
            }

        pending_nodes = [dict(r["n"]) for r in pending_rows]
        pending_descriptions = [n.get("description", "") for n in pending_nodes]

        # 4. Get team_id from graph metadata for agent selection
        team_id = graph.get("team_id", "default")
        session_id = graph.get("session_id", str(uuid.uuid4()))

        # 5. Select agents
        primary, fallbacks = await pipeline._agent_sel.select_primary_and_fallbacks(
            team_id=team_id,
            trace_id=trace_id,
        )

        # 6. Execute pending nodes (Steps 4-7)
        node_results = await pipeline._step4_to_7_execution(
            graph_id=graph_id,
            root_node_id="",
            node_descriptions=pending_descriptions,
            primary=primary,
            fallbacks=fallbacks,
            message=graph.get("user_request", ""),
            trace_id=trace_id,
        )

        # 7. Re-aggregate (Step 8) — include both old successful results and new results
        all_node_rows = await neo4j.run_query(
            """
            MATCH (n:TaskNode {graph_id: $graph_id})
            WHERE n.status = 'SUCCESS'
            RETURN n.description as description, n.llm_response as llm_response, n.score as score
            """,
            {"graph_id": graph_id},
            trace_id=trace_id,
        )
        all_results = [dict(r) for r in (all_node_rows or [])]

        # Combine with new node_results
        combined_results = []
        for r in all_results:
            combined_results.append({
                "description": r.get("description", ""),
                "llm_response": r.get("llm_response", ""),
                "score": r.get("score", 0.0),
                "status": "SUCCESS",
            })
        for r in node_results:
            if r.get("status") in ("SUCCESS", "AUTO_CORRECTED"):
                combined_results.append(r)

        final_response = await pipeline._step8_aggregation(
            message=graph.get("user_request", ""),
            node_results=combined_results,
            graph_id=graph_id,
            primary=primary,
            trace_id=trace_id,
        )

        successful = sum(1 for r in node_results if r.get("status") in ("SUCCESS", "AUTO_CORRECTED"))
        failed = sum(1 for r in node_results if r.get("status") == "FAILED")

        return {
            "graph_id": graph_id,
            "status": "COMPLETED",
            "resumed_nodes": len(pending_nodes),
            "successful": successful,
            "failed": failed,
            "response": final_response,
            "trace_id": trace_id,
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "Job resume failed",
            layer="router",
            graph_id=graph_id,
            error=str(exc),
            trace_id=trace_id,
        )
        # Mark graph back as interrupted on failure
        try:
            await neo4j.run_query(
                """
                MATCH (g:TaskGraph {graph_id: $graph_id})
                SET g.status = 'INTERRUPTED', g.updated_at = datetime(),
                    g.recovery_note = 'Resume attempt failed'
                """,
                {"graph_id": graph_id},
                trace_id=trace_id,
            )
        except Exception:
            pass
        raise HTTPException(
            status_code=500,
            detail={"error": str(exc), "code": "RESUME_ERROR", "trace_id": trace_id},
        )


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    request: Request,
) -> SessionResponse:
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    neo4j = _get_neo4j(request)

    # Lookup graph_id by session_id
    rows = await neo4j.run_query(
        "MATCH (g:TaskGraph {session_id: $session_id}) RETURN g LIMIT 1",
        {"session_id": session_id},
        trace_id=trace_id,
    )
    if not rows:
        raise HTTPException(
            status_code=404,
            detail={"error": "Session not found", "code": "SESSION_NOT_FOUND", "trace_id": trace_id},
        )

    graph = dict(rows[0]["g"])
    graph_id = graph.get("graph_id", "")
    nodes = await neo4j.get_graph_nodes(graph_id, trace_id=trace_id)

    return SessionResponse(
        session_id=session_id,
        graph_id=graph_id,
        status=graph.get("status", "UNKNOWN"),
        nodes=nodes,
        trace_id=trace_id,
    )


# ── Distributed feedback endpoint ──────────────────────────────────────────────


class ConversationFeedbackRequest(BaseModel):
    message_id: str
    feedback: Literal["positive", "negative"]
    team_id: Optional[str] = None


@router.post("/conversations/{conversation_id}/feedback")
async def conversation_feedback(
    conversation_id: str,
    body: ConversationFeedbackRequest,
    request: Request,
) -> Any:
    """Distribute user feedback to all agents in a team for a conversation message."""
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    pipeline = _get_pipeline(request)

    # Resolve team_id: use provided value or look it up from the conversation
    team_id = body.team_id
    if not team_id:
        try:
            pool = request.app.state.mysql_pool
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT team_id FROM conversations WHERE conversation_id = %s",
                        (conversation_id,),
                    )
                    row = await cur.fetchone()
                    if row:
                        team_id = str(row[0]) if row[0] else None
        except Exception as exc:
            logger.warning(
                "Failed to look up team_id from conversation",
                layer="router",
                conversation_id=conversation_id,
                error=str(exc),
                trace_id=trace_id,
            )

    if not team_id:
        raise HTTPException(
            status_code=400,
            detail={"error": "Could not determine team_id for conversation", "code": "NO_TEAM_ID", "trace_id": trace_id},
        )

    logger.info(
        "Conversation feedback received",
        layer="router",
        conversation_id=conversation_id,
        message_id=body.message_id,
        feedback=body.feedback,
        team_id=team_id,
        trace_id=trace_id,
    )

    try:
        # 1. Fetch team agents from agent-mgmt
        import httpx
        from app.config import settings

        team_data: Dict[str, Any] = {}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{settings.agent_mgmt_url}/v1/teams/{team_id}",
                    headers={"x-request-id": trace_id},
                )
                resp.raise_for_status()
                raw = resp.json()
                team_data = raw.get("team", raw)
        except Exception as exc:
            logger.error(
                "Failed to fetch team for feedback distribution",
                layer="router",
                team_id=team_id,
                error=str(exc),
                trace_id=trace_id,
            )
            raise HTTPException(
                status_code=502,
                detail={"error": f"Failed to fetch team: {exc}", "code": "TEAM_FETCH_ERROR", "trace_id": trace_id},
            )

        agents = team_data.get("agents", [])
        if not agents:
            return {"accepted": True, "agents_notified": 0, "trace_id": trace_id}

        # 2. Determine score and reward signal based on feedback
        score = 1.0 if body.feedback == "positive" else 0.0
        reward_signal = 1.0 if body.feedback == "positive" else -0.5

        # 3. Send feedback to scoring service for each agent
        agents_notified = 0
        async with httpx.AsyncClient(timeout=10.0) as client:
            for agent in agents:
                agent_id = agent.get("id") or agent.get("agent_id")
                if agent_id is None:
                    continue
                # Ensure agent_id is an int
                try:
                    agent_id_int = int(agent_id) if not isinstance(agent_id, int) else agent_id
                except (ValueError, TypeError):
                    continue

                feedback_payload = {
                    "agent_id": agent_id_int,
                    "task_id": body.message_id,
                    "session_id": conversation_id,
                    "feedback_source": "USER",
                    "feedback_type": "SCORE",
                    "score": score,
                    "reward_signal": reward_signal,
                    "context_type": "conversation",
                }
                try:
                    resp = await client.post(
                        f"{settings.scoring_service_url}/v1/scoring/feedback",
                        json=feedback_payload,
                        headers={"x-request-id": trace_id},
                    )
                    resp.raise_for_status()
                    agents_notified += 1
                except Exception as exc:
                    logger.warning(
                        "Feedback submission failed for agent",
                        layer="router",
                        agent_id=agent_id_int,
                        error=str(exc),
                        trace_id=trace_id,
                    )

        logger.info(
            "Conversation feedback distributed",
            layer="router",
            conversation_id=conversation_id,
            agents_notified=agents_notified,
            trace_id=trace_id,
        )
        return {"accepted": True, "agents_notified": agents_notified, "trace_id": trace_id}

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "Conversation feedback failed",
            layer="router",
            error=str(exc),
            trace_id=trace_id,
        )
        raise HTTPException(
            status_code=500,
            detail={"error": str(exc), "code": "FEEDBACK_ERROR", "trace_id": trace_id},
        )
