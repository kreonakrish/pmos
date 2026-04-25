"""Neo4j async driver wrapper for the orchestrator service."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from neo4j import AsyncGraphDatabase, AsyncDriver
from neo4j.exceptions import ServiceUnavailable

from app.config import settings
from app.utils.logger import logger


class Neo4jAdapter:
    """Wraps the neo4j AsyncDriver with structured logging and health check.

    Accepts an optional ``name`` plus per-instance connection overrides so
    callers can spin up a second adapter bound to a different Neo4j (e.g. the
    Business Ontology graph) without duplicating the class.
    """

    def __init__(
        self,
        name: str = "execution",
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        database: Optional[str] = None,
    ) -> None:
        self._driver: Optional[AsyncDriver] = None
        self.name = name
        self._uri = uri if uri is not None else settings.neo4j_uri
        self._user = user if user is not None else settings.neo4j_user
        self._password = password if password is not None else settings.neo4j_password
        self._database = database if database is not None else settings.neo4j_database

    async def connect(self) -> None:
        self._driver = AsyncGraphDatabase.driver(
            self._uri,
            auth=(self._user, self._password),
        )
        logger.info(
            "Neo4j driver initialised",
            layer="adapter",
            name=self.name,
            target=self._uri,
        )

    async def close(self) -> None:
        if self._driver:
            await self._driver.close()
            logger.info("Neo4j driver closed", layer="adapter", name=self.name)

    async def health_check(self) -> bool:
        try:
            async with self._driver.session(database=self._database) as session:
                await session.run("RETURN 1")
            return True
        except Exception as exc:
            logger.error(
                "Neo4j health check failed",
                layer="adapter",
                name=self.name,
                error=str(exc),
            )
            return False

    async def run_query(
        self,
        cypher: str,
        parameters: Optional[Dict[str, Any]] = None,
        trace_id: str = "",
    ) -> List[Dict[str, Any]]:
        """Execute a Cypher query and return list of record dicts."""
        params = parameters or {}
        async with self._driver.session(database=self._database) as session:
            result = await session.run(cypher, **params)
            records = await result.data()
        logger.debug(
            "Neo4j query executed",
            layer="adapter",
            name=self.name,
            cypher=cypher[:120],
            rows=len(records),
            trace_id=trace_id,
        )
        return records

    # ------------------------------------------------------------------
    # TaskGraph helpers
    # ------------------------------------------------------------------

    async def create_task_graph(
        self,
        graph_id: str,
        session_id: str,
        user_request: str,
        trace_id: str = "",
        conversation_id: str = "",
        team_id: str = "",
    ) -> None:
        cypher = """
        CREATE (g:TaskGraph {
          graph_id: $graph_id,
          session_id: $session_id,
          conversation_id: $conversation_id,
          team_id: $team_id,
          user_request: $user_request,
          current_iteration: 0,
          status: 'CONSTRUCTING',
          created_at: datetime(),
          updated_at: datetime()
        })
        """
        await self.run_query(
            cypher,
            {"graph_id": graph_id, "session_id": session_id,
             "conversation_id": conversation_id, "team_id": team_id,
             "user_request": user_request},
            trace_id=trace_id,
        )

    async def create_task_node(
        self,
        node_id: str,
        graph_id: str,
        parent_id: Optional[str],
        description: str,
        node_type: str,
        criticality: str,
        depth: int,
        iteration: int,
        max_retries: int = 3,
        trace_id: str = "",
        canonical_entities: Optional[List[str]] = None,
        dataset_bindings: Optional[List[str]] = None,
        intent: Optional[str] = None,
        domain: Optional[str] = None,
        ontology_versions: Optional[List[str]] = None,
    ) -> None:
        cypher = """
        CREATE (n:TaskNode {
          node_id: $node_id,
          graph_id: $graph_id,
          parent_id: $parent_id,
          description: $description,
          node_type: $node_type,
          status: 'PENDING',
          depth: $depth,
          iteration: $iteration,
          criticality: $criticality,
          max_retries: $max_retries,
          retry_count: 0,
          canonical_entities: $canonical_entities,
          dataset_bindings: $dataset_bindings,
          intent: $intent,
          domain: $domain,
          ontology_versions: $ontology_versions,
          created_at: datetime()
        })
        """
        await self.run_query(
            cypher,
            {
                "node_id": node_id,
                "graph_id": graph_id,
                "parent_id": parent_id,
                "description": description,
                "node_type": node_type,
                "depth": depth,
                "iteration": iteration,
                "criticality": criticality,
                "max_retries": max_retries,
                "canonical_entities": canonical_entities or [],
                "dataset_bindings": dataset_bindings or [],
                "intent": intent,
                "domain": domain,
                "ontology_versions": ontology_versions or [],
            },
            trace_id=trace_id,
        )
        if parent_id:
            await self.link_spawned_by(node_id, parent_id, trace_id=trace_id)

    async def link_spawned_by(
        self, child_id: str, parent_id: str, trace_id: str = ""
    ) -> None:
        cypher = """
        MATCH (child:TaskNode {node_id: $child_id})
        MATCH (parent:TaskNode {node_id: $parent_id})
        CREATE (child)-[:SPAWNED_BY]->(parent)
        """
        await self.run_query(
            cypher,
            {"child_id": child_id, "parent_id": parent_id},
            trace_id=trace_id,
        )

    async def update_task_node_status(
        self,
        node_id: str,
        status: str,
        score: Optional[float] = None,
        execution_time_ms: Optional[int] = None,
        trace_id: str = "",
    ) -> None:
        sets = ["n.status = $status", "n.updated_at = datetime()"]
        params: Dict[str, Any] = {"node_id": node_id, "status": status}
        if score is not None:
            sets.append("n.score = $score")
            params["score"] = score
        if execution_time_ms is not None:
            sets.append("n.execution_time_ms = $execution_time_ms")
            params["execution_time_ms"] = execution_time_ms
        cypher = f"MATCH (n:TaskNode {{node_id: $node_id}}) SET {', '.join(sets)}"
        await self.run_query(cypher, params, trace_id=trace_id)

    async def update_graph_status(
        self, graph_id: str, status: str, iteration: Optional[int] = None, trace_id: str = ""
    ) -> None:
        sets = ["g.status = $status", "g.updated_at = datetime()"]
        params: Dict[str, Any] = {"graph_id": graph_id, "status": status}
        if iteration is not None:
            sets.append("g.current_iteration = $iteration")
            params["iteration"] = iteration
        cypher = f"MATCH (g:TaskGraph {{graph_id: $graph_id}}) SET {', '.join(sets)}"
        await self.run_query(cypher, params, trace_id=trace_id)

    async def get_graph_nodes(self, graph_id: str, trace_id: str = "") -> List[Dict[str, Any]]:
        cypher = """
        MATCH (n:TaskNode {graph_id: $graph_id})
        RETURN n
        ORDER BY n.depth ASC, n.created_at ASC
        """
        rows = await self.run_query(cypher, {"graph_id": graph_id}, trace_id=trace_id)
        return [dict(row["n"]) for row in rows]

    async def get_sub_agent_tree(self, parent_node_id: str, trace_id: str = "") -> List[Dict[str, Any]]:
        """Get all sub-agent TaskNodes spawned from a parent node."""
        cypher = """
        MATCH (parent:TaskNode {node_id: $parent_node_id})<-[:SPAWNED_BY*1..10]-(child:TaskNode)
        WHERE child.node_type = 'SUB_AGENT'
        RETURN child
        ORDER BY child.depth ASC, child.created_at ASC
        """
        rows = await self.run_query(cypher, {"parent_node_id": parent_node_id}, trace_id=trace_id)
        return [dict(row["child"]) for row in rows]

    async def get_team_agents(self, team_id: str, trace_id: str = "") -> List[Dict[str, Any]]:
        cypher = """
        MATCH (t:Team {team_id: $team_id})<-[r:MEMBER_OF]-(a:Agent)
        WHERE a.status IN ['IDLE', 'ACTIVE']
        RETURN a, r.role as role, r.priority as priority, r.execution_mode as execution_mode,
               r.criticality as criticality, r.timeout_seconds as timeout_seconds
        ORDER BY CASE WHEN r.role = 'orchestrator' THEN 0 ELSE 1 END,
                 r.priority ASC, a.accuracy_rate DESC
        """
        rows = await self.run_query(cypher, {"team_id": team_id}, trace_id=trace_id)
        results = []
        for row in rows:
            agent_data = dict(row["a"])
            agent_data["role"] = row.get("role")
            agent_data["priority"] = row.get("priority")
            agent_data["execution_mode"] = row.get("execution_mode")
            agent_data["criticality"] = row.get("criticality")
            agent_data["timeout_seconds"] = row.get("timeout_seconds")
            results.append(agent_data)
        return results

    async def load_team_for_conversation(
        self,
        team_data: Dict[str, Any],
        conversation_id: str,
        trace_id: str = "",
    ) -> None:
        """Load team hierarchy from MySQL data into Neo4j for a conversation.

        Creates/merges:
        - Team node
        - Agent nodes for each team member
        - MEMBER_OF relationships with hierarchy metadata
        - REPORTS_TO relationships for parent-child hierarchy
        """
        team_id = team_data.get("team_id", "")
        team_name = team_data.get("name", "")
        agents = team_data.get("agents", [])

        # 1. MERGE the Team node
        await self.run_query(
            """
            MERGE (t:Team {team_id: $team_id})
            SET t.name = $name, t.conversation_id = $conversation_id, t.updated_at = datetime()
            """,
            {"team_id": team_id, "name": team_name, "conversation_id": conversation_id},
            trace_id=trace_id,
        )

        # 2. For each agent, MERGE Agent node and MEMBER_OF relationship
        for agent in agents:
            agent_id = str(agent.get("agent_id", ""))
            await self.run_query(
                """
                MERGE (a:Agent {agent_id: $agent_id})
                SET a.name = $name,
                    a.status = $status,
                    a.role = $role,
                    a.accuracy_rate = $accuracy,
                    a.success_rate = $success_rate,
                    a.foundation_model = $model,
                    a.updated_at = datetime()
                """,
                {
                    "agent_id": agent_id,
                    "name": str(agent.get("agent_name", agent.get("name", ""))),
                    "status": str(agent.get("agent_status", agent.get("status", "IDLE"))),
                    "role": str(agent.get("role", "specialist")),
                    "accuracy": float(agent.get("accuracy", 0.5)),
                    "success_rate": float(agent.get("success_rate", 0.5)),
                    "model": str(agent.get("foundation_model", "")),
                },
                trace_id=trace_id,
            )

            # Create MEMBER_OF relationship
            await self.run_query(
                """
                MATCH (a:Agent {agent_id: $agent_id}), (t:Team {team_id: $team_id})
                MERGE (a)-[r:MEMBER_OF]->(t)
                SET r.priority = $priority,
                    r.role = $role,
                    r.execution_mode = $execution_mode,
                    r.criticality = $criticality,
                    r.timeout_seconds = $timeout_seconds
                """,
                {
                    "agent_id": agent_id,
                    "team_id": team_id,
                    "priority": int(agent.get("priority", 0)),
                    "role": str(agent.get("role", "specialist")),
                    "execution_mode": str(agent.get("execution_mode", "sequential")),
                    "criticality": str(agent.get("criticality", "MEDIUM")),
                    "timeout_seconds": int(agent.get("timeout_seconds", 30)),
                },
                trace_id=trace_id,
            )

        # 3. Create REPORTS_TO relationships for agents with parent_agent_id
        for agent in agents:
            parent_id = agent.get("parent_agent_id")
            if parent_id:
                child_id = str(agent.get("agent_id", ""))
                await self.run_query(
                    """
                    MATCH (child:Agent {agent_id: $child_id}), (parent:Agent {agent_id: $parent_id})
                    MERGE (child)-[:REPORTS_TO]->(parent)
                    """,
                    {"child_id": child_id, "parent_id": str(parent_id)},
                    trace_id=trace_id,
                )

        logger.info(
            "Team hierarchy loaded into Neo4j",
            layer="adapter",
            team_id=team_id,
            agent_count=len(agents),
            conversation_id=conversation_id,
            trace_id=trace_id,
        )

    async def create_execution_event(
        self,
        event_id: str,
        event_type: str,
        agent_id: str,
        node_id: str,
        score: Optional[float],
        action_taken: str,
        correlation_id: str,
        trace_id: str = "",
    ) -> None:
        cypher = """
        CREATE (e:ExecutionEvent {
          event_id: $event_id,
          event_type: $event_type,
          agent_id: $agent_id,
          node_id: $node_id,
          score: $score,
          action_taken: $action_taken,
          correlation_id: $correlation_id,
          timestamp: datetime()
        })
        WITH e
        MATCH (n:TaskNode {node_id: $node_id})
        CREATE (n)-[:PRODUCED_EVENT]->(e)
        """
        await self.run_query(
            cypher,
            {
                "event_id": event_id,
                "event_type": event_type,
                "agent_id": agent_id,
                "node_id": node_id,
                "score": score,
                "action_taken": action_taken,
                "correlation_id": correlation_id,
            },
            trace_id=trace_id,
        )
