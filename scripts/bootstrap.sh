#!/usr/bin/env bash
# =============================================================================
# PMOS Bootstrap Script
# Creates MySQL schema, seeds Neo4j constraints, initializes Redis streams
# Run from the pmos/ directory: ./scripts/bootstrap.sh
# Prerequisites: MySQL running on host, Redis running (local or Docker)
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PMOS_DIR="$(dirname "$SCRIPT_DIR")"

# Load environment variables
if [ -f "$PMOS_DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$PMOS_DIR/.env"
  set +a
else
  echo "ERROR: $PMOS_DIR/.env not found. Copy .env.example to .env and fill in values."
  exit 1
fi

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

info()    { echo "[INFO]  $*"; }
success() { echo "[OK]    $*"; }
error()   { echo "[ERROR] $*" >&2; }

wait_for_port() {
  local host="$1" port="$2" name="$3" timeout="${4:-30}"
  info "Waiting for $name ($host:$port)..."
  local elapsed=0
  until nc -z "$host" "$port" 2>/dev/null; do
    sleep 1
    elapsed=$((elapsed + 1))
    if [ "$elapsed" -ge "$timeout" ]; then
      error "$name did not become available within ${timeout}s"
      exit 1
    fi
  done
  success "$name is available"
}

# ---------------------------------------------------------------------------
# STEP 1: Wait for backing services
# ---------------------------------------------------------------------------

info "=== Checking backing service availability ==="

MYSQL_HOST_ACTUAL="${MYSQL_HOST:-localhost}"
MYSQL_PORT_ACTUAL="${MYSQL_PORT:-3306}"
REDIS_HOST=$(echo "${REDIS_URL:-redis://localhost:6379}" | sed 's|redis://||' | cut -d: -f1)
REDIS_PORT=$(echo "${REDIS_URL:-redis://localhost:6379}" | sed 's|redis://||' | cut -d: -f2)
REDIS_PORT="${REDIS_PORT:-6379}"

# For Docker internal hostname, fall back to localhost for bootstrap
if [ "$MYSQL_HOST_ACTUAL" = "host-gateway" ]; then
  MYSQL_HOST_ACTUAL="localhost"
fi
if [ "$REDIS_HOST" = "redis" ]; then
  REDIS_HOST="localhost"
fi

wait_for_port "$MYSQL_HOST_ACTUAL" "$MYSQL_PORT_ACTUAL" "MySQL" 60
wait_for_port "$REDIS_HOST" "$REDIS_PORT" "Redis" 30

# ---------------------------------------------------------------------------
# STEP 2: Create MySQL schema
# ---------------------------------------------------------------------------

info "=== Creating MySQL schema ==="

MYSQL_CMD="mysql -h $MYSQL_HOST_ACTUAL -P ${MYSQL_PORT_ACTUAL} -u ${MYSQL_USER:-root}"
if [ -n "${MYSQL_PASSWORD:-}" ]; then
  MYSQL_CMD="$MYSQL_CMD -p${MYSQL_PASSWORD}"
fi

$MYSQL_CMD < "$PMOS_DIR/infra/mysql/schema.sql"
success "MySQL schema created (database: ${MYSQL_DB:-pmos})"

# Auth / RBAC schema (idempotent)
if [ -f "$PMOS_DIR/infra/mysql/auth_schema.sql" ]; then
  $MYSQL_CMD "${MYSQL_DB:-pmos}" < "$PMOS_DIR/infra/mysql/auth_schema.sql"
  success "MySQL auth/RBAC schema applied"
fi

# ---------------------------------------------------------------------------
# STEP 3: Seed Neo4j constraints & indexes
# ---------------------------------------------------------------------------

info "=== Seeding Neo4j constraints ==="

NEO4J_URI_ACTUAL="${NEO4J_URI:-}"
if [ -z "$NEO4J_URI_ACTUAL" ]; then
  error "NEO4J_URI is not set in .env. Set it before bootstrapping (e.g. neo4j+s://<host> or bolt://<host>:7687)."
  exit 1
fi
NEO4J_USER_ACTUAL="${NEO4J_USER:-neo4j}"
NEO4J_PASSWORD_ACTUAL="${NEO4J_PASSWORD:-}"

if [ -z "$NEO4J_PASSWORD_ACTUAL" ]; then
  error "NEO4J_PASSWORD is not set. Skipping Neo4j seeding."
  info "Run manually: cypher-shell -a \"$NEO4J_URI_ACTUAL\" -u \"$NEO4J_USER_ACTUAL\" -p \"<password>\" -f infra/neo4j/constraints.cypher"
else
  if command -v cypher-shell &>/dev/null; then
    cypher-shell \
      -a "$NEO4J_URI_ACTUAL" \
      -u "$NEO4J_USER_ACTUAL" \
      -p "$NEO4J_PASSWORD_ACTUAL" \
      -f "$PMOS_DIR/infra/neo4j/constraints.cypher" \
      --format plain
    success "Neo4j constraints and indexes created"
  else
    info "cypher-shell not found. Attempting via Python neo4j driver..."
    python3 - <<PYEOF
import os, sys
try:
    from neo4j import GraphDatabase
except ImportError:
    print("[WARN] neo4j python driver not installed. Install with: pip install neo4j")
    sys.exit(0)

uri = "$NEO4J_URI_ACTUAL"
user = "$NEO4J_USER_ACTUAL"
password = "$NEO4J_PASSWORD_ACTUAL"
cypher_file = "$PMOS_DIR/infra/neo4j/constraints.cypher"

driver = GraphDatabase.driver(uri, auth=(user, password))
with open(cypher_file) as f:
    statements = [s.strip() for s in f.read().split(';') if s.strip() and not s.strip().startswith('//')]

with driver.session() as session:
    for stmt in statements:
        if stmt:
            try:
                session.run(stmt)
            except Exception as e:
                print(f"[WARN] {e}: {stmt[:80]}")

driver.close()
print("[OK]   Neo4j constraints applied via Python driver")
PYEOF
  fi
fi

# ---------------------------------------------------------------------------
# STEP 4: Initialize Redis consumer groups
# ---------------------------------------------------------------------------

info "=== Initializing Redis stream consumer groups ==="

REDIS_CLI="redis-cli -h $REDIS_HOST -p $REDIS_PORT"

create_group() {
  local stream="$1" group="$2"
  $REDIS_CLI XGROUP CREATE "$stream" "$group" '$' MKSTREAM 2>/dev/null || \
    $REDIS_CLI XGROUP CREATECONSUMER "$stream" "$group" "bootstrap" 2>/dev/null || true
  info "  Stream: $stream | Group: $group"
}

create_group "orchestrator:tasks"      "orchestrator-workers"
create_group "memory:writes"           "memory-service"
create_group "scoring:feedback"        "rl-engine"
create_group "events:telemetry"        "telemetry-collector"
create_group "events:tool_health"      "orchestrator-health-listener"
create_group "events:capability_added" "orchestrator-capability-listener"
create_group "events:capability_added" "agent-mgmt-capability-listener"
create_group "events:documents"        "rag-ingestor"

success "Redis streams and consumer groups initialized"

# ---------------------------------------------------------------------------
# DONE
# ---------------------------------------------------------------------------

echo ""
echo "============================================================"
echo "  PMOS Bootstrap Complete!"
echo "  MySQL:   ${MYSQL_DB:-pmos} schema ready"
echo "  Neo4j:   constraints applied (or skipped — check above)"
echo "  Redis:   8 streams with consumer groups ready"
echo ""
echo "  Next steps:"
echo "    docker compose up -d"
echo "    # Wait for services to become healthy"
echo "    ./scripts/run_tests.sh"
echo "============================================================"
