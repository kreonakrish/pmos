"""Primary + fallback agent selection from Neo4j — hierarchy-aware."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.adapters.neo4j_adapter import Neo4jAdapter
from app.utils.logger import logger


@dataclass
class Agent:
    agent_id: str
    name: str = ""
    status: str = "IDLE"
    accuracy_rate: float = 0.5
    success_rate: float = 0.5
    foundation_model: str = ""
    role: str = "specialist"
    priority: int = 999
    execution_mode: str = "sequential"
    criticality: str = "MEDIUM"
    raw: Dict[str, Any] = field(default_factory=dict)


class AgentSelector:
    """Selects agents from Neo4j respecting team hierarchy and orchestrator role."""

    def __init__(self, neo4j: Neo4jAdapter) -> None:
        self._neo4j = neo4j

    async def select_primary_and_fallbacks(
        self,
        team_id: str,
        task_type: str = "",
        trace_id: str = "",
    ) -> Tuple[Optional[Agent], List[Agent]]:
        """
        Query Neo4j for team members. Returns (orchestrator, specialists).

        1. Find the designated orchestrator (role='orchestrator')
        2. Specialists ordered by priority ASC, accuracy_rate DESC
        3. If no explicit orchestrator, first agent by priority becomes primary
        """
        rows = await self._neo4j.get_team_agents(team_id=team_id, trace_id=trace_id)

        agents = [self._row_to_agent(r) for r in rows]

        if not agents:
            logger.warning(
                "No eligible agents found for team",
                layer="service",
                team_id=team_id,
                task_type=task_type,
                trace_id=trace_id,
            )
            return None, []

        # Find the orchestrator
        orchestrator = None
        specialists: List[Agent] = []

        for agent in agents:
            if agent.role == "orchestrator":
                orchestrator = agent
            else:
                specialists.append(agent)

        # If no explicit orchestrator, use first agent by priority
        if orchestrator is None:
            orchestrator = agents[0]
            specialists = agents[1:]

        # Sort specialists: by priority ASC, then accuracy DESC
        specialists.sort(key=lambda a: (a.priority, -a.accuracy_rate))

        logger.info(
            "Agent selection complete (hierarchy-aware)",
            layer="service",
            team_id=team_id,
            orchestrator=orchestrator.agent_id,
            orchestrator_name=orchestrator.name,
            specialist_count=len(specialists),
            specialist_names=[s.name for s in specialists],
            trace_id=trace_id,
        )
        return orchestrator, specialists

    async def select_best_agent_for_task(
        self,
        specialists: List[Agent],
        task_description: str,
        trace_id: str = "",
    ) -> Optional[Agent]:
        """Select the best specialist for a given task based on success rate."""
        if not specialists:
            return None
        # Simple heuristic: highest success_rate * accuracy_rate
        ranked = sorted(specialists, key=lambda a: -(a.success_rate * a.accuracy_rate))
        return ranked[0]

    def _row_to_agent(self, row: Dict[str, Any]) -> Agent:
        return Agent(
            agent_id=str(row.get("agent_id") or row.get("id") or ""),
            name=str(row.get("name") or ""),
            status=str(row.get("status") or "IDLE"),
            accuracy_rate=float(row.get("accuracy_rate") or 0.5),
            success_rate=float(row.get("success_rate") or 0.5),
            foundation_model=str(row.get("foundation_model") or ""),
            role=str(row.get("role") or "specialist"),
            priority=int(row.get("priority") or 999),
            execution_mode=str(row.get("execution_mode") or "sequential"),
            criticality=str(row.get("criticality") or "MEDIUM"),
            raw=row,
        )
