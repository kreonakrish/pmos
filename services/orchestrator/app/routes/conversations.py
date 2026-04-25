"""Conversation management HTTP routes.

GET    /v1/orchestrator/conversations
POST   /v1/orchestrator/conversations
GET    /v1/orchestrator/conversations/{conversation_id}
PATCH  /v1/orchestrator/conversations/{conversation_id}
DELETE /v1/orchestrator/conversations/{conversation_id}
GET    /v1/orchestrator/conversations/{conversation_id}/messages
POST   /v1/orchestrator/conversations/{conversation_id}/messages
GET    /v1/orchestrator/conversations/{conversation_id}/decomposition
GET    /v1/orchestrator/conversations/{conversation_id}/interactions
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import mysql.connector
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.config import settings
from app.middleware.rbac import require_permission
from app.utils.logger import logger

router = APIRouter(prefix="/v1/orchestrator/conversations", tags=["conversations"])


# ---------------------------------------------------------------------------
# Database helper
# ---------------------------------------------------------------------------


def get_db():
    """Return a new MySQL connection using settings."""
    return mysql.connector.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_db,
    )


def _row_to_conversation(row: tuple, columns: list[str]) -> dict:
    """Convert a DB row tuple to a conversation dict."""
    conv = dict(zip(columns, row))
    # Serialize datetime objects to ISO strings
    for key in ("created_at", "updated_at"):
        if key in conv and isinstance(conv[key], datetime):
            conv[key] = conv[key].isoformat()
    # Parse metadata JSON
    if "metadata" in conv and isinstance(conv["metadata"], str):
        try:
            conv["metadata"] = json.loads(conv["metadata"])
        except (json.JSONDecodeError, TypeError):
            conv["metadata"] = {}
    elif "metadata" in conv and conv["metadata"] is None:
        conv["metadata"] = {}
    return conv


def _row_to_message(row: tuple, columns: list[str]) -> dict:
    """Convert a DB row tuple to a message dict."""
    msg = dict(zip(columns, row))
    for key in ("created_at",):
        if key in msg and isinstance(msg[key], datetime):
            msg[key] = msg[key].isoformat()
    if "metadata" in msg and isinstance(msg["metadata"], str):
        try:
            msg["metadata"] = json.loads(msg["metadata"])
        except (json.JSONDecodeError, TypeError):
            msg["metadata"] = {}
    elif "metadata" in msg and msg["metadata"] is None:
        msg["metadata"] = {}
    return msg


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------


class CreateConversationRequest(BaseModel):
    title: str
    team_id: Optional[str] = None
    user_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    class Config:
        extra = "allow"


class UpdateConversationRequest(BaseModel):
    title: Optional[str] = None
    status: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    class Config:
        extra = "allow"


class CreateMessageRequest(BaseModel):
    content: str
    role: str = "user"

    class Config:
        extra = "allow"


# ---------------------------------------------------------------------------
# Conversation endpoints
# ---------------------------------------------------------------------------


CONVERSATION_COLUMNS = [
    "id", "conversation_id", "user_id", "team_id",
    "title", "status", "metadata", "created_at", "updated_at",
]

MESSAGE_COLUMNS = [
    "id", "message_id", "conversation_id", "role",
    "content", "trace_id", "score", "metadata", "created_at",
]


@router.get("")
async def list_conversations(
    request: Request,
    user_id: Optional[str] = Query(None),
    team_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
) -> Any:
    """List conversations with optional filters."""
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))

    logger.info(
        "Listing conversations",
        layer="router",
        user_id=user_id,
        team_id=team_id,
        status=status,
        trace_id=trace_id,
    )

    query = "SELECT id, conversation_id, user_id, team_id, title, status, metadata, created_at, updated_at FROM conversations WHERE 1=1"
    params: list[Any] = []

    if user_id is not None:
        query += " AND user_id = %s"
        params.append(user_id)
    if team_id is not None:
        query += " AND team_id = %s"
        params.append(team_id)
    if status is not None:
        query += " AND status = %s"
        params.append(status)

    query += " ORDER BY created_at DESC"

    conn = None
    cursor = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conversations = [_row_to_conversation(row, CONVERSATION_COLUMNS) for row in rows]
        return {"conversations": conversations, "count": len(conversations), "trace_id": trace_id}
    except mysql.connector.Error as exc:
        logger.error(
            "Failed to list conversations",
            layer="router",
            error=str(exc),
            trace_id=trace_id,
        )
        raise HTTPException(
            status_code=500,
            detail={"error": str(exc), "code": "DB_ERROR", "trace_id": trace_id},
        )
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


@router.post("", dependencies=[Depends(require_permission("conversations.write"))])
async def create_conversation(
    body: CreateConversationRequest,
    request: Request,
) -> Any:
    """Create a new conversation."""
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    conversation_id = str(uuid.uuid4())

    logger.info(
        "Creating conversation",
        layer="router",
        conversation_id=conversation_id,
        title=body.title,
        trace_id=trace_id,
    )

    metadata_json = json.dumps(body.metadata) if body.metadata else None

    conn = None
    cursor = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO conversations (conversation_id, user_id, team_id, title, status, metadata)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (conversation_id, body.user_id, body.team_id, body.title, "ACTIVE", metadata_json),
        )
        conn.commit()

        # Fetch the created row
        cursor.execute(
            "SELECT id, conversation_id, user_id, team_id, title, status, metadata, created_at, updated_at FROM conversations WHERE conversation_id = %s",
            (conversation_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise HTTPException(
                status_code=500,
                detail={"error": "Failed to retrieve created conversation", "code": "DB_ERROR", "trace_id": trace_id},
            )

        conversation = _row_to_conversation(row, CONVERSATION_COLUMNS)
        return {"conversation": conversation, "trace_id": trace_id}

    except mysql.connector.Error as exc:
        logger.error(
            "Failed to create conversation",
            layer="router",
            error=str(exc),
            trace_id=trace_id,
        )
        raise HTTPException(
            status_code=500,
            detail={"error": str(exc), "code": "DB_ERROR", "trace_id": trace_id},
        )
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    request: Request,
) -> Any:
    """Get a single conversation by conversation_id."""
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))

    logger.info(
        "Fetching conversation",
        layer="router",
        conversation_id=conversation_id,
        trace_id=trace_id,
    )

    conn = None
    cursor = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, conversation_id, user_id, team_id, title, status, metadata, created_at, updated_at FROM conversations WHERE conversation_id = %s",
            (conversation_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "Conversation not found", "code": "NOT_FOUND", "trace_id": trace_id},
            )
        conversation = _row_to_conversation(row, CONVERSATION_COLUMNS)
        return {"conversation": conversation, "trace_id": trace_id}

    except mysql.connector.Error as exc:
        logger.error(
            "Failed to fetch conversation",
            layer="router",
            error=str(exc),
            trace_id=trace_id,
        )
        raise HTTPException(
            status_code=500,
            detail={"error": str(exc), "code": "DB_ERROR", "trace_id": trace_id},
        )
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


@router.patch(
    "/{conversation_id}",
    dependencies=[Depends(require_permission("conversations.write"))],
)
async def update_conversation(
    conversation_id: str,
    body: UpdateConversationRequest,
    request: Request,
) -> Any:
    """Update a conversation's title, status, or metadata."""
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))

    logger.info(
        "Updating conversation",
        layer="router",
        conversation_id=conversation_id,
        trace_id=trace_id,
    )

    # Build dynamic SET clause
    set_parts: list[str] = []
    params: list[Any] = []

    if body.title is not None:
        set_parts.append("title = %s")
        params.append(body.title)
    if body.status is not None:
        valid_statuses = ("ACTIVE", "COMPLETED", "ARCHIVED")
        if body.status not in valid_statuses:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": f"Invalid status. Must be one of: {', '.join(valid_statuses)}",
                    "code": "INVALID_STATUS",
                    "trace_id": trace_id,
                },
            )
        set_parts.append("status = %s")
        params.append(body.status)
    if body.metadata is not None:
        set_parts.append("metadata = %s")
        params.append(json.dumps(body.metadata))

    if not set_parts:
        raise HTTPException(
            status_code=400,
            detail={"error": "No fields to update", "code": "NO_UPDATE_FIELDS", "trace_id": trace_id},
        )

    params.append(conversation_id)

    conn = None
    cursor = None
    try:
        conn = get_db()
        cursor = conn.cursor()

        # Check existence first
        cursor.execute(
            "SELECT id FROM conversations WHERE conversation_id = %s",
            (conversation_id,),
        )
        if cursor.fetchone() is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "Conversation not found", "code": "NOT_FOUND", "trace_id": trace_id},
            )

        query = f"UPDATE conversations SET {', '.join(set_parts)} WHERE conversation_id = %s"
        cursor.execute(query, params)
        conn.commit()

        # Fetch updated row
        cursor.execute(
            "SELECT id, conversation_id, user_id, team_id, title, status, metadata, created_at, updated_at FROM conversations WHERE conversation_id = %s",
            (conversation_id,),
        )
        row = cursor.fetchone()
        conversation = _row_to_conversation(row, CONVERSATION_COLUMNS)
        return {"conversation": conversation, "trace_id": trace_id}

    except mysql.connector.Error as exc:
        logger.error(
            "Failed to update conversation",
            layer="router",
            error=str(exc),
            trace_id=trace_id,
        )
        raise HTTPException(
            status_code=500,
            detail={"error": str(exc), "code": "DB_ERROR", "trace_id": trace_id},
        )
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


@router.delete(
    "/{conversation_id}",
    dependencies=[Depends(require_permission("conversations.write"))],
)
async def delete_conversation(
    conversation_id: str,
    request: Request,
) -> Any:
    """Delete a conversation and all its messages."""
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))

    logger.info(
        "Deleting conversation",
        layer="router",
        conversation_id=conversation_id,
        trace_id=trace_id,
    )

    conn = None
    cursor = None
    try:
        conn = get_db()
        cursor = conn.cursor()

        # Check existence
        cursor.execute(
            "SELECT id FROM conversations WHERE conversation_id = %s",
            (conversation_id,),
        )
        if cursor.fetchone() is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "Conversation not found", "code": "NOT_FOUND", "trace_id": trace_id},
            )

        # Delete messages first (foreign key integrity)
        cursor.execute(
            "DELETE FROM messages WHERE conversation_id = %s",
            (conversation_id,),
        )
        # Delete the conversation
        cursor.execute(
            "DELETE FROM conversations WHERE conversation_id = %s",
            (conversation_id,),
        )
        conn.commit()

        return {"deleted": True, "trace_id": trace_id}

    except mysql.connector.Error as exc:
        logger.error(
            "Failed to delete conversation",
            layer="router",
            error=str(exc),
            trace_id=trace_id,
        )
        raise HTTPException(
            status_code=500,
            detail={"error": str(exc), "code": "DB_ERROR", "trace_id": trace_id},
        )
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


# ---------------------------------------------------------------------------
# Message endpoints
# ---------------------------------------------------------------------------


@router.get("/{conversation_id}/messages")
async def list_messages(
    conversation_id: str,
    request: Request,
) -> Any:
    """List all messages for a conversation, ordered by created_at."""
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))

    logger.info(
        "Listing messages",
        layer="router",
        conversation_id=conversation_id,
        trace_id=trace_id,
    )

    conn = None
    cursor = None
    try:
        conn = get_db()
        cursor = conn.cursor()

        # Verify conversation exists
        cursor.execute(
            "SELECT id FROM conversations WHERE conversation_id = %s",
            (conversation_id,),
        )
        if cursor.fetchone() is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "Conversation not found", "code": "NOT_FOUND", "trace_id": trace_id},
            )

        cursor.execute(
            "SELECT id, message_id, conversation_id, role, content, trace_id, score, metadata, created_at FROM messages WHERE conversation_id = %s ORDER BY created_at ASC",
            (conversation_id,),
        )
        rows = cursor.fetchall()
        messages = [_row_to_message(row, MESSAGE_COLUMNS) for row in rows]
        return {"messages": messages, "count": len(messages), "trace_id": trace_id}

    except mysql.connector.Error as exc:
        logger.error(
            "Failed to list messages",
            layer="router",
            error=str(exc),
            trace_id=trace_id,
        )
        raise HTTPException(
            status_code=500,
            detail={"error": str(exc), "code": "DB_ERROR", "trace_id": trace_id},
        )
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


@router.post(
    "/{conversation_id}/messages",
    dependencies=[Depends(require_permission("conversations.write"))],
)
async def create_message(
    conversation_id: str,
    body: CreateMessageRequest,
    request: Request,
) -> Any:
    """Create a new message in a conversation."""
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    message_id = str(uuid.uuid4())

    logger.info(
        "Creating message",
        layer="router",
        conversation_id=conversation_id,
        message_id=message_id,
        role=body.role,
        trace_id=trace_id,
    )

    conn = None
    cursor = None
    try:
        conn = get_db()
        cursor = conn.cursor()

        # Verify conversation exists
        cursor.execute(
            "SELECT id FROM conversations WHERE conversation_id = %s",
            (conversation_id,),
        )
        if cursor.fetchone() is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "Conversation not found", "code": "NOT_FOUND", "trace_id": trace_id},
            )

        cursor.execute(
            """
            INSERT INTO messages (message_id, conversation_id, role, content, trace_id)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (message_id, conversation_id, body.role, body.content, trace_id),
        )
        conn.commit()

        # Fetch created message
        cursor.execute(
            "SELECT id, message_id, conversation_id, role, content, trace_id, score, metadata, created_at FROM messages WHERE message_id = %s",
            (message_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise HTTPException(
                status_code=500,
                detail={"error": "Failed to retrieve created message", "code": "DB_ERROR", "trace_id": trace_id},
            )

        message = _row_to_message(row, MESSAGE_COLUMNS)

        # If this is a user message, trigger the orchestrator pipeline
        if body.role == "user":
            try:
                # Fetch conversation to get team_id
                cursor.execute(
                    "SELECT team_id FROM conversations WHERE conversation_id = %s",
                    (conversation_id,),
                )
                conv_row = cursor.fetchone()
                team_id = conv_row[0] if conv_row else None
            finally:
                cursor.close()
                conn.close()
                conn = None
                cursor = None

            if team_id:
                try:
                    pipeline = request.app.state.pipeline

                    logger.info(
                        "Triggering pipeline for user message",
                        layer="router",
                        conversation_id=conversation_id,
                        team_id=team_id,
                        trace_id=trace_id,
                    )

                    result = await pipeline.execute(
                        conversation_id=conversation_id,
                        message=body.content,
                        team_id=team_id,
                        trace_id=trace_id,
                    )

                    # Store agent response as a new message
                    agent_response = result.get("response", "")
                    agent_message_id = str(uuid.uuid4())
                    score = result.get("score")
                    graph_id = result.get("graph_id", "")

                    metadata = {
                        "graph_id": graph_id,
                        "session_id": result.get("session_id", ""),
                        "agent_name": result.get("agent_name"),
                        "model": result.get("model"),
                        "latency_ms": result.get("latency_ms"),
                    }
                    # F7 — when this assistant turn is a translator
                    # clarification ("can you tell me which subdomain..."),
                    # persist the markers so the next user reply can be
                    # stitched back into the translator's prior_turns.
                    if result.get("clarification_needed"):
                        metadata["clarification"] = True
                        metadata["clarification_question"] = result.get(
                            "clarification_question"
                        )
                    if result.get("auditor_issue_id"):
                        metadata["auditor_issue_id"] = result.get("auditor_issue_id")
                        metadata["auditor_issue_kind"] = result.get(
                            "auditor_issue_kind"
                        )
                    # Charts — when a deterministic Report fired, the
                    # pipeline returns a ``visualizations`` list. Persist
                    # it on the assistant message so the chat UI can
                    # render bar/line/pie cards under the markdown body.
                    viz = result.get("visualizations") or []
                    if viz:
                        metadata["visualizations"] = viz
                    if result.get("matched_report_id"):
                        metadata["matched_report_id"] = result.get("matched_report_id")

                    conn2 = get_db()
                    cursor2 = conn2.cursor()
                    try:
                        cursor2.execute(
                            """
                            INSERT INTO messages (message_id, conversation_id, role, content, trace_id, score, metadata)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            """,
                            (agent_message_id, conversation_id, "assistant", agent_response, trace_id,
                             score, json.dumps(metadata)),
                        )
                        conn2.commit()

                        cursor2.execute(
                            "SELECT id, message_id, conversation_id, role, content, trace_id, score, metadata, created_at FROM messages WHERE message_id = %s",
                            (agent_message_id,),
                        )
                        agent_row = cursor2.fetchone()
                        agent_msg = _row_to_message(agent_row, MESSAGE_COLUMNS) if agent_row else None
                    finally:
                        cursor2.close()
                        conn2.close()

                    return {
                        "message": message,
                        "agent_message": agent_msg,
                        "graph_id": graph_id,
                        "trace_id": trace_id,
                    }

                except Exception as exc:
                    logger.error(
                        "Pipeline execution failed",
                        layer="router",
                        conversation_id=conversation_id,
                        error=str(exc),
                        trace_id=trace_id,
                    )
                    # Return user message even if pipeline fails
                    return {
                        "message": message,
                        "agent_message": None,
                        "error": str(exc),
                        "trace_id": trace_id,
                    }

        return {"message": message, "trace_id": trace_id}

    except mysql.connector.Error as exc:
        logger.error(
            "Failed to create message",
            layer="router",
            error=str(exc),
            trace_id=trace_id,
        )
        raise HTTPException(
            status_code=500,
            detail={"error": str(exc), "code": "DB_ERROR", "trace_id": trace_id},
        )
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


# ---------------------------------------------------------------------------
# Decomposition & Interactions (stubs for future implementation)
# ---------------------------------------------------------------------------


@router.get("/{conversation_id}/decomposition")
async def get_decomposition(
    conversation_id: str,
    request: Request,
) -> Any:
    """Return task decomposition graph for a conversation from Neo4j."""
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    neo4j = request.app.state.neo4j

    try:
        # Find TaskGraph for this conversation
        graphs = await neo4j.run_query(
            """
            MATCH (g:TaskGraph)
            WHERE g.session_id CONTAINS $conversation_id OR g.conversation_id = $conversation_id
            RETURN g ORDER BY g.created_at DESC LIMIT 5
            """,
            {"conversation_id": conversation_id},
            trace_id=trace_id,
        )

        all_tasks = []
        for graph_row in (graphs or []):
            graph = dict(graph_row["g"])
            graph_id = graph.get("graph_id", "")

            nodes = await neo4j.run_query(
                """
                MATCH (n:TaskNode {graph_id: $graph_id})
                OPTIONAL MATCH (n)-[:SPAWNED_BY]->(parent:TaskNode)
                RETURN n, parent.node_id as parent_id
                ORDER BY n.depth, n.created_at
                """,
                {"graph_id": graph_id},
                trace_id=trace_id,
            )

            for row in (nodes or []):
                node = {k: (str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v)
                        for k, v in dict(row["n"]).items()}
                node["parent_id"] = row.get("parent_id")
                node["graph_id"] = graph_id
                all_tasks.append(node)

        return {"tasks": all_tasks, "trace_id": trace_id}
    except Exception as exc:
        logger.error("Decomposition fetch failed", layer="router", error=str(exc), trace_id=trace_id)
        return {"tasks": [], "error": str(exc), "trace_id": trace_id}


@router.get("/{conversation_id}/interactions")
async def get_interactions(
    conversation_id: str,
    request: Request,
) -> Any:
    """Return agent interactions (execution events) for a conversation.

    Queries Neo4j for ExecutionEvents and AgentInteraction nodes,
    and also queries the MySQL agent_interactions table for full payloads.
    Falls back to Neo4j-only if MySQL table does not exist.
    """
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    neo4j = request.app.state.neo4j

    try:
        # Find execution events linked to this conversation's task graphs
        graphs = await neo4j.run_query(
            """
            MATCH (g:TaskGraph)
            WHERE g.session_id CONTAINS $conversation_id OR g.conversation_id = $conversation_id
            RETURN g.graph_id as graph_id
            """,
            {"conversation_id": conversation_id},
            trace_id=trace_id,
        )

        interactions = []
        graph_ids = []
        for graph_row in (graphs or []):
            graph_id = graph_row.get("graph_id", "")
            graph_ids.append(graph_id)

            # Get ExecutionEvents (course corrections, escalations, bids)
            events = await neo4j.run_query(
                """
                MATCH (n:TaskNode {graph_id: $graph_id})-[:PRODUCED_EVENT]->(e:ExecutionEvent)
                RETURN e, n.description as task_description, n.node_id as node_id
                ORDER BY e.timestamp
                """,
                {"graph_id": graph_id},
                trace_id=trace_id,
            )

            for row in (events or []):
                event = {k: (str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v)
                         for k, v in dict(row["e"]).items()}
                event["task_description"] = row.get("task_description")
                event["node_id"] = row.get("node_id")
                interactions.append(event)

            # Get AgentInteraction nodes (from capability negotiation + execution)
            agent_interactions = await neo4j.run_query(
                """
                MATCH (n:TaskNode {graph_id: $graph_id})-[:HAS_INTERACTION]->(i:AgentInteraction)
                RETURN i, n.description as task_description, n.node_id as node_id
                ORDER BY i.timestamp
                """,
                {"graph_id": graph_id},
                trace_id=trace_id,
            )

            for row in (agent_interactions or []):
                interaction = {k: (str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v)
                               for k, v in dict(row["i"]).items()}
                interaction["task_description"] = row.get("task_description")
                interaction["node_id"] = row.get("node_id")
                interaction["source"] = "neo4j_interaction"
                interactions.append(interaction)

            # Include task node execution details as interactions ONLY if no AgentInteraction exists for this graph
            # (avoids duplicating EXECUTION entries already captured by the interaction logger)
            covered_node_ids = {str(i.get("task_id", "")) for i in interactions if i.get("interaction_type") == "EXECUTION" or i.get("source") == "neo4j_interaction"}
            nodes = await neo4j.run_query(
                """
                MATCH (n:TaskNode {graph_id: $graph_id})
                WHERE n.status IN ['SUCCESS', 'FAILED', 'CORRECTING']
                RETURN n ORDER BY n.depth, n.created_at
                """,
                {"graph_id": graph_id},
                trace_id=trace_id,
            )

            for row in (nodes or []):
                node = dict(row["n"])
                node_id = str(node.get("node_id", ""))
                # Skip if already covered by an AgentInteraction
                if node_id in covered_node_ids:
                    continue
                interactions.append({
                    "event_type": "task_execution",
                    "node_id": node_id,
                    "task_description": str(node.get("description", "")),
                    "status": str(node.get("status", "")),
                    "score": node.get("score"),
                    "depth": node.get("depth"),
                    "execution_time_ms": node.get("execution_time_ms"),
                    "assigned_agent": str(node.get("assigned_agent_id", "") or ""),
                    "assigned_agent_name": str(node.get("assigned_agent_name", "") or ""),
                    "bid_confidence": node.get("bid_confidence"),
                    "timestamp": str(node.get("updated_at", node.get("created_at", ""))),
                })

        # Also query MySQL agent_interactions table for full payloads
        mysql_interactions = []
        if graph_ids:
            try:
                from app.services.interaction_logger import InteractionLogger
                il = InteractionLogger(neo4j)
                mysql_interactions = await il.get_interactions_from_mysql(
                    graph_ids=graph_ids,
                    trace_id=trace_id,
                )
                for mi in mysql_interactions:
                    mi["source"] = "mysql"
            except Exception as exc:
                logger.debug(
                    "MySQL interaction query failed (non-fatal)",
                    layer="router",
                    error=str(exc),
                    trace_id=trace_id,
                )

        # Query sub-agent spawning relationships
        sub_agent_rels = []
        for graph_id in graph_ids:
            try:
                rels = await neo4j.run_query(
                    """
                    MATCH (child:TaskNode {graph_id: $graph_id})-[:SPAWNED_BY]->(parent:TaskNode)
                    WHERE child.node_type = 'SUB_AGENT'
                    RETURN child.node_id as child_id, parent.node_id as parent_id,
                           child.assigned_agent_name as agent_name, child.depth as depth,
                           child.status as status, child.score as score,
                           child.execution_time_ms as latency_ms
                    """,
                    {"graph_id": graph_id},
                    trace_id=trace_id,
                )
                sub_agent_rels.extend(rels or [])
            except Exception:
                pass

        return {
            "interactions": interactions,
            "mysql_interactions": mysql_interactions,
            "sub_agent_relationships": sub_agent_rels,
            "trace_id": trace_id,
        }
    except Exception as exc:
        logger.error("Interactions fetch failed", layer="router", error=str(exc), trace_id=trace_id)
        return {"interactions": [], "mysql_interactions": [], "sub_agent_relationships": [], "error": str(exc), "trace_id": trace_id}
