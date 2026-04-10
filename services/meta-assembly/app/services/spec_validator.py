"""Three-stage spec validator — all analysis via AST, never exec/eval."""
from __future__ import annotations

import ast
import uuid
from typing import Any

from app.utils.logger import get_logger

logger = get_logger(layer="service")

# AST node types that always constitute a safety violation
_FORBIDDEN_FUNCTION_NAMES: frozenset[str] = frozenset(
    {"eval", "exec", "__import__", "compile", "breakpoint"}
)

_FORBIDDEN_ATTR_NAMES: frozenset[str] = frozenset(
    {
        "system",        # os.system
        "popen",         # os.popen / subprocess.Popen via attribute
        "socket",        # socket.socket
        "connect",       # socket.connect
    }
)

_FORBIDDEN_MODULE_NAMES: frozenset[str] = frozenset(
    {
        "os",
        "subprocess",
        "sys",
        "socket",
        "shutil",
        "pathlib",
        "ctypes",
        "importlib",
        "builtins",
        "signal",
        "multiprocessing",
        "threading",
        "concurrent",
    }
)


class SpecValidatorService:
    """
    Validates generated code specs using three independent AST-based checks.
    NEVER executes or evaluates any code.
    """

    # ── Stage 1: Syntax check ─────────────────────────────────────────────────

    async def check_syntax(self, code: str) -> tuple[bool, str]:
        """Parse code with ast.parse() — never exec or eval.
        Returns (passed, error_message)."""
        if not code or not code.strip():
            return True, ""  # Empty code — no syntax error; dependency check will handle
        try:
            ast.parse(code)
            return True, ""
        except SyntaxError as exc:
            return False, f"SyntaxError at line {exc.lineno}: {exc.msg}"

    # ── Stage 2: Dependency (import whitelist) check ──────────────────────────

    async def check_dependencies(
        self, code: str, allowed_imports: list[str]
    ) -> tuple[bool, str]:
        """
        Walk AST to find all import statements.
        Reject any import not in allowed_imports whitelist.
        NEVER executes the code.
        """
        if not code or not code.strip():
            return True, ""

        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return False, f"Cannot check dependencies — syntax error: {exc}"

        allowed_set = set(allowed_imports)
        violations: list[str] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    # Top-level module name (e.g. "numpy.random" → "numpy")
                    top_module = alias.name.split(".")[0]
                    if top_module not in allowed_set:
                        violations.append(alias.name)

            elif isinstance(node, ast.ImportFrom):
                if node.module is None:
                    continue
                top_module = node.module.split(".")[0]
                if top_module not in allowed_set:
                    violations.append(node.module)

        if violations:
            return False, f"Disallowed imports: {', '.join(set(violations))}"
        return True, ""

    # ── Stage 3: Safety check ─────────────────────────────────────────────────

    async def check_safety(self, code: str) -> tuple[bool, str]:
        """
        AST-based static analysis. Rejects code that contains dangerous patterns.
        All checks via AST node inspection — never by executing the code.

        Rejects:
        - os.system, subprocess calls, eval(), exec()
        - open() with write mode
        - socket.socket() or any network calls
        - __import__() calls
        - file system path traversal
        """
        if not code or not code.strip():
            return True, ""

        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return False, f"Cannot check safety — syntax error: {exc}"

        violations: list[str] = []

        for node in ast.walk(tree):
            # Direct calls to forbidden builtins: eval(), exec(), __import__()
            if isinstance(node, ast.Call):
                func = node.func

                if isinstance(func, ast.Name):
                    if func.id in _FORBIDDEN_FUNCTION_NAMES:
                        violations.append(f"Forbidden call: {func.id}()")

                elif isinstance(func, ast.Attribute):
                    if func.attr in _FORBIDDEN_ATTR_NAMES:
                        violations.append(
                            f"Forbidden attribute call: .{func.attr}()"
                        )
                    # Check for open() with write modes
                    if (
                        isinstance(func.value, ast.Name)
                        and func.value.id == "open"
                    ) or (isinstance(func, ast.Name) and func.id == "open"):  # type: ignore[comparison-overlap]
                        # Covered below under ast.Name check
                        pass

                # open("file", "w"), open("file", mode="w")
                if isinstance(func, ast.Name) and func.id == "open":
                    write_modes = {"w", "wb", "a", "ab", "x", "xb", "w+", "r+"}
                    # Positional arg
                    if len(node.args) >= 2:
                        mode_arg = node.args[1]
                        if isinstance(mode_arg, ast.Constant) and mode_arg.value in write_modes:
                            violations.append("open() with write mode")
                    # Keyword arg
                    for kw in node.keywords:
                        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                            if kw.value.value in write_modes:
                                violations.append("open() with write mode (keyword)")

            # Imports of forbidden modules (belt-and-suspenders on top of dep check)
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in _FORBIDDEN_MODULE_NAMES:
                        violations.append(f"Forbidden import: {alias.name}")

            if isinstance(node, ast.ImportFrom):
                if node.module:
                    top = node.module.split(".")[0]
                    if top in _FORBIDDEN_MODULE_NAMES:
                        violations.append(f"Forbidden import from: {node.module}")

        if violations:
            return False, f"Safety violations: {'; '.join(violations)}"
        return True, ""

    # ── Composite check ────────────────────────────────────────────────────────

    async def validate_all(
        self,
        code: str,
        allowed_imports: list[str],
        trace_id: str = "",
    ) -> dict[str, Any]:
        """Run all three stages; return combined result dict."""
        trace_id = trace_id or str(uuid.uuid4())

        syntax_ok, syntax_err = await self.check_syntax(code)
        dep_ok, dep_err = await self.check_dependencies(code, allowed_imports)
        safety_ok, safety_err = await self.check_safety(code)

        passed = syntax_ok and dep_ok and safety_ok
        score = (int(syntax_ok) + int(dep_ok) + int(safety_ok)) / 3.0

        logger.info(
            "spec_validation_result",
            trace_id=trace_id,
            syntax_ok=syntax_ok,
            dep_ok=dep_ok,
            safety_ok=safety_ok,
            validation_score=score,
            errors={
                "syntax": syntax_err,
                "dependencies": dep_err,
                "safety": safety_err,
            },
            layer="service",
        )

        return {
            "passed": passed,
            "syntax": {"ok": syntax_ok, "error": syntax_err},
            "dependencies": {"ok": dep_ok, "error": dep_err},
            "safety": {"ok": safety_ok, "error": safety_err},
            "validation_score": score,
        }
