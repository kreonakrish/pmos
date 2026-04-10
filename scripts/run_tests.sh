#!/usr/bin/env bash
# =============================================================================
# PMOS Test Runner
# Runs: pytest for all Python services, jest for Node services
# Reports: coverage per service, exits non-zero if any suite fails
# Run from pmos/ directory: ./scripts/run_tests.sh
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PMOS_DIR="$(dirname "$SCRIPT_DIR")"
SERVICES_DIR="$PMOS_DIR/services"

# Test result tracking
FAILED_SERVICES=()
PASSED_SERVICES=()

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

info()    { echo "[INFO]  $*"; }
success() { echo "[PASS]  $*"; }
fail()    { echo "[FAIL]  $*" >&2; }
section() { echo ""; echo "=== $* ==="; }

run_python_tests() {
  local service="$1"
  local service_dir="$SERVICES_DIR/$service"

  if [ ! -d "$service_dir" ]; then
    info "  Skipping $service — directory not found"
    return 0
  fi

  section "Python service: $service"

  # Use virtualenv if present, else system python
  local python_bin="python3"
  if [ -f "$service_dir/.venv/bin/python" ]; then
    python_bin="$service_dir/.venv/bin/python"
  elif [ -f "$service_dir/venv/bin/python" ]; then
    python_bin="$service_dir/venv/bin/python"
  fi

  local pytest_bin="${python_bin%python*}pytest"
  if ! command -v "$pytest_bin" &>/dev/null; then
    pytest_bin="$python_bin -m pytest"
  fi

  if $pytest_bin \
    "$service_dir/tests/" \
    --cov="$service_dir/app" \
    --cov-report=term-missing \
    --cov-fail-under=90 \
    -v \
    --tb=short \
    2>&1; then
    success "$service"
    PASSED_SERVICES+=("$service")
  else
    fail "$service"
    FAILED_SERVICES+=("$service")
  fi
}

run_node_tests() {
  local service="$1"
  local service_dir="$SERVICES_DIR/$service"

  if [ ! -d "$service_dir" ]; then
    info "  Skipping $service — directory not found"
    return 0
  fi

  section "Node service: $service"

  if [ ! -f "$service_dir/package.json" ]; then
    fail "$service — package.json not found"
    FAILED_SERVICES+=("$service")
    return 1
  fi

  # Install dependencies if node_modules missing
  if [ ! -d "$service_dir/node_modules" ]; then
    info "  Installing dependencies for $service..."
    (cd "$service_dir" && npm ci --prefer-offline 2>&1)
  fi

  if (cd "$service_dir" && npm test -- --coverage --passWithNoTests 2>&1); then
    success "$service"
    PASSED_SERVICES+=("$service")
  else
    fail "$service"
    FAILED_SERVICES+=("$service")
  fi
}

# ---------------------------------------------------------------------------
# PYTHON SERVICES
# ---------------------------------------------------------------------------

section "Running Python service tests"

PYTHON_SERVICES=(
  "orchestrator"
  "memory"
  "rag"
  "scoring"
  "meta-assembly"
)

for svc in "${PYTHON_SERVICES[@]}"; do
  run_python_tests "$svc" || true  # don't exit on individual failure
done

# ---------------------------------------------------------------------------
# NODE SERVICES
# ---------------------------------------------------------------------------

section "Running Node service tests"

NODE_SERVICES=(
  "gateway"
  "agent-mgmt"
)

for svc in "${NODE_SERVICES[@]}"; do
  run_node_tests "$svc" || true  # don't exit on individual failure
done

# ---------------------------------------------------------------------------
# SUMMARY
# ---------------------------------------------------------------------------

echo ""
echo "============================================================"
echo "  PMOS Test Suite Summary"
echo "============================================================"

if [ ${#PASSED_SERVICES[@]} -gt 0 ]; then
  echo "  PASSED (${#PASSED_SERVICES[@]}):"
  for svc in "${PASSED_SERVICES[@]}"; do
    echo "    ✓ $svc"
  done
fi

if [ ${#FAILED_SERVICES[@]} -gt 0 ]; then
  echo "  FAILED (${#FAILED_SERVICES[@]}):"
  for svc in "${FAILED_SERVICES[@]}"; do
    echo "    ✗ $svc"
  done
  echo ""
  echo "  Some tests failed. See output above for details."
  exit 1
fi

echo ""
echo "  All tests passed!"
exit 0
