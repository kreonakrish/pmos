"""
PMOS Validation Suite -- Shared helpers.

Provides an async HTTP client factory, structured test reporting,
shared-state helpers, and common assertion utilities.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

import httpx

from config import REQUEST_TIMEOUT, state

# ---------------------------------------------------------------------------
# Persistence path for cross-suite state and final report
# ---------------------------------------------------------------------------
_STATE_FILE = Path(__file__).parent / ".validation_state.json"
_REPORT_FILE = Path(__file__).parent / ".validation_report.json"


# ---------------------------------------------------------------------------
# Async HTTP client
# ---------------------------------------------------------------------------

def async_client(timeout: float | None = None) -> httpx.AsyncClient:
    """Return an ``httpx.AsyncClient`` pre-configured with the suite timeout."""
    t = timeout if timeout is not None else REQUEST_TIMEOUT
    return httpx.AsyncClient(timeout=httpx.Timeout(t))


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

class ValidationReporter:
    """Tracks pass / fail / skip counts and prints a formatted summary."""

    _instances: list["ValidationReporter"] = []

    def __init__(self, suite_name: str) -> None:
        self.suite_name = suite_name
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.results: list[dict] = []
        ValidationReporter._instances.append(self)

    # -- individual result recording --

    def record(self, status: str, name: str, description: str, error: str | None = None) -> None:
        self.results.append({
            "status": status,
            "name": name,
            "description": description,
            "error": error,
        })
        if status == "PASS":
            self.passed += 1
        elif status == "FAIL":
            self.failed += 1
        else:
            self.skipped += 1
        report(status, name, description, error)

    # -- suite-level summary --

    def summary(self) -> None:
        total = self.passed + self.failed + self.skipped
        print(f"\n--- {self.suite_name} Summary ---")
        print(f"  Total: {total}  |  PASS: {self.passed}  |  FAIL: {self.failed}  |  SKIP: {self.skipped}")
        if self.failed:
            print("  Status: FAILED")
        elif self.skipped and not self.passed:
            print("  Status: ALL SKIPPED")
        else:
            print("  Status: OK")
        print()

        # Persist counts for final report
        self._persist()

    def _persist(self) -> None:
        """Append this suite's counts to the report file."""
        data: list[dict] = []
        if _REPORT_FILE.exists():
            try:
                data = json.loads(_REPORT_FILE.read_text())
            except Exception:
                data = []
        data.append({
            "suite": self.suite_name,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
        })
        _REPORT_FILE.write_text(json.dumps(data, indent=2))

    @staticmethod
    def load_and_print_final() -> None:
        """Print the aggregate report from all suite runs."""
        if not _REPORT_FILE.exists():
            print("No validation report found.")
            return
        try:
            data = json.loads(_REPORT_FILE.read_text())
        except Exception:
            print("Corrupt validation report file.")
            return

        total_p = sum(d.get("passed", 0) for d in data)
        total_f = sum(d.get("failed", 0) for d in data)
        total_s = sum(d.get("skipped", 0) for d in data)
        total = total_p + total_f + total_s

        print("=" * 60)
        print("          PMOS VALIDATION -- FINAL REPORT")
        print("=" * 60)
        for entry in data:
            s = entry.get("suite", "?")
            p, f, sk = entry.get("passed", 0), entry.get("failed", 0), entry.get("skipped", 0)
            tag = "OK" if f == 0 else "FAILED"
            print(f"  {s:40s}  P={p}  F={f}  S={sk}  [{tag}]")
        print("-" * 60)
        print(f"  {'TOTALS':40s}  P={total_p}  F={total_f}  S={total_s}  Tests={total}")
        overall = "PASS" if total_f == 0 else "FAIL"
        print(f"\n  Overall: {overall}")
        print("=" * 60)

        # Clean up
        try:
            _REPORT_FILE.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

def report(status: str, name: str, description: str, error: str | None = None) -> None:
    """Print a single ``[PASS]``, ``[FAIL]``, or ``[SKIP]`` line."""
    tag = f"[{status:4s}]"
    line = f"  {tag}  {name}: {description}"
    if error:
        line += f"  -- {error}"
    print(line)


def assert_status(response: httpx.Response, expected: int, test_name: str) -> bool:
    """Check HTTP status. Returns True on match, False otherwise."""
    if response.status_code == expected:
        return True
    report(
        "FAIL",
        test_name,
        f"Expected HTTP {expected}, got {response.status_code}",
        response.text[:200],
    )
    return False


def store(key: str, value: Any) -> None:
    """Store a value in cross-suite shared state (memory + disk)."""
    state[key] = value
    _save_state()


def get(key: str, default: Any = None) -> Any:
    """Retrieve a value from shared state, loading from disk if needed."""
    if key not in state:
        _load_state()
    return state.get(key, default)


def _save_state() -> None:
    try:
        _STATE_FILE.write_text(json.dumps(state, indent=2, default=str))
    except Exception:
        pass


def _load_state() -> None:
    if _STATE_FILE.exists():
        try:
            state.update(json.loads(_STATE_FILE.read_text()))
        except Exception:
            pass
