"""Unit tests for SpecValidatorService — pure AST analysis, no mocks needed."""
from __future__ import annotations

import pytest

from app.services.spec_validator import SpecValidatorService

ALLOWED_IMPORTS = ["json", "re", "math", "datetime", "collections", "itertools", "functools"]


@pytest.fixture
def validator():
    return SpecValidatorService()


# ── Syntax checks ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_valid_python_passes_syntax(validator):
    code = "def run(**kwargs):\n    return kwargs.get('x', 0) + 1\n"
    ok, err = await validator.check_syntax(code)
    assert ok is True
    assert err == ""


@pytest.mark.asyncio
async def test_syntax_error_detected(validator):
    code = "def run(**kwargs)\n    return 42\n"  # missing colon
    ok, err = await validator.check_syntax(code)
    assert ok is False
    assert "SyntaxError" in err


@pytest.mark.asyncio
async def test_empty_code_passes_syntax(validator):
    ok, err = await validator.check_syntax("")
    assert ok is True


# ── Dependency (import whitelist) checks ──────────────────────────────────────


@pytest.mark.asyncio
async def test_allowed_import_passes(validator):
    code = "import json\nimport math\ndef run(**kwargs):\n    return json.dumps(kwargs)\n"
    ok, err = await validator.check_dependencies(code, ALLOWED_IMPORTS)
    assert ok is True
    assert err == ""


@pytest.mark.asyncio
async def test_disallowed_import_os_fails(validator):
    code = "import os\ndef run(**kwargs):\n    return os.getcwd()\n"
    ok, err = await validator.check_dependencies(code, ALLOWED_IMPORTS)
    assert ok is False
    assert "os" in err


@pytest.mark.asyncio
async def test_disallowed_from_import_fails(validator):
    code = "from os.path import join\ndef run(**kwargs):\n    return join('a', 'b')\n"
    ok, err = await validator.check_dependencies(code, ALLOWED_IMPORTS)
    assert ok is False
    assert "os" in err


@pytest.mark.asyncio
async def test_submodule_of_allowed_passes(validator):
    code = "from datetime import timedelta\ndef run(**kwargs):\n    return str(timedelta(days=1))\n"
    ok, err = await validator.check_dependencies(code, ALLOWED_IMPORTS)
    assert ok is True


# ── Safety checks ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_safe_code_passes_safety(validator):
    code = "def run(**kwargs):\n    return sum(kwargs.get('nums', []))\n"
    ok, err = await validator.check_safety(code)
    assert ok is True
    assert err == ""


@pytest.mark.asyncio
async def test_eval_call_fails_safety(validator):
    code = "def run(**kwargs):\n    return eval(kwargs['expr'])\n"
    ok, err = await validator.check_safety(code)
    assert ok is False
    assert "eval" in err.lower()


@pytest.mark.asyncio
async def test_exec_call_fails_safety(validator):
    code = "def run(**kwargs):\n    exec(kwargs['code'])\n"
    ok, err = await validator.check_safety(code)
    assert ok is False
    assert "exec" in err.lower()


@pytest.mark.asyncio
async def test_os_system_call_fails_safety(validator):
    code = "import os\ndef run(**kwargs):\n    os.system('ls')\n"
    ok, err = await validator.check_safety(code)
    assert ok is False
    assert "system" in err.lower() or "os" in err.lower()


@pytest.mark.asyncio
async def test_subprocess_import_fails_safety(validator):
    code = "import subprocess\ndef run(**kwargs):\n    return subprocess.run(['echo', 'hi'])\n"
    ok, err = await validator.check_safety(code)
    assert ok is False
    assert "subprocess" in err.lower()


@pytest.mark.asyncio
async def test_open_with_write_mode_fails_safety(validator):
    code = 'def run(**kwargs):\n    f = open("out.txt", "w")\n    f.write("data")\n    f.close()\n'
    ok, err = await validator.check_safety(code)
    assert ok is False
    assert "open" in err.lower() or "write" in err.lower()


@pytest.mark.asyncio
async def test_dunder_import_fails_safety(validator):
    code = "def run(**kwargs):\n    m = __import__('os')\n    return m.getcwd()\n"
    ok, err = await validator.check_safety(code)
    assert ok is False
    assert "__import__" in err


# ── Composite validate_all ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_all_passes_for_safe_code(validator):
    code = "import json\ndef run(**kwargs):\n    return json.dumps(kwargs)\n"
    result = await validator.validate_all(code, ALLOWED_IMPORTS)
    assert result["passed"] is True
    assert result["validation_score"] == 1.0
    assert result["syntax"]["ok"] is True
    assert result["dependencies"]["ok"] is True
    assert result["safety"]["ok"] is True


@pytest.mark.asyncio
async def test_validate_all_fails_for_unsafe_code(validator):
    code = "import os\ndef run(**kwargs):\n    return eval(kwargs['x'])\n"
    result = await validator.validate_all(code, ALLOWED_IMPORTS)
    assert result["passed"] is False
    assert result["validation_score"] < 1.0
    # dependencies fail (os not in whitelist), safety fails (eval)
    assert result["dependencies"]["ok"] is False
    assert result["safety"]["ok"] is False
