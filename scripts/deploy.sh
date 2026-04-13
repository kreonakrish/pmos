#!/usr/bin/env bash
# =============================================================================
# PMOS Universal Deploy Script
#
# One script to install / start / stop / restart / validate the entire app
# OR any individual component, on any OS (Linux, macOS, Windows-Git-Bash).
#
# Usage:
#   ./scripts/deploy.sh install               # one-shot setup on a fresh server
#   ./scripts/deploy.sh up [component...]     # start everything or named comps
#   ./scripts/deploy.sh down [component...]   # stop everything or named comps
#   ./scripts/deploy.sh restart [component...]
#   ./scripts/deploy.sh status
#   ./scripts/deploy.sh logs <component>
#   ./scripts/deploy.sh validate
#
# Components:
#   backing                  redis + qdrant
#   gateway agent-mgmt orchestrator memory rag scoring meta-assembly
#   client                   React frontend
#
# Configuration:
#   All values come from pmos/.env. Required keys:
#     OPENAI_API_KEY (or ANTHROPIC/GOOGLE), NEO4J_URI, NEO4J_PASSWORD,
#     MYSQL_HOST/PORT/USER/PASSWORD, JWT_SECRET, AUTH_PASSWORD
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PMOS_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="$PMOS_DIR/docker-compose.yml"
ENV_FILE="$PMOS_DIR/.env"
CLIENT_DIR="$PMOS_DIR/client"
CLIENT_PID_FILE="$PMOS_DIR/.client.pid"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${GREEN}[PMOS]${NC} $*"; }
warn()  { echo -e "${YELLOW}[PMOS]${NC} $*"; }
err()   { echo -e "${RED}[PMOS]${NC} $*" >&2; }
step()  { echo -e "${CYAN}[PMOS]${NC} $*"; }

# ---------------------------------------------------------------------------
# OS detection + .env loading
# ---------------------------------------------------------------------------
detect_os() {
    case "$(uname -s 2>/dev/null)" in
        Linux*)               echo "linux"   ;;
        Darwin*)              echo "macos"   ;;
        MINGW*|MSYS*|CYGWIN*) echo "windows" ;;
        *)                    echo "unknown" ;;
    esac
}
PMOS_OS="$(detect_os)"

if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090,SC1091
    . "$ENV_FILE"
    set +a
fi

# All ports/hosts come from .env; fall back to safe localhost defaults
MYSQL_HOST="${MYSQL_HOST:-127.0.0.1}"
MYSQL_PORT="${MYSQL_PORT:-3306}"
MYSQL_USER="${MYSQL_USER:-root}"
GATEWAY_PORT="${GATEWAY_PORT:-4000}"
AGENT_MGMT_PORT="${AGENT_MGMT_PORT:-4001}"
ORCHESTRATOR_PORT="${ORCHESTRATOR_PORT:-8000}"
MEMORY_PORT="${MEMORY_PORT:-8001}"
RAG_PORT="${RAG_PORT:-8002}"
SCORING_PORT="${SCORING_PORT:-8003}"
META_ASSEMBLY_PORT="${META_ASSEMBLY_PORT:-8004}"
CLIENT_PORT="${CLIENT_PORT:-3000}"
REDIS_PORT="${REDIS_PORT:-6379}"
QDRANT_PORT="${QDRANT_PORT:-6333}"
QDRANT_GRPC_PORT="${QDRANT_GRPC_PORT:-6334}"

BACKEND_SERVICES=(gateway agent-mgmt orchestrator memory rag scoring meta-assembly client)

# ---------------------------------------------------------------------------
# Prereq checks
# ---------------------------------------------------------------------------
require_env() {
    local missing=()
    for v in "$@"; do
        if [ -z "${!v:-}" ]; then missing+=("$v"); fi
    done
    if [ "${#missing[@]}" -gt 0 ]; then
        err "Missing required env vars in .env: ${missing[*]}"
        exit 1
    fi
}

check_docker() {
    if ! command -v docker > /dev/null; then err "docker not installed"; exit 1; fi
    if ! docker info > /dev/null 2>&1; then err "Docker daemon not running"; exit 1; fi
}
check_node() {
    if ! command -v node > /dev/null; then err "Node.js 20+ required"; exit 1; fi
}
check_compose() {
    if ! docker compose version > /dev/null 2>&1; then
        err "docker compose v2 required (docker-compose-plugin)"; exit 1
    fi
}

find_mysql_bin() {
    if command -v mysql > /dev/null 2>&1; then command -v mysql; return 0; fi
    local cands=()
    case "$PMOS_OS" in
        windows) for d in "/c/Program Files/MySQL"/MySQL*; do
                     [ -x "$d/bin/mysql.exe" ] && cands+=("$d/bin/mysql.exe"); done ;;
        macos)   cands+=("/opt/homebrew/bin/mysql" "/usr/local/mysql/bin/mysql" "/usr/local/bin/mysql") ;;
        linux)   cands+=("/usr/bin/mysql" "/usr/local/bin/mysql") ;;
    esac
    for c in "${cands[@]}"; do [ -x "$c" ] && { echo "$c"; return 0; }; done
    return 1
}

# ---------------------------------------------------------------------------
# Backing services (Redis + Qdrant)
# ---------------------------------------------------------------------------
backing_up() {
    step "Starting backing services (Redis, Qdrant)..."
    # Named volumes so data survives `down`/recreation.
    docker volume create pmos_redis_data  > /dev/null 2>&1 || true
    docker volume create pmos_qdrant_data > /dev/null 2>&1 || true

    if docker ps --format '{{.Names}}' | grep -q '^pmos_redis$'; then
        info "Redis already running."
    else
        docker rm -f pmos_redis > /dev/null 2>&1 || true
        docker run -d --name pmos_redis \
            -p "${REDIS_PORT}:6379" \
            -v pmos_redis_data:/data \
            redis:7-alpine redis-server --appendonly yes > /dev/null
        info "Redis started on ${REDIS_PORT} (volume: pmos_redis_data)."
    fi
    if docker ps --format '{{.Names}}' | grep -q '^pmos_qdrant$'; then
        info "Qdrant already running."
    else
        docker rm -f pmos_qdrant > /dev/null 2>&1 || true
        docker run -d --name pmos_qdrant \
            -p "${QDRANT_PORT}:6333" -p "${QDRANT_GRPC_PORT}:6334" \
            -v pmos_qdrant_data:/qdrant/storage \
            qdrant/qdrant:latest > /dev/null
        info "Qdrant started on ${QDRANT_PORT} (volume: pmos_qdrant_data)."
    fi
}
backing_down() {
    step "Stopping backing services..."
    docker rm -f pmos_redis pmos_qdrant > /dev/null 2>&1 || true
    info "Redis & Qdrant stopped."
}

# ---------------------------------------------------------------------------
# Backend services (docker-compose)
# ---------------------------------------------------------------------------
backend_up() {
    local svcs=("$@")
    cd "$PMOS_DIR"
    if [ "${#svcs[@]}" -eq 0 ]; then
        step "Starting all 7 backend services..."
        docker compose -f "$COMPOSE_FILE" up -d --build
    else
        step "Starting backend services: ${svcs[*]}"
        docker compose -f "$COMPOSE_FILE" up -d --build "${svcs[@]}"
    fi
    info "Backend services started."
}
backend_down() {
    local svcs=("$@")
    cd "$PMOS_DIR"
    if [ "${#svcs[@]}" -eq 0 ]; then
        step "Stopping all backend services..."
        docker compose -f "$COMPOSE_FILE" down
    else
        step "Stopping backend services: ${svcs[*]}"
        docker compose -f "$COMPOSE_FILE" stop "${svcs[@]}"
    fi
    info "Backend services stopped."
}

# ---------------------------------------------------------------------------
# Frontend client
# ---------------------------------------------------------------------------
client_dev_up() {
    step "Starting frontend client (Vite dev mode) on port ${CLIENT_PORT}..."
    cd "$CLIENT_DIR"
    [ -d node_modules ] || { info "Installing client deps..."; npm install; }
    client_dev_down_quiet
    npx vite --port "$CLIENT_PORT" --host > "$PMOS_DIR/.client.log" 2>&1 &
    echo "$!" > "$CLIENT_PID_FILE"
    info "Client (dev) started (PID $!). Log: pmos/.client.log"
    info "URL: http://localhost:${CLIENT_PORT}"
}
client_dev_down_quiet() {
    if [ -f "$CLIENT_PID_FILE" ]; then
        local PID; PID="$(cat "$CLIENT_PID_FILE")"
        kill "$PID" > /dev/null 2>&1 || true
        rm -f "$CLIENT_PID_FILE"
    fi
    if   command -v lsof  > /dev/null; then lsof -ti:"$CLIENT_PORT" 2>/dev/null | xargs -r kill > /dev/null 2>&1 || true
    elif command -v fuser > /dev/null; then fuser -k "${CLIENT_PORT}/tcp" > /dev/null 2>&1 || true
    fi
}
client_dev_down() { step "Stopping dev client..."; client_dev_down_quiet; info "Dev client stopped."; }

# ---------------------------------------------------------------------------
# Component dispatch
# ---------------------------------------------------------------------------
is_backend_svc() {
    local s="$1"
    for x in "${BACKEND_SERVICES[@]}"; do [ "$x" = "$s" ] && return 0; done
    return 1
}

dispatch_up() {
    if [ "$#" -eq 0 ]; then
        check_docker; check_compose
        backing_up
        backend_up      # builds & starts all 7 services + client (compose)
        return
    fi
    local backends=()
    for c in "$@"; do
        case "$c" in
            backing)    check_docker; backing_up ;;
            client-dev) check_node; client_dev_up ;;
            *) if is_backend_svc "$c"; then backends+=("$c"); else err "Unknown component: $c"; exit 1; fi ;;
        esac
    done
    if [ "${#backends[@]}" -gt 0 ]; then
        check_docker; check_compose
        backend_up "${backends[@]}"
    fi
}

dispatch_down() {
    if [ "$#" -eq 0 ]; then
        client_dev_down_quiet
        backend_down
        backing_down
        return
    fi
    local backends=()
    for c in "$@"; do
        case "$c" in
            backing)    backing_down ;;
            client-dev) client_dev_down ;;
            *) if is_backend_svc "$c"; then backends+=("$c"); else err "Unknown component: $c"; exit 1; fi ;;
        esac
    done
    [ "${#backends[@]}" -gt 0 ] && backend_down "${backends[@]}"
}

# ---------------------------------------------------------------------------
# Health / status / logs / validate / install
# ---------------------------------------------------------------------------
health() {
    step "Health check"
    local services=(
        "Gateway:http://localhost:${GATEWAY_PORT}/health"
        "Agent-Mgmt:http://localhost:${AGENT_MGMT_PORT}/health"
        "Orchestrator:http://localhost:${ORCHESTRATOR_PORT}/health"
        "Memory:http://localhost:${MEMORY_PORT}/health"
        "RAG:http://localhost:${RAG_PORT}/health"
        "Scoring:http://localhost:${SCORING_PORT}/health"
        "Meta-Assembly:http://localhost:${META_ASSEMBLY_PORT}/health"
        "Client:http://localhost:${CLIENT_PORT}"
    )
    for svc in "${services[@]}"; do
        local n="${svc%%:*}" u="${svc#*:}"
        if curl -sf --max-time 3 "$u" > /dev/null 2>&1; then
            echo -e "  ${GREEN}[UP]${NC}   $n  ($u)"
        else
            echo -e "  ${RED}[DOWN]${NC} $n  ($u)"
        fi
    done
    for hp in "MySQL:${MYSQL_HOST}:${MYSQL_PORT}" "Redis:127.0.0.1:${REDIS_PORT}" "Qdrant:127.0.0.1:${QDRANT_PORT}"; do
        local n h p _rest
        n="${hp%%:*}"
        _rest="${hp#*:}"
        h="${_rest%%:*}"
        p="${_rest##*:}"
        if (echo > /dev/tcp/$h/$p) 2>/dev/null; then
            echo -e "  ${GREEN}[UP]${NC}   $n  ($h:$p)"
        else
            echo -e "  ${RED}[DOWN]${NC} $n  ($h:$p)"
        fi
    done
}

status() {
    step "Docker containers:"
    docker ps --filter "name=pmos" --format "  {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || true
    echo
    health
}

logs() {
    local svc="${1:-}"
    [ -z "$svc" ] && { err "Usage: deploy.sh logs <component>"; exit 1; }
    if [ "$svc" = "client-dev" ]; then
        tail -f "$PMOS_DIR/.client.log"
    else
        cd "$PMOS_DIR"
        docker compose -f "$COMPOSE_FILE" logs -f "$svc"
    fi
}

validate() {
    step "Running validation suite..."
    cd "$PMOS_DIR"
    bash "$SCRIPT_DIR/run_tests.sh"
}

install() {
    step "PMOS install on $PMOS_OS"
    [ -f "$ENV_FILE" ] || { err "$ENV_FILE missing. Copy .env.example and fill it in."; exit 1; }
    require_env NEO4J_URI NEO4J_PASSWORD MYSQL_PASSWORD JWT_SECRET AUTH_PASSWORD
    check_docker; check_compose; check_node

    # Check MySQL reachable
    local MYSQL_BIN
    if MYSQL_BIN="$(find_mysql_bin)"; then
        if MYSQL_PWD="$MYSQL_PASSWORD" "$MYSQL_BIN" -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" \
            -e "SELECT 1" > /dev/null 2>&1; then
            info "MySQL reachable at $MYSQL_HOST:$MYSQL_PORT"
        else
            err "Cannot connect to MySQL at $MYSQL_HOST:$MYSQL_PORT with provided credentials."; exit 1
        fi
    else
        warn "mysql client not found — skipping connectivity probe (bootstrap will retry)."
    fi

    backing_up
    step "Bootstrapping schema, Neo4j constraints, Redis streams..."
    bash "$SCRIPT_DIR/bootstrap.sh"
    backend_up
    info "Waiting 10s for services to settle..."; sleep 10
    health
    info "PMOS install complete."
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
cmd="${1:-help}"; shift || true
case "$cmd" in
    install)  install ;;
    up|start) dispatch_up "$@" ;;
    down|stop) dispatch_down "$@" ;;
    restart)  dispatch_down "$@"; dispatch_up "$@" ;;
    status)   status ;;
    health)   health ;;
    logs)     logs "$@" ;;
    validate) validate ;;
    *)
        cat <<EOF

PMOS Universal Deploy Script

Usage: $0 <command> [component...]

Commands:
  install                One-shot fresh-server setup (validates env, runs bootstrap, starts everything)
  up [component...]      Start everything, or named components
  down [component...]    Stop everything, or named components
  restart [component...] Down then up
  status                 Containers + health
  health                 Health check only
  logs <component>       Tail logs for a single component
  validate               Run the validation suite

Components:
  backing                Redis + Qdrant
  gateway agent-mgmt orchestrator memory rag scoring meta-assembly
  client                 React frontend (production: nginx container)
  client-dev             React frontend (Vite dev server on host, hot reload)

Examples:
  $0 install
  $0 up                       # everything
  $0 up orchestrator scoring  # only those two
  $0 restart gateway
  $0 logs orchestrator

EOF
        exit 1 ;;
esac
