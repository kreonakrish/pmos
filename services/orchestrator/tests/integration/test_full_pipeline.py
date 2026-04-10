"""Integration test for the full 9-step orchestration pipeline.

Verifies:
- Full pipeline completes without error
- Neo4j nodes created (mock neo4j adapter)
- Memory writes published to Redis (mock redis adapter)
- Score computed and evaluated
"""

from __future__ import annotations

import json
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import pytest

from app.services.pipeline import PipelineService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_subtask_nodes(graph_id: str, root_node_id: str) -> List[Dict[str, Any]]:
    """Return fake graph nodes as Neo4j would."""
    return [
        {
            "node_id": root_node_id,
            "graph_id": graph_id,
            "parent_id": None,
            "description": "Original user request",
            "node_type": "ROOT",
            "status": "PENDING",
            "depth": 0,
            "iteration": 0,
            "criticality": "MEDIUM",
        },
        {
            "node_id": "subtask-node-1",
            "graph_id": graph_id,
            "parent_id": root_node_id,
            "description": "Research the topic",
            "node_type": "SUBTASK",
            "status": "PENDING",
            "depth": 1,
            "iteration": 0,
            "criticality": "MEDIUM",
        },
        {
            "node_id": "subtask-node-2",
            "graph_id": graph_id,
            "parent_id": root_node_id,
            "description": "Summarise findings",
            "node_type": "SUBTASK",
            "status": "PENDING",
            "depth": 1,
            "iteration": 0,
            "criticality": "MEDIUM",
        },
    ]


def _team_agent_rows() -> List[Dict[str, Any]]:
    """Fake Neo4j rows for team agents."""
    return [
        {
            "agent_id": "1",
            "name": "Alpha",
            "status": "IDLE",
            "accuracy_rate": 0.9,
            "success_rate": 0.85,
            "foundation_model": "gpt-4o",
        },
        {
            "agent_id": "2",
            "name": "Beta",
            "status": "IDLE",
            "accuracy_rate": 0.7,
            "success_rate": 0.7,
            "foundation_model": "gpt-4o",
        },
    ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def pipeline_service(
    mock_neo4j, mock_redis, mock_llm, mock_memory, mock_scoring, mock_rag, mock_meta
):
    """Build a PipelineService wired to all mock adapters."""
    return PipelineService(
        neo4j=mock_neo4j,
        redis=mock_redis,
        llm=mock_llm,
        memory=mock_memory,
        scoring=mock_scoring,
        rag=mock_rag,
        meta=mock_meta,
    )


@pytest.fixture
def _configure_neo4j(mock_neo4j):
    """Set up mock_neo4j to return realistic graph data."""
    captured_graph_id = {}
    captured_root_id = {}

    original_create_graph = mock_neo4j.create_task_graph

    async def _create_task_graph(**kwargs):
        captured_graph_id["value"] = kwargs.get("graph_id", "")
        return await original_create_graph(**kwargs)

    original_create_node = mock_neo4j.create_task_node

    async def _create_task_node(**kwargs):
        if kwargs.get("node_type") == "ROOT":
            captured_root_id["value"] = kwargs.get("node_id", "")
        return await original_create_node(**kwargs)

    mock_neo4j.create_task_graph = AsyncMock(side_effect=_create_task_graph)
    mock_neo4j.create_task_node = AsyncMock(side_effect=_create_task_node)

    async def _get_graph_nodes(graph_id, trace_id=""):
        root_id = captured_root_id.get("value", "root-node")
        return _make_subtask_nodes(graph_id, root_id)

    mock_neo4j.get_graph_nodes = AsyncMock(side_effect=_get_graph_nodes)
    mock_neo4j.get_team_agents = AsyncMock(return_value=_team_agent_rows())

    return mock_neo4j


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFullPipeline:
    """End-to-end integration tests for the 9-step pipeline."""

    @pytest.mark.asyncio
    async def test_pipeline_completes_successfully(
        self, pipeline_service, mock_neo4j, mock_redis, mock_llm, mock_scoring,
        mock_memory, _configure_neo4j,
    ):
        """Full pipeline executes all 9 steps and returns a valid result."""
        # LLM returns: decomposition JSON on first call, task responses next,
        # then aggregation response.
        mock_llm.complete = AsyncMock(
            side_effect=[
                '["Research the topic", "Summarise findings"]',  # Step 2: decomposition
                "Detailed research results on the topic.",       # Step 4: node 1 execution
                "Summary of all findings.",                      # Step 4: node 2 execution
                "Final synthesised answer for the user.",        # Step 8: aggregation
            ]
        )

        result = await pipeline_service.execute(
            conversation_id="conv-001",
            message="Explain quantum computing",
            team_id="team-alpha",
            trace_id="trace-integration-001",
        )

        # Pipeline returns expected structure
        assert result is not None
        assert "session_id" in result
        assert "graph_id" in result
        assert "response" in result
        assert result["response"] == "Final synthesised answer for the user."
        assert result["trace_id"] == "trace-integration-001"

    @pytest.mark.asyncio
    async def test_neo4j_nodes_created(
        self, pipeline_service, mock_neo4j, mock_llm, mock_scoring,
        mock_memory, mock_redis, _configure_neo4j,
    ):
        """Verify that TaskGraph, root TaskNode, and sub-task TaskNodes are created."""
        mock_llm.complete = AsyncMock(
            side_effect=[
                '["Sub-task A", "Sub-task B"]',
                "Result for sub-task A.",
                "Result for sub-task B.",
                "Aggregated final response.",
            ]
        )

        await pipeline_service.execute(
            conversation_id="conv-002",
            message="Build a REST API",
            team_id="team-alpha",
            trace_id="trace-integration-002",
        )

        # TaskGraph creation
        mock_neo4j.create_task_graph.assert_called_once()
        graph_call_kwargs = mock_neo4j.create_task_graph.call_args.kwargs
        assert graph_call_kwargs["user_request"] == "Build a REST API"
        assert graph_call_kwargs["trace_id"] == "trace-integration-002"

        # TaskNode creation: 1 root + 2 sub-tasks = at least 3 calls
        assert mock_neo4j.create_task_node.call_count >= 3

        # Verify root node was created with node_type ROOT
        root_calls = [
            c for c in mock_neo4j.create_task_node.call_args_list
            if c.kwargs.get("node_type") == "ROOT"
        ]
        assert len(root_calls) == 1

        # Verify sub-task nodes created
        subtask_calls = [
            c for c in mock_neo4j.create_task_node.call_args_list
            if c.kwargs.get("node_type") == "SUBTASK"
        ]
        assert len(subtask_calls) >= 2

        # Graph status updated to EXECUTING then COMPLETED
        status_calls = mock_neo4j.update_graph_status.call_args_list
        statuses = [c.args[1] if len(c.args) > 1 else c.kwargs.get("status") for c in status_calls]
        assert "EXECUTING" in statuses
        assert "COMPLETED" in statuses

    @pytest.mark.asyncio
    async def test_memory_writes_published_to_redis(
        self, pipeline_service, mock_neo4j, mock_redis, mock_llm,
        mock_scoring, mock_memory, _configure_neo4j,
    ):
        """Verify that episodic memory writes are published to Redis stream."""
        mock_llm.complete = AsyncMock(
            side_effect=[
                '["Analyse data", "Summarise findings"]',  # Step 2: decomposition
                "Analysis complete.",                        # Step 4: node 1
                "Final analysis report.",                    # Step 4: node 2
                "Synthesised analysis output.",              # Step 8: aggregation
            ]
        )

        await pipeline_service.execute(
            conversation_id="conv-003",
            message="Analyse the dataset",
            team_id="team-alpha",
            trace_id="trace-integration-003",
        )

        # Step 9: memory write published
        mock_redis.publish_memory_write.assert_called_once()
        mem_call_kwargs = mock_redis.publish_memory_write.call_args.kwargs
        assert mem_call_kwargs["tier"] == "episodic"
        assert mem_call_kwargs["trace_id"] == "trace-integration-003"
        assert mem_call_kwargs["agent_id"] == 1  # first agent from team

        # Telemetry events published (session_started + session_completed)
        assert mock_redis.publish_telemetry.call_count >= 2

    @pytest.mark.asyncio
    async def test_scoring_evaluated_for_each_node(
        self, pipeline_service, mock_neo4j, mock_redis, mock_llm,
        mock_scoring, mock_memory, _configure_neo4j,
    ):
        """Verify that each sub-task node is scored via the scoring adapter."""
        mock_llm.complete = AsyncMock(
            side_effect=[
                '["Task 1", "Task 2"]',
                "Response for task 1.",
                "Response for task 2.",
                "Aggregated answer.",
            ]
        )

        result = await pipeline_service.execute(
            conversation_id="conv-004",
            message="Write unit tests",
            team_id="team-alpha",
            trace_id="trace-integration-004",
        )

        # Scoring evaluate called for each sub-task node
        assert mock_scoring.evaluate.call_count >= 2

        # Each call includes required fields
        for call in mock_scoring.evaluate.call_args_list:
            kwargs = call.kwargs
            assert "agent_id" in kwargs
            assert "task_id" in kwargs
            assert "response_text" in kwargs
            assert "latency_ms" in kwargs
            assert "trace_id" in kwargs

        # Result includes a score
        assert result.get("score") is not None

    @pytest.mark.asyncio
    async def test_pipeline_handles_no_agents_gracefully(
        self, pipeline_service, mock_neo4j, mock_redis, mock_llm,
        mock_scoring, mock_memory,
    ):
        """Pipeline still works when no agents are found (uses default LLM)."""
        # No agents available
        mock_neo4j.get_team_agents = AsyncMock(return_value=[])
        mock_neo4j.get_graph_nodes = AsyncMock(return_value=[
            {
                "node_id": "sub-1",
                "graph_id": "g-1",
                "parent_id": "root-1",
                "description": "Only task",
                "node_type": "SUBTASK",
                "status": "PENDING",
                "depth": 1,
                "iteration": 0,
                "criticality": "MEDIUM",
            },
        ])

        mock_llm.complete = AsyncMock(
            side_effect=[
                '["Only task"]',
                "Task completed without agent.",
                "Final result.",
            ]
        )

        result = await pipeline_service.execute(
            conversation_id="conv-005",
            message="Simple question",
            team_id="team-empty",
            trace_id="trace-integration-005",
        )

        assert result is not None
        assert "response" in result

    @pytest.mark.asyncio
    async def test_pipeline_node_status_transitions(
        self, pipeline_service, mock_neo4j, mock_redis, mock_llm,
        mock_scoring, mock_memory, _configure_neo4j,
    ):
        """Verify node status transitions: PENDING -> RUNNING -> SUCCESS."""
        mock_llm.complete = AsyncMock(
            side_effect=[
                '["Check status", "Verify results"]',  # Step 2: decomposition
                "Status verified.",                      # Step 4: node 1
                "Results confirmed.",                    # Step 4: node 2
                "All checks passed.",                    # Step 8: aggregation
            ]
        )

        await pipeline_service.execute(
            conversation_id="conv-006",
            message="Run status check",
            team_id="team-alpha",
            trace_id="trace-integration-006",
        )

        # Nodes marked RUNNING
        running_calls = [
            c for c in mock_neo4j.update_task_node_status.call_args_list
            if (c.args[1] if len(c.args) > 1 else c.kwargs.get("status")) == "RUNNING"
        ]
        assert len(running_calls) >= 1

        # Nodes marked SUCCESS
        success_calls = [
            c for c in mock_neo4j.update_task_node_status.call_args_list
            if (c.args[1] if len(c.args) > 1 else c.kwargs.get("status")) == "SUCCESS"
        ]
        assert len(success_calls) >= 1

    @pytest.mark.asyncio
    async def test_memory_prompt_assembly_called(
        self, pipeline_service, mock_neo4j, mock_redis, mock_llm,
        mock_scoring, mock_memory, _configure_neo4j,
    ):
        """Verify that memory service assemble-prompt is called for each node."""
        mock_llm.complete = AsyncMock(
            side_effect=[
                '["Memory task", "Context task"]',   # Step 2: decomposition
                "Response with memory context.",       # Step 4: node 1
                "Additional memory response.",         # Step 4: node 2
                "Final with memory.",                  # Step 8: aggregation
            ]
        )

        await pipeline_service.execute(
            conversation_id="conv-007",
            message="Use memory context",
            team_id="team-alpha",
            trace_id="trace-integration-007",
        )

        # Memory assemble_prompt called at least once per sub-task node
        assert mock_memory.assemble_prompt.call_count >= 1
