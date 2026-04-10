"""Neo4j TaskNode creation and living graph expansion.

CRITICAL INVARIANT: Every intermediate LLM response that contains sub-questions
MUST result in new TaskNode creation in Neo4j BEFORE the next execution step.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Dict, List, Optional

from app.adapters.neo4j_adapter import Neo4jAdapter
from app.models.task import Criticality, NodeType, TaskGraph, TaskNode
from app.utils.logger import logger


class GraphManager:
    """Manages the living task graph in Neo4j."""

    def __init__(self, neo4j: Neo4jAdapter) -> None:
        self._neo4j = neo4j

    # ------------------------------------------------------------------
    # Graph & node creation
    # ------------------------------------------------------------------

    async def create_graph(
        self,
        session_id: str,
        user_request: str,
        trace_id: str = "",
        conversation_id: str = "",
        team_id: str = "",
    ) -> str:
        graph_id = str(uuid.uuid4())
        await self._neo4j.create_task_graph(
            graph_id=graph_id,
            session_id=session_id,
            user_request=user_request,
            trace_id=trace_id,
            conversation_id=conversation_id,
            team_id=team_id,
        )
        logger.info(
            "Task graph created",
            layer="service",
            graph_id=graph_id,
            session_id=session_id,
            trace_id=trace_id,
        )
        return graph_id

    async def add_root_node(
        self,
        graph_id: str,
        description: str,
        criticality: str = Criticality.MEDIUM,
        trace_id: str = "",
    ) -> str:
        node_id = str(uuid.uuid4())
        await self._neo4j.create_task_node(
            node_id=node_id,
            graph_id=graph_id,
            parent_id=None,
            description=description,
            node_type=NodeType.ROOT,
            criticality=criticality,
            depth=0,
            iteration=0,
            trace_id=trace_id,
        )
        logger.info(
            "Root TaskNode created",
            layer="service",
            node_id=node_id,
            graph_id=graph_id,
            trace_id=trace_id,
        )
        return node_id

    async def add_node(
        self,
        graph_id: str,
        parent_id: Optional[str],
        description: str,
        node_type: str = NodeType.SUBTASK,
        criticality: str = Criticality.MEDIUM,
        depth: int = 1,
        iteration: int = 0,
        max_retries: int = 3,
        trace_id: str = "",
    ) -> str:
        node_id = str(uuid.uuid4())
        await self._neo4j.create_task_node(
            node_id=node_id,
            graph_id=graph_id,
            parent_id=parent_id,
            description=description,
            node_type=node_type,
            criticality=criticality,
            depth=depth,
            iteration=iteration,
            max_retries=max_retries,
            trace_id=trace_id,
        )
        return node_id

    # ------------------------------------------------------------------
    # Living graph expansion
    # ------------------------------------------------------------------

    async def expand_graph_from_response(
        self,
        graph_id: str,
        parent_node_id: str,
        llm_response: str,
        iteration: int,
        parent_depth: int = 0,
        trace_id: str = "",
    ) -> List[str]:
        """
        Parse LLM response for sub-questions / sub-tasks.
        For each one found, create a new TaskNode in Neo4j linked with SPAWNED_BY.
        Returns list of new node_ids.

        CRITICAL: All nodes MUST be created before returning — guaranteeing the
        living graph invariant.
        """
        sub_tasks = self._extract_sub_tasks(llm_response)
        if not sub_tasks:
            logger.debug(
                "No sub-tasks found in LLM response; graph not expanded",
                layer="service",
                graph_id=graph_id,
                parent_node_id=parent_node_id,
                trace_id=trace_id,
            )
            return []

        new_node_ids: List[str] = []
        for sub_task in sub_tasks:
            node_id = await self.add_node(
                graph_id=graph_id,
                parent_id=parent_node_id,
                description=sub_task,
                node_type=NodeType.SUBTASK,
                criticality=Criticality.MEDIUM,
                depth=parent_depth + 1,
                iteration=iteration,
                trace_id=trace_id,
            )
            new_node_ids.append(node_id)
            logger.info(
                "TaskNode spawned from intermediate response",
                layer="service",
                node_id=node_id,
                parent_node_id=parent_node_id,
                graph_id=graph_id,
                iteration=iteration,
                description=sub_task[:80],
                trace_id=trace_id,
            )

        return new_node_ids

    def _extract_sub_tasks(self, llm_response: str) -> List[str]:
        """
        Heuristic extractor for sub-questions / sub-tasks embedded in an LLM response.
        Looks for:
          - Numbered lists  (1. ... / 1) ...)
          - Bullet lists    (- ... / * ...)
          - Lines ending with '?'
        """
        sub_tasks: List[str] = []

        # Try JSON array first (structured output)
        try:
            parsed = json.loads(llm_response)
            if isinstance(parsed, list):
                return [str(item) for item in parsed if item]
            if isinstance(parsed, dict) and "sub_tasks" in parsed:
                return [str(t) for t in parsed["sub_tasks"] if t]
        except (json.JSONDecodeError, ValueError):
            pass

        # Numbered list items: "1. task" or "1) task"
        numbered = re.findall(r"^\s*\d+[.)]\s+(.+)", llm_response, re.MULTILINE)
        if numbered:
            return [t.strip() for t in numbered if t.strip()]

        # Bullet list items
        bulleted = re.findall(r"^\s*[-*]\s+(.+)", llm_response, re.MULTILINE)
        if bulleted:
            return [t.strip() for t in bulleted if t.strip()]

        # Lines ending with a question mark
        questions = re.findall(r"([^\n.!?]+\?)", llm_response)
        if questions:
            return [q.strip() for q in questions if len(q.strip()) > 10]

        return sub_tasks

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------

    async def mark_node_running(self, node_id: str, trace_id: str = "") -> None:
        await self._neo4j.update_task_node_status(node_id, "RUNNING", trace_id=trace_id)

    async def mark_node_success(
        self, node_id: str, score: float, execution_time_ms: int, trace_id: str = ""
    ) -> None:
        await self._neo4j.update_task_node_status(
            node_id, "SUCCESS", score=score, execution_time_ms=execution_time_ms, trace_id=trace_id
        )

    async def mark_node_failed(
        self, node_id: str, score: Optional[float] = None, trace_id: str = ""
    ) -> None:
        await self._neo4j.update_task_node_status(node_id, "FAILED", score=score, trace_id=trace_id)

    async def mark_node_correcting(self, node_id: str, trace_id: str = "") -> None:
        await self._neo4j.update_task_node_status(node_id, "CORRECTING", trace_id=trace_id)

    async def get_graph_nodes(self, graph_id: str, trace_id: str = "") -> List[Dict[str, Any]]:
        return await self._neo4j.get_graph_nodes(graph_id, trace_id=trace_id)
