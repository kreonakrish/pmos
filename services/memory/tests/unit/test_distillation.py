"""Unit tests for DistillationService."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.distillation import DistillationService


@pytest.fixture
def short_term_svc():
    svc = AsyncMock()
    svc.get_access_counts = AsyncMock(return_value={})
    svc.get_entry = AsyncMock(return_value=None)
    svc.delete = AsyncMock()
    return svc


@pytest.fixture
def long_term_svc():
    svc = AsyncMock()
    svc.store = AsyncMock(return_value="lt-mem-id")
    return svc


@pytest.fixture
def mysql_adapter(mock_mysql_adapter):
    return mock_mysql_adapter


@pytest.fixture
def redis_adapter(mock_redis_adapter):
    return mock_redis_adapter


@pytest.fixture
def distillation(short_term_svc, long_term_svc, mysql_adapter, redis_adapter):
    svc = DistillationService(
        short_term=short_term_svc,
        long_term=long_term_svc,
        mysql=mysql_adapter,
        redis=redis_adapter,
    )
    svc._threshold = 3
    return svc


class TestDistillationPromotion:
    @pytest.mark.asyncio
    async def test_entry_above_threshold_promoted_to_long_term(
        self, distillation, short_term_svc, long_term_svc
    ):
        short_term_svc.get_access_counts = AsyncMock(return_value={"key-1": 5})
        short_term_svc.get_entry = AsyncMock(return_value={
            "content": "important pattern",
            "metadata": {"session_id": "s1"},
            "access_count": 5,
        })

        result = await distillation.run_once(agent_ids=[1])

        long_term_svc.store.assert_called_once()
        call_args = long_term_svc.store.call_args
        assert call_args[0][0] == 1  # agent_id
        assert call_args[0][1] == "important pattern"  # content
        assert result["promoted"] == 1

    @pytest.mark.asyncio
    async def test_entry_below_threshold_stays_in_short_term(
        self, distillation, short_term_svc, long_term_svc
    ):
        short_term_svc.get_access_counts = AsyncMock(return_value={"key-1": 2})

        result = await distillation.run_once(agent_ids=[1])

        long_term_svc.store.assert_not_called()
        assert result["promoted"] == 0
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_promoted_entry_deleted_from_short_term(
        self, distillation, short_term_svc, long_term_svc
    ):
        short_term_svc.get_access_counts = AsyncMock(return_value={"key-1": 10})
        short_term_svc.get_entry = AsyncMock(return_value={
            "content": "to promote",
            "metadata": {},
            "access_count": 10,
        })

        await distillation.run_once(agent_ids=[1])

        short_term_svc.delete.assert_called_once_with(1, "key-1")

    @pytest.mark.asyncio
    async def test_exactly_at_threshold_is_promoted(
        self, distillation, short_term_svc, long_term_svc
    ):
        threshold = distillation._threshold  # 3
        short_term_svc.get_access_counts = AsyncMock(return_value={"key-1": threshold})
        short_term_svc.get_entry = AsyncMock(return_value={
            "content": "borderline",
            "metadata": {},
            "access_count": threshold,
        })

        result = await distillation.run_once(agent_ids=[1])

        assert result["promoted"] == 1

    @pytest.mark.asyncio
    async def test_multiple_agents_processed(
        self, distillation, short_term_svc, long_term_svc
    ):
        # Agent 1 has one promotable entry, agent 2 has none
        async def get_counts(agent_id):
            if agent_id == 1:
                return {"k1": 5}
            return {"k2": 1}

        short_term_svc.get_access_counts = AsyncMock(side_effect=get_counts)
        short_term_svc.get_entry = AsyncMock(return_value={
            "content": "agent1 pattern",
            "metadata": {},
            "access_count": 5,
        })

        result = await distillation.run_once(agent_ids=[1, 2])

        assert result["promoted"] == 1
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_metadata_enriched_on_promotion(
        self, distillation, short_term_svc, long_term_svc
    ):
        short_term_svc.get_access_counts = AsyncMock(return_value={"key-1": 4})
        short_term_svc.get_entry = AsyncMock(return_value={
            "content": "pattern",
            "metadata": {"original_key": "val"},
            "access_count": 4,
        })

        await distillation.run_once(agent_ids=[1])

        call_meta = long_term_svc.store.call_args[0][2]
        assert call_meta["distilled_from"] == "short_term"
        assert call_meta["original_access_count"] == 4
