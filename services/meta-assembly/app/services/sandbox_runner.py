"""Sandbox runner — executes generated code in an isolated subprocess.

CRITICAL SAFETY: Never eval()/exec() in the main process.
All generated code runs in a subprocess with timeout and memory limits.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from typing import Any

from app.utils.logger import get_logger

logger = get_logger(layer="service")


class SandboxRunner:
    """Run generated Python code in an isolated subprocess with resource limits."""

    def __init__(self, settings: Any) -> None:
        self.timeout_sec: int = settings.meta_sandbox_timeout_sec
        self.memory_mb: int = settings.meta_sandbox_memory_mb

    async def run_test_case(self, code: str, test_input: dict) -> dict[str, Any]:
        """Run generated code in isolated subprocess with timeout and memory limit.

        The code MUST define a function named ``run(**kwargs)`` which will be
        called with ``test_input`` as keyword arguments.

        Returns a dict with keys: success, output|error, duration_ms.
        """
        code_path: str | None = None
        input_path: str | None = None

        try:
            # Write code and input to temp files
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False
            ) as code_file:
                code_file.write(code)
                code_path = code_file.name

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            ) as input_file:
                json.dump(test_input, input_file)
                input_path = input_file.name

            # Build wrapper script that applies resource limits and runs the code
            memory_limit = self.memory_mb
            wrapper = f"""
import sys, json

# Apply memory limit (Linux only — gracefully ignored on Windows)
try:
    import resource
    limit = {memory_limit} * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
except (ImportError, ValueError, OSError):
    pass

# Load and execute generated code in a restricted namespace
with open({code_path!r}) as f:
    code_text = f.read()
namespace = {{}}
exec(compile(code_text, "<sandbox>", "exec"), namespace)

# Load test input and call the run() function
with open({input_path!r}) as f:
    test_input = json.load(f)

run_fn = namespace.get("run")
if run_fn is None:
    print(json.dumps({{"success": False, "error": "No run() function defined"}}))
    sys.exit(0)

try:
    result = run_fn(**test_input)
    print(json.dumps({{"success": True, "output": result}}))
except Exception as exc:
    print(json.dumps({{"success": False, "error": str(exc)}}))
"""

            start = time.monotonic()
            proc = subprocess.run(
                [sys.executable, "-c", wrapper],
                capture_output=True,
                text=True,
                timeout=self.timeout_sec,
            )
            duration_ms = int((time.monotonic() - start) * 1000)

            if proc.returncode == 0 and proc.stdout.strip():
                try:
                    output = json.loads(proc.stdout.strip())
                    output["duration_ms"] = duration_ms
                    return output
                except json.JSONDecodeError:
                    return {
                        "success": False,
                        "error": f"Non-JSON stdout: {proc.stdout[:300]}",
                        "duration_ms": duration_ms,
                    }

            return {
                "success": False,
                "error": proc.stderr[:500] if proc.stderr else "Process exited with no output",
                "duration_ms": duration_ms,
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": "Execution timed out",
                "duration_ms": self.timeout_sec * 1000,
            }
        except Exception as exc:
            logger.error("sandbox_run_error", error=str(exc), layer="service")
            return {"success": False, "error": str(exc), "duration_ms": 0}
        finally:
            for path in [code_path, input_path]:
                if path:
                    try:
                        os.unlink(path)
                    except OSError:
                        pass
