"""Unit tests for PromptAssembler — verifies all 4 memory tiers contribute to assembled prompt."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.services.prompt_assembler import PromptAssembler


@pytest.fixture
def mock_short_term():
    svc = AsyncMock()
    svc.read_all = AsyncMock(return_value=[])
    svc.get_session_context = AsyncMock(return_value=[])
    return svc


@pytest.fixture
def mock_long_term():
    svc = AsyncMock()
    svc.semantic_search = AsyncMock(return_value=[])
    return svc


@pytest.fixture
def mock_reasoning():
    svc = AsyncMock()
    svc.search = AsyncMock(return_value=[])
    return svc


@pytest.fixture
def mock_episodic():
    svc = AsyncMock()
    svc.retrieve_similar = AsyncMock(return_value=[])
    return svc


@pytest.fixture
def assembler(mock_short_term, mock_long_term, mock_reasoning, mock_episodic):
    return PromptAssembler(
        short_term=mock_short_term,
        long_term=mock_long_term,
        reasoning=mock_reasoning,
        episodic=mock_episodic,
    )


class TestAllTiersContribute:
    @pytest.mark.asyncio
    async def test_all_four_tiers_in_prompt(
        self, assembler, mock_short_term, mock_long_term, mock_reasoning, mock_episodic
    ):
        """When all 4 tiers return data, the assembled prompt contains all sections."""
        mock_short_term.read_all = AsyncMock(return_value=[
            {"content": "short term context data", "metadata": {}, "created_at": "2026-01-01T00:00:00Z"},
        ])
        mock_long_term.semantic_search = AsyncMock(return_value=[
            {"content": "long term knowledge", "similarity_score": 0.95, "metadata": {}},
        ])
        mock_reasoning.search = AsyncMock(return_value=[
            {"content": "reasoning pattern A", "similarity_score": 0.88, "metadata": {}},
        ])
        mock_episodic.retrieve_similar = AsyncMock(return_value=[
            {"task_description": "past task", "output": "past output", "outcome": "success", "score": 0.9},
        ])

        result = await assembler.assemble_prompt(
            agent_id=1,
            context={"task_type": "analysis", "domain": "finance"},
            tiers=["short_term", "long_term", "reasoning", "episodic"],
        )

        prompt = result["system_prompt"]
        assert "SHORT_TERM" in prompt
        assert "short term context data" in prompt
        assert "LONG_TERM" in prompt
        assert "long term knowledge" in prompt
        assert "Reasoning Patterns" in prompt
        assert "reasoning pattern A" in prompt
        assert "EPISODIC" in prompt
        assert "past task" in prompt

    @pytest.mark.asyncio
    async def test_sources_hit_counts(
        self, assembler, mock_short_term, mock_long_term, mock_reasoning, mock_episodic
    ):
        """sources dict accurately reflects hit counts from each tier."""
        mock_short_term.read_all = AsyncMock(return_value=[
            {"content": "a", "metadata": {}, "created_at": ""},
            {"content": "b", "metadata": {}, "created_at": ""},
        ])
        mock_long_term.semantic_search = AsyncMock(return_value=[
            {"content": "lt1", "similarity_score": 0.9},
        ])
        mock_reasoning.search = AsyncMock(return_value=[
            {"content": "r1", "similarity_score": 0.8},
            {"content": "r2", "similarity_score": 0.7},
            {"content": "r3", "similarity_score": 0.6},
        ])
        mock_episodic.retrieve_similar = AsyncMock(return_value=[
            {"task_description": "ep1", "score": 0.9},
        ])

        result = await assembler.assemble_prompt(
            agent_id=1,
            context={"task_type": "test"},
            tiers=["short_term", "long_term", "reasoning", "episodic"],
        )

        sources = result["sources"]
        assert sources["short_term_hits"] == 2
        assert sources["long_term_hits"] == 1
        assert sources["reasoning_hits"] == 3
        assert sources["episodic_hits"] == 1


class TestTiersFilter:
    @pytest.mark.asyncio
    async def test_only_specified_tiers_queried(
        self, assembler, mock_short_term, mock_long_term, mock_reasoning, mock_episodic
    ):
        """When tiers filter excludes a tier, that tier is not queried."""
        mock_short_term.read_all = AsyncMock(return_value=[
            {"content": "st data", "metadata": {}, "created_at": ""},
        ])

        result = await assembler.assemble_prompt(
            agent_id=1,
            context={"task_type": "test"},
            tiers=["short_term"],  # only short_term
        )

        # short_term was queried
        mock_short_term.read_all.assert_called_once()
        # others were NOT queried
        mock_long_term.semantic_search.assert_not_called()
        mock_reasoning.search.assert_not_called()
        mock_episodic.retrieve_similar.assert_not_called()

        sources = result["sources"]
        assert sources["short_term_hits"] == 1
        assert sources["long_term_hits"] == 0
        assert sources["reasoning_hits"] == 0
        assert sources["episodic_hits"] == 0

    @pytest.mark.asyncio
    async def test_two_tiers_filtered(
        self, assembler, mock_short_term, mock_long_term, mock_reasoning, mock_episodic
    ):
        """Requesting only long_term and episodic skips short_term and reasoning."""
        mock_long_term.semantic_search = AsyncMock(return_value=[
            {"content": "lt data", "similarity_score": 0.8},
        ])
        mock_episodic.retrieve_similar = AsyncMock(return_value=[
            {"task_description": "ep", "score": 0.7},
        ])

        result = await assembler.assemble_prompt(
            agent_id=2,
            context={"task_type": "retrieval", "domain": "legal"},
            tiers=["long_term", "episodic"],
        )

        sources = result["sources"]
        assert sources["short_term_hits"] == 0
        assert sources["long_term_hits"] == 1
        assert sources["reasoning_hits"] == 0
        assert sources["episodic_hits"] == 1


class TestEmptyTierResults:
    @pytest.mark.asyncio
    async def test_empty_results_still_works(self, assembler):
        """When all tiers return empty, the prompt is empty string and hits are 0."""
        result = await assembler.assemble_prompt(
            agent_id=1,
            context={"task_type": "test"},
            tiers=["short_term", "long_term", "reasoning", "episodic"],
        )

        assert result["system_prompt"] == ""
        sources = result["sources"]
        assert sources["short_term_hits"] == 0
        assert sources["long_term_hits"] == 0
        assert sources["reasoning_hits"] == 0
        assert sources["episodic_hits"] == 0

    @pytest.mark.asyncio
    async def test_partial_empty_tiers(
        self, assembler, mock_short_term, mock_long_term
    ):
        """When some tiers return results and others are empty, still assembles correctly."""
        mock_short_term.read_all = AsyncMock(return_value=[
            {"content": "context info", "metadata": {}, "created_at": ""},
        ])
        # long_term, reasoning, episodic return empty (default mocks)

        result = await assembler.assemble_prompt(
            agent_id=1,
            context={"task_type": "test"},
            tiers=["short_term", "long_term", "reasoning", "episodic"],
        )

        assert "context info" in result["system_prompt"]
        assert result["sources"]["short_term_hits"] == 1
        assert result["sources"]["long_term_hits"] == 0


class TestTraceId:
    @pytest.mark.asyncio
    async def test_returns_trace_id(self, assembler):
        result = await assembler.assemble_prompt(
            agent_id=1,
            context={},
            tiers=["short_term"],
            trace_id="trace-abc-123",
        )
        assert result["trace_id"] == "trace-abc-123"

    @pytest.mark.asyncio
    async def test_generates_trace_id_if_none(self, assembler):
        result = await assembler.assemble_prompt(
            agent_id=1,
            context={},
            tiers=["short_term"],
        )
        assert result["trace_id"] is not None
        assert len(result["trace_id"]) == 36  # UUID format


class TestSessionContext:
    @pytest.mark.asyncio
    async def test_session_id_in_context_uses_get_session_context(
        self, assembler, mock_short_term
    ):
        """When context has session_id, uses get_session_context instead of read_all."""
        mock_short_term.get_session_context = AsyncMock(return_value=[
            {"content": "session data", "metadata": {"session_id": "s1"}, "created_at": ""},
        ])

        result = await assembler.assemble_prompt(
            agent_id=1,
            context={"session_id": "s1", "task_type": "test"},
            tiers=["short_term"],
        )

        mock_short_term.get_session_context.assert_called_once_with(1, "s1")
        assert result["sources"]["short_term_hits"] == 1
