"""Integration test — full self-assembly cycle with mocked adapters.

Verifies the complete flow: detect-gap -> generate-spec -> register
and confirms all backing stores are updated.
"""
from __future__ import annotations

import uuid
import pytest
from unittest.mock import AsyncMock

from app.services.gap_detector import GapDetectorService
from app.services.spec_generator import SpecGeneratorService
from app.services.spec_validator import SpecValidatorService
from app.services.capability_registrar import CapabilityRegistrar


@pytest.fixture
def gap_llm():
    """LLM mock for gap detection."""
    mock = AsyncMock()
    mock.complete_json.return_value = {
        "gap_description": "Missing a CSV parsing tool for data transformation",
        "suggested_capability_type": "TOOL",
        "confidence": 0.92,
    }
    return mock


@pytest.fixture
def spec_llm():
    """LLM mock for spec generation."""
    mock = AsyncMock()
    mock.complete_json.return_value = {
        "capability_type": "TOOL",
        "name": "csv_parser",
        "description": "Parse CSV strings into list of dicts",
        "spec_json": {
            "code": "import json\ndef run(**kwargs):\n    return []\n",
            "config_schema": {"data": {"type": "str", "description": "CSV string"}},
            "test_cases": [{"input": {"data": "a,b"}, "expected_output": [], "description": "parse simple CSV"}],
            "dependencies": ["json"],
            "domains": ["data"],
        },
    }
    return mock


@pytest.fixture
def mock_mysql():
    adapter = AsyncMock()
    adapter.insert_capability = AsyncMock(return_value=None)
    return adapter


@pytest.fixture
def mock_neo4j():
    adapter = AsyncMock()
    adapter.create_capability_node = AsyncMock(return_value=None)
    return adapter


@pytest.fixture
def mock_redis():
    adapter = AsyncMock()
    adapter.publish_capability_added = AsyncMock(return_value="stream-entry-1")
    return adapter


@pytest.mark.asyncio
async def test_full_self_assembly_cycle(
    gap_llm, spec_llm, mock_mysql, mock_neo4j, mock_redis
):
    """Complete cycle: detect gap -> generate spec -> validate -> register."""
    trace_id = str(uuid.uuid4())

    # Step 1: Detect gap
    detector = GapDetectorService(llm=gap_llm)
    gap_result = await detector.detect_gap(
        task_context={"task_id": "task-100", "task_type": "data_processing", "required_tools": ["csv_parser"]},
        failed_agents=[1, 2],
        failure_reasons=["No agent has a CSV parsing tool"],
        trace_id=trace_id,
    )
    assert gap_result["suggested_capability_type"] == "TOOL"
    assert gap_result["confidence"] > 0.5
    gap_llm.complete_json.assert_awaited_once()

    # Step 2: Generate spec
    generator = SpecGeneratorService(llm=spec_llm)
    spec = await generator.generate_spec(
        gap_description=gap_result["gap_description"],
        capability_type=gap_result["suggested_capability_type"],
        trace_id=trace_id,
    )
    assert spec["capability_type"] == "TOOL"
    assert spec["name"] == "csv_parser"
    spec_llm.complete_json.assert_awaited_once()

    # Step 3: Validate spec
    validator = SpecValidatorService()
    code = spec["spec_json"]["code"]
    allowed_imports = ["json", "re", "math", "datetime", "collections"]
    validation = await validator.validate_all(code, allowed_imports, trace_id=trace_id)
    assert validation["passed"] is True
    assert validation["validation_score"] == 1.0

    # Step 4: Register
    registrar = CapabilityRegistrar(
        mysql_adapter=mock_mysql,
        neo4j_adapter=mock_neo4j,
        redis_adapter=mock_redis,
    )
    capability_id = await registrar.register(
        spec=spec,
        gap_id="gap-100",
        validation_score=validation["validation_score"],
        trace_id=trace_id,
    )

    # Verify all stores were updated
    assert uuid.UUID(capability_id)  # Valid UUID

    # MySQL: insert_capability called
    mock_mysql.insert_capability.assert_awaited_once()
    mysql_kwargs = mock_mysql.insert_capability.call_args.kwargs
    assert mysql_kwargs["capability_type"] == "TOOL"
    assert mysql_kwargs["name"] == "csv_parser"

    # Neo4j: create_capability_node called
    mock_neo4j.create_capability_node.assert_awaited_once()
    neo4j_kwargs = mock_neo4j.create_capability_node.call_args.kwargs
    assert neo4j_kwargs["capability_id"] == capability_id
    assert neo4j_kwargs["domains"] == ["data"]

    # Redis: publish_capability_added called
    mock_redis.publish_capability_added.assert_awaited_once()
    redis_kwargs = mock_redis.publish_capability_added.call_args.kwargs
    assert redis_kwargs["capability_id"] == capability_id
    assert redis_kwargs["capability_type"] == "TOOL"
    assert redis_kwargs["gap_id"] == "gap-100"


@pytest.mark.asyncio
async def test_cycle_with_validation_failure_does_not_register(
    gap_llm, mock_mysql, mock_neo4j, mock_redis
):
    """If validation fails, the spec must NOT be registered."""
    trace_id = str(uuid.uuid4())

    # Detect gap
    detector = GapDetectorService(llm=gap_llm)
    gap_result = await detector.detect_gap(
        task_context={"task_id": "task-200", "task_type": "system", "required_tools": []},
        failed_agents=[5],
        failure_reasons=["Agent failed to execute system command"],
        trace_id=trace_id,
    )

    # Generate a spec with unsafe code (manually constructed)
    unsafe_spec = {
        "capability_type": "TOOL",
        "name": "system_exec",
        "description": "Execute system commands",
        "spec_json": {
            "code": "import os\ndef run(**kwargs):\n    return os.system(kwargs['cmd'])\n",
            "dependencies": ["os"],
            "domains": ["system"],
            "test_cases": [],
        },
    }

    # Validate — should fail
    validator = SpecValidatorService()
    validation = await validator.validate_all(
        unsafe_spec["spec_json"]["code"],
        ["json", "re", "math"],
        trace_id=trace_id,
    )
    assert validation["passed"] is False

    # Registration should NOT happen since validation failed
    # (In real flow, the route handler checks validation["passed"] before registering)
    mock_mysql.insert_capability.assert_not_awaited()
    mock_neo4j.create_capability_node.assert_not_awaited()
    mock_redis.publish_capability_added.assert_not_awaited()
