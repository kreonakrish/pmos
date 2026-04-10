"""Unit tests for SandboxRunner — subprocess isolation, timeout, memory limits."""
from __future__ import annotations

import platform
import pytest

from app.services.sandbox_runner import SandboxRunner


class _Settings:
    meta_sandbox_timeout_sec = 5
    meta_sandbox_memory_mb = 128


@pytest.fixture
def sandbox():
    return SandboxRunner(_Settings())


@pytest.mark.asyncio
async def test_valid_function_returns_correct_output(sandbox):
    """A well-formed run() function should return the expected result."""
    code = "def run(**kwargs):\n    return kwargs['a'] + kwargs['b']\n"
    result = await sandbox.run_test_case(code, {"a": 3, "b": 7})
    assert result["success"] is True
    assert result["output"] == 10
    assert "duration_ms" in result


@pytest.mark.asyncio
async def test_function_with_string_output(sandbox):
    """run() returning a string should be captured correctly."""
    code = 'def run(**kwargs):\n    return f"hello {kwargs[\'name\']}"\n'
    result = await sandbox.run_test_case(code, {"name": "world"})
    assert result["success"] is True
    assert result["output"] == "hello world"


@pytest.mark.asyncio
async def test_infinite_loop_times_out(sandbox):
    """An infinite loop must be killed by the timeout, not raise an exception in main."""
    sandbox.timeout_sec = 2  # Keep test fast
    code = "def run(**kwargs):\n    while True:\n        pass\n"
    result = await sandbox.run_test_case(code, {})
    assert result["success"] is False
    assert "timed out" in result["error"].lower() or "timeout" in result["error"].lower()
    assert result["duration_ms"] >= 1000  # At least 1s before timeout


@pytest.mark.asyncio
async def test_runtime_error_captured(sandbox):
    """A runtime error in user code should be captured, not crash the host."""
    code = "def run(**kwargs):\n    raise ValueError('intentional error')\n"
    result = await sandbox.run_test_case(code, {})
    assert result["success"] is False
    assert "intentional error" in result["error"]


@pytest.mark.asyncio
async def test_no_run_function_returns_error(sandbox):
    """Code without a run() function should fail gracefully."""
    code = "def helper(x):\n    return x + 1\n"
    result = await sandbox.run_test_case(code, {})
    assert result["success"] is False
    assert "run" in result["error"].lower() or "None" in str(result.get("output"))


@pytest.mark.asyncio
async def test_syntax_error_in_code(sandbox):
    """Syntax errors in generated code should be reported, not crash host."""
    code = "def run(**kwargs)\n    return 42\n"  # missing colon
    result = await sandbox.run_test_case(code, {})
    assert result["success"] is False
    assert result["error"]  # Should have some error message


@pytest.mark.asyncio
@pytest.mark.skipif(platform.system() == "Windows", reason="RLIMIT_AS not available on Windows")
async def test_memory_bomb_caught(sandbox):
    """Allocating excessive memory should be caught by RLIMIT_AS on Linux."""
    sandbox.memory_mb = 64  # Very tight limit
    code = "def run(**kwargs):\n    data = 'x' * (200 * 1024 * 1024)\n    return len(data)\n"
    result = await sandbox.run_test_case(code, {})
    assert result["success"] is False
    assert result["error"]  # Should have an error (MemoryError or killed)
