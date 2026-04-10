"""Unit tests for living graph expansion (ARCHITECTURE.md living graph invariant)."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, call

from app.services.graph_manager import GraphManager


@pytest.mark.asyncio
async def test_expand_graph_creates_nodes_for_each_subtask(mock_neo4j):
    """LLM response with 2 sub-questions → 2 new TaskNodes created before returning."""
    graph_mgr = GraphManager(neo4j=mock_neo4j)

    llm_response = "1. What is the database schema?\n2. How do we optimise the query?"
    new_ids = await graph_mgr.expand_graph_from_response(
        graph_id="graph-001",
        parent_node_id="node-root",
        llm_response=llm_response,
        iteration=1,
        parent_depth=0,
        trace_id="trace-001",
    )

    assert len(new_ids) == 2
    # Verify create_task_node was called exactly twice
    assert mock_neo4j.create_task_node.call_count == 2


@pytest.mark.asyncio
async def test_expand_graph_links_spawned_by_relationship(mock_neo4j):
    """New nodes are linked to parent via SPAWNED_BY in Neo4j."""
    graph_mgr = GraphManager(neo4j=mock_neo4j)

    llm_response = "- Retrieve customer data\n- Validate business rules"
    await graph_mgr.expand_graph_from_response(
        graph_id="graph-001",
        parent_node_id="parent-node-42",
        llm_response=llm_response,
        iteration=1,
        trace_id="trace-002",
    )

    # link_spawned_by must be called for each new node with parent_node_id
    for c in mock_neo4j.link_spawned_by.call_args_list:
        assert c.kwargs.get("parent_id") == "parent-node-42" or c.args[1] == "parent-node-42"


@pytest.mark.asyncio
async def test_expand_graph_iteration_counter_propagated(mock_neo4j):
    """Iteration value is passed to each new TaskNode."""
    graph_mgr = GraphManager(neo4j=mock_neo4j)

    llm_response = "1. Step A\n2. Step B\n3. Step C"
    await graph_mgr.expand_graph_from_response(
        graph_id="graph-002",
        parent_node_id="node-parent",
        llm_response=llm_response,
        iteration=3,
        trace_id="trace-003",
    )

    for call_args in mock_neo4j.create_task_node.call_args_list:
        # iteration is a keyword arg
        assert call_args.kwargs.get("iteration") == 3


@pytest.mark.asyncio
async def test_expand_graph_no_subtasks_returns_empty(mock_neo4j):
    """Response with no detectable sub-tasks returns empty list without Neo4j calls."""
    graph_mgr = GraphManager(neo4j=mock_neo4j)

    llm_response = "The answer is 42."
    new_ids = await graph_mgr.expand_graph_from_response(
        graph_id="graph-003",
        parent_node_id="node-leaf",
        llm_response=llm_response,
        iteration=0,
        trace_id="trace-004",
    )

    assert new_ids == []
    mock_neo4j.create_task_node.assert_not_called()


@pytest.mark.asyncio
async def test_expand_graph_json_array_response(mock_neo4j):
    """Structured JSON array response creates the right number of nodes."""
    graph_mgr = GraphManager(neo4j=mock_neo4j)

    llm_response = '["Fetch user profile", "Compute recommendations", "Send notification"]'
    new_ids = await graph_mgr.expand_graph_from_response(
        graph_id="graph-004",
        parent_node_id="node-root",
        llm_response=llm_response,
        iteration=2,
        trace_id="trace-005",
    )

    assert len(new_ids) == 3
    assert mock_neo4j.create_task_node.call_count == 3
