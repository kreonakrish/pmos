"""Fire-and-forget interaction logger.

Logs every agent interaction to Neo4j (AgentInteraction node) and
best-effort to MySQL (agent_interactions table).
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Dict, List, Optional

import mysql.connector

from app.adapters.neo4j_adapter import Neo4jAdapter
from app.config import settings
from app.utils.logger import logger


class InteractionLogger:
    """Logs agent interactions to Neo4j and MySQL (best-effort)."""

    def __init__(self, neo4j: Neo4jAdapter) -> None:
        self._neo4j = neo4j

    async def log_interaction(
        self,
        task_id: str,
        graph_id: str,
        agent_id: str,
        agent_name: str,
        interaction_type: str,
        description: str,
        request_payload: Optional[Dict[str, Any]] = None,
        response_payload: Optional[Dict[str, Any]] = None,
        score: Optional[float] = None,
        latency_ms: int = 0,
        tools_used: Optional[List[str]] = None,
        bid_confidence: Optional[float] = None,
        trace_id: str = "",
    ) -> None:
        """Log interaction fire-and-forget. Does not raise on failure."""
        asyncio.create_task(
            self._log_interaction_impl(
                task_id=task_id,
                graph_id=graph_id,
                agent_id=agent_id,
                agent_name=agent_name,
                interaction_type=interaction_type,
                description=description,
                request_payload=request_payload,
                response_payload=response_payload,
                score=score,
                latency_ms=latency_ms,
                tools_used=tools_used,
                bid_confidence=bid_confidence,
                trace_id=trace_id,
            )
        )

    async def _log_interaction_impl(
        self,
        task_id: str,
        graph_id: str,
        agent_id: str,
        agent_name: str,
        interaction_type: str,
        description: str,
        request_payload: Optional[Dict[str, Any]] = None,
        response_payload: Optional[Dict[str, Any]] = None,
        score: Optional[float] = None,
        latency_ms: int = 0,
        tools_used: Optional[List[str]] = None,
        bid_confidence: Optional[float] = None,
        trace_id: str = "",
    ) -> None:
        """Internal implementation. Writes to Neo4j and MySQL independently."""
        interaction_id = str(uuid.uuid4())

        # Write to Neo4j
        try:
            await self._log_to_neo4j(
                interaction_id=interaction_id,
                task_id=task_id,
                graph_id=graph_id,
                agent_id=agent_id,
                agent_name=agent_name,
                interaction_type=interaction_type,
                description=description,
                score=score,
                latency_ms=latency_ms,
                tools_used=tools_used or [],
                bid_confidence=bid_confidence,
                trace_id=trace_id,
            )
        except Exception as exc:
            logger.warning(
                "Failed to log interaction to Neo4j",
                layer="service",
                interaction_id=interaction_id,
                error=str(exc),
                trace_id=trace_id,
            )

        # Write to MySQL (best-effort, table may not exist)
        try:
            await asyncio.get_event_loop().run_in_executor(
                None,
                self._log_to_mysql,
                interaction_id,
                task_id,
                graph_id,
                agent_id,
                agent_name,
                interaction_type,
                description,
                request_payload,
                response_payload,
                score,
                latency_ms,
                tools_used,
                bid_confidence,
                trace_id,
            )
        except Exception as exc:
            logger.debug(
                "Failed to log interaction to MySQL (table may not exist yet)",
                layer="service",
                interaction_id=interaction_id,
                error=str(exc),
                trace_id=trace_id,
            )

    async def _log_to_neo4j(
        self,
        interaction_id: str,
        task_id: str,
        graph_id: str,
        agent_id: str,
        agent_name: str,
        interaction_type: str,
        description: str,
        score: Optional[float],
        latency_ms: int,
        tools_used: List[str],
        bid_confidence: Optional[float],
        trace_id: str,
    ) -> None:
        """Create an AgentInteraction node linked to the TaskNode."""
        cypher = """
        CREATE (i:AgentInteraction {
            interaction_id: $interaction_id,
            task_id: $task_id,
            graph_id: $graph_id,
            agent_id: $agent_id,
            agent_name: $agent_name,
            interaction_type: $interaction_type,
            description: $description,
            score: $score,
            latency_ms: $latency_ms,
            tools_used: $tools_used,
            bid_confidence: $bid_confidence,
            trace_id: $trace_id,
            timestamp: datetime()
        })
        WITH i
        OPTIONAL MATCH (n:TaskNode {node_id: $task_id})
        FOREACH (_ IN CASE WHEN n IS NOT NULL THEN [1] ELSE [] END |
            CREATE (n)-[:HAS_INTERACTION]->(i)
        )
        """
        await self._neo4j.run_query(
            cypher,
            {
                "interaction_id": interaction_id,
                "task_id": task_id,
                "graph_id": graph_id,
                "agent_id": agent_id,
                "agent_name": agent_name,
                "interaction_type": interaction_type,
                "description": description[:500],
                "score": score,
                "latency_ms": latency_ms,
                "tools_used": tools_used,
                "bid_confidence": bid_confidence,
                "trace_id": trace_id,
            },
            trace_id=trace_id,
        )

    def _log_to_mysql(
        self,
        interaction_id: str,
        task_id: str,
        graph_id: str,
        agent_id: str,
        agent_name: str,
        interaction_type: str,
        description: str,
        request_payload: Optional[Dict[str, Any]],
        response_payload: Optional[Dict[str, Any]],
        score: Optional[float],
        latency_ms: int,
        tools_used: Optional[List[str]],
        bid_confidence: Optional[float],
        trace_id: str,
    ) -> None:
        """Synchronous MySQL write (runs in executor). Best-effort."""
        conn = None
        cursor = None
        try:
            conn = mysql.connector.connect(
                host=settings.mysql_host,
                port=settings.mysql_port,
                user=settings.mysql_user,
                password=settings.mysql_password,
                database=settings.mysql_db,
            )
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO agent_interactions
                    (interaction_id, task_id, graph_id, agent_id, agent_name,
                     interaction_type, description, request_payload, response_payload,
                     score, latency_ms, tools_used, bid_confidence, trace_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    interaction_id,
                    task_id,
                    graph_id,
                    agent_id,
                    agent_name,
                    interaction_type,
                    description[:1000],
                    json.dumps(request_payload) if request_payload else None,
                    json.dumps(response_payload, default=str) if response_payload else None,
                    score,
                    latency_ms,
                    json.dumps(tools_used) if tools_used else None,
                    bid_confidence,
                    trace_id,
                ),
            )
            conn.commit()
        except mysql.connector.ProgrammingError:
            # Table doesn't exist yet - that's OK
            pass
        except Exception:
            raise
        finally:
            if cursor is not None:
                cursor.close()
            if conn is not None:
                conn.close()

    # ------------------------------------------------------------------
    # Query interactions (for the conversations endpoint)
    # ------------------------------------------------------------------

    async def get_interactions_from_mysql(
        self,
        graph_ids: List[str],
        trace_id: str = "",
    ) -> List[Dict[str, Any]]:
        """Fetch interactions from MySQL for given graph IDs. Returns [] if table missing."""
        if not graph_ids:
            return []

        def _query():
            conn = None
            cursor = None
            try:
                conn = mysql.connector.connect(
                    host=settings.mysql_host,
                    port=settings.mysql_port,
                    user=settings.mysql_user,
                    password=settings.mysql_password,
                    database=settings.mysql_db,
                )
                cursor = conn.cursor(dictionary=True)
                placeholders = ",".join(["%s"] * len(graph_ids))
                cursor.execute(
                    f"""
                    SELECT interaction_id, task_id, graph_id, agent_id, agent_name,
                           interaction_type, description, request_payload, response_payload,
                           score, latency_ms, tools_used, bid_confidence, trace_id, created_at
                    FROM agent_interactions
                    WHERE graph_id IN ({placeholders})
                    ORDER BY created_at ASC
                    """,
                    graph_ids,
                )
                rows = cursor.fetchall()
                result = []
                for row in rows:
                    # Parse JSON columns
                    for json_col in ("request_payload", "response_payload", "tools_used"):
                        if row.get(json_col) and isinstance(row[json_col], str):
                            try:
                                row[json_col] = json.loads(row[json_col])
                            except (json.JSONDecodeError, ValueError):
                                pass
                    # Serialize datetime
                    if row.get("created_at"):
                        from datetime import datetime
                        if isinstance(row["created_at"], datetime):
                            row["created_at"] = row["created_at"].isoformat()
                    result.append(row)
                return result
            except mysql.connector.ProgrammingError:
                return []
            except Exception as exc:
                logger.debug(
                    "MySQL interaction query failed",
                    layer="service",
                    error=str(exc),
                    trace_id=trace_id,
                )
                return []
            finally:
                if cursor is not None:
                    cursor.close()
                if conn is not None:
                    conn.close()

        return await asyncio.get_event_loop().run_in_executor(None, _query)
