"""Unit tests for GapDetectorService."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from app.services.gap_detector import GapDetectorService


@pytest.fixture
def llm_mock():
    """Create a mock LLM adapter."""
    mock = AsyncMock()
    return mock


@pytest.fixture
def detector(llm_mock):
    return GapDetectorService(llm=llm_mock)


@pytest.mark.asyncio
async def test_missing_tool_detected(detector, llm_mock):
    """When a tool is missing, the LLM should identify gap_type=TOOL."""
    llm_mock.complete_json.return_value = {
        "gap_description": "Missing a JSON schema validation tool",
        "suggested_capability_type": "TOOL",
        "confidence": 0.9,
    }
    result = await detector.detect_gap(
        task_context={"task_id": "t1", "task_type": "validation", "required_tools": ["json_validator"]},
        failed_agents=[1, 2],
        failure_reasons=["No tool available for JSON schema validation"],
        trace_id="test-trace-1",
    )
    assert result["suggested_capability_type"] == "TOOL"
    assert result["trace_id"] == "test-trace-1"
    assert "JSON" in result["gap_description"] or "json" in result["gap_description"].lower()
    llm_mock.complete_json.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_skill_detected(detector, llm_mock):
    """When a reasoning pattern is missing, the LLM should identify gap_type=SKILL."""
    llm_mock.complete_json.return_value = {
        "gap_description": "Missing chain-of-thought reasoning for math proofs",
        "suggested_capability_type": "SKILL",
        "confidence": 0.85,
    }
    result = await detector.detect_gap(
        task_context={"task_id": "t2", "task_type": "reasoning", "required_tools": []},
        failed_agents=[3],
        failure_reasons=["Agent lacks mathematical reasoning patterns"],
        trace_id="test-trace-2",
    )
    assert result["suggested_capability_type"] == "SKILL"
    assert result["confidence"] == 0.85


@pytest.mark.asyncio
async def test_missing_agent_detected(detector, llm_mock):
    """When no agent exists for a domain, gap_type=AGENT."""
    llm_mock.complete_json.return_value = {
        "gap_description": "No agent with legal domain expertise exists",
        "suggested_capability_type": "AGENT",
        "confidence": 0.75,
    }
    result = await detector.detect_gap(
        task_context={"task_id": "t3", "task_type": "legal_analysis", "required_tools": []},
        failed_agents=[],
        failure_reasons=["No agent qualified for legal domain"],
        trace_id="test-trace-3",
    )
    assert result["suggested_capability_type"] == "AGENT"


@pytest.mark.asyncio
async def test_llm_response_parsed_correctly(detector, llm_mock):
    """The parsed result should contain all required fields and clamp confidence."""
    llm_mock.complete_json.return_value = {
        "gap_description": "Need a CSV parser",
        "suggested_capability_type": "TOOL",
        "confidence": 1.5,  # Out of range — should be clamped to 1.0
    }
    result = await detector.detect_gap(
        task_context={"task_id": "t4", "task_type": "data", "required_tools": ["csv_parser"]},
        failed_agents=[10],
        failure_reasons=["Cannot parse CSV files"],
        trace_id="test-trace-4",
    )
    assert result["confidence"] == 1.0
    assert "gap_description" in result
    assert "suggested_capability_type" in result
    assert "trace_id" in result


@pytest.mark.asyncio
async def test_invalid_capability_type_defaults_to_tool(detector, llm_mock):
    """If the LLM returns an unknown capability type, it should default to TOOL."""
    llm_mock.complete_json.return_value = {
        "gap_description": "Something is missing",
        "suggested_capability_type": "WIDGET",
        "confidence": 0.6,
    }
    result = await detector.detect_gap(
        task_context={"task_id": "t5", "task_type": "unknown", "required_tools": []},
        failed_agents=[],
        failure_reasons=["General failure"],
    )
    assert result["suggested_capability_type"] == "TOOL"


@pytest.mark.asyncio
async def test_negative_confidence_clamped_to_zero(detector, llm_mock):
    """Negative confidence should be clamped to 0.0."""
    llm_mock.complete_json.return_value = {
        "gap_description": "Unclear gap",
        "suggested_capability_type": "TOOL",
        "confidence": -0.3,
    }
    result = await detector.detect_gap(
        task_context={"task_id": "t6", "task_type": "unknown", "required_tools": []},
        failed_agents=[],
        failure_reasons=[],
    )
    assert result["confidence"] == 0.0


@pytest.mark.asyncio
async def test_llm_error_propagates(detector, llm_mock):
    """If the LLM call fails, the error should propagate."""
    llm_mock.complete_json.side_effect = RuntimeError("LLM API unavailable")
    with pytest.raises(RuntimeError, match="LLM API unavailable"):
        await detector.detect_gap(
            task_context={"task_id": "t7", "task_type": "any", "required_tools": []},
            failed_agents=[],
            failure_reasons=[],
        )
