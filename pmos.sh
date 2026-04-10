#!/usr/bin/env bash
# =============================================================================
# PMOS Service Manager
# Usage: ./pmos.sh [start|stop|restart|status]
#
# Manages:
#   - Backing services: MySQL (host), Redis (Docker), Qdrant (Docker)
#   - Backend services: 7 Docker containers via docker-compose
#   - Frontend client: Vite dev server on port 3000
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLIENT_DIR="$SCRIPT_DIR/client"
CLIENT_PID_FILE="$SCRIPT_DIR/.client.pid"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[PMOS]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[PMOS]${NC} $1"; }
log_error() { echo -e "${RED}[PMOS]${NC} $1"; }
log_step()  { echo -e "${CYAN}[PMOS]${NC} $1"; }

# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
check_docker() {
    if ! docker info > /dev/null 2>&1; then
        log_error "Docker is not running. Please start Docker Desktop first."
        exit 1
    fi
    log_info "Docker is running."
}

check_mysql() {
    local MYSQL_BIN="/c/Program Files/MySQL/MySQL Server 8.0/bin/mysql.exe"
    if [ ! -f "$MYSQL_BIN" ]; then
        MYSQL_BIN="mysql"
    fi
    if MYSQL_PWD="${MYSQL_PASSWORD:-Jpmc2024H}" "$MYSQL_BIN" -h 127.0.0.1 -u root -e "SELECT 1" > /dev/null 2>&1; then
        log_info "MySQL is running on port 3306."
        return 0
    else
        log_warn "MySQL is not reachable on port 3306. Some services may fail to connect."
        return 1
    fi
}

check_node() {
    if ! command -v node > /dev/null 2>&1; then
        log_error "Node.js not found. Please install Node.js 20+."
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# Backing services (Redis + Qdrant as standalone Docker containers)
# ---------------------------------------------------------------------------
start_backing() {
    log_step "Starting backing services (Redis, Qdrant)..."

    # Redis
    if docker ps --format '{{.Names}}' | grep -q '^pmos_redis$'; then
        log_info "Redis already running."
    else
        docker rm -f pmos_redis > /dev/null 2>&1 || true
        docker run -d --name pmos_redis -p 6379:6379 redis:7-alpine > /dev/null
        log_info "Redis started on port 6379."
    fi

    # Qdrant
    if docker ps --format '{{.Names}}' | grep -q '^pmos_qdrant$'; then
        log_info "Qdrant already running."
    else
        docker rm -f pmos_qdrant > /dev/null 2>&1 || true
        docker run -d --name pmos_qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant:latest > /dev/null
        log_info "Qdrant started on port 6333."
    fi
}

stop_backing() {
    log_step "Stopping backing services..."
    docker rm -f pmos_redis pmos_qdrant > /dev/null 2>&1 || true
    log_info "Redis and Qdrant stopped."
}

# ---------------------------------------------------------------------------
# Backend services (docker-compose)
# ---------------------------------------------------------------------------
start_backend() {
    log_step "Starting 7 backend services via docker-compose..."
    cd "$SCRIPT_DIR"
    docker compose -f "$COMPOSE_FILE" up -d --build
    log_info "Backend services started."
}

stop_backend() {
    log_step "Stopping backend services..."
    cd "$SCRIPT_DIR"
    docker compose -f "$COMPOSE_FILE" down
    log_info "Backend services stopped."
}

# ---------------------------------------------------------------------------
# Frontend client (Vite dev server)
# ---------------------------------------------------------------------------
start_client() {
    log_step "Starting frontend client on port 3000..."
    cd "$CLIENT_DIR"

    # Install deps if needed
    if [ ! -d "node_modules" ]; then
        log_info "Installing client dependencies..."
        npm install
    fi

    # Kill any existing client process
    stop_client_quiet

    # Start Vite in background
    npx vite --port 3000 --host > "$SCRIPT_DIR/.client.log" 2>&1 &
    local PID=$!
    echo "$PID" > "$CLIENT_PID_FILE"
    log_info "Frontend client started (PID: $PID). Log: pmos/.client.log"
    log_info "Client URL: http://localhost:3000"
}

stop_client_quiet() {
    if [ -f "$CLIENT_PID_FILE" ]; then
        local PID
        PID=$(cat "$CLIENT_PID_FILE")
        kill "$PID" > /dev/null 2>&1 || true
        rm -f "$CLIENT_PID_FILE"
    fi
    # Also kill any vite on port 3000
    if command -v lsof > /dev/null 2>&1; then
        lsof -ti:3000 2>/dev/null | xargs kill > /dev/null 2>&1 || true
    fi
}

stop_client() {
    log_step "Stopping frontend client..."
    stop_client_quiet
    log_info "Frontend client stopped."
}

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
check_health() {
    log_step "Checking service health..."
    echo ""

    local services=(
        "Gateway:http://localhost:4000/health"
        "Agent-Mgmt:http://localhost:4001/health"
        "Orchestrator:http://localhost:8000/health"
        "Memory:http://localhost:8001/health"
        "RAG:http://localhost:8002/health"
        "Scoring:http://localhost:8003/health"
        "Meta-Assembly:http://localhost:8004/health"
        "Client:http://localhost:3000"
    )

    for svc in "${services[@]}"; do
        local name="${svc%%:*}"
        local url="${svc#*:}"
        if curl -sf --max-time 3 "$url" > /dev/null 2>&1; then
            echo -e "  ${GREEN}[UP]${NC}   $name ($url)"
        else
            echo -e "  ${RED}[DOWN]${NC} $name ($url)"
        fi
    done

    echo ""

    # Backing services
    local backing=(
        "MySQL:127.0.0.1:3306"
        "Redis:127.0.0.1:6379"
        "Qdrant:127.0.0.1:6333"
    )
    for svc in "${backing[@]}"; do
        local name="${svc%%:*}"
        local host_port="${svc#*:}"
        local host="${host_port%%:*}"
        local port="${host_port##*:}"
        if (echo > /dev/tcp/$host/$port) 2>/dev/null; then
            echo -e "  ${GREEN}[UP]${NC}   $name ($host:$port)"
        else
            echo -e "  ${RED}[DOWN]${NC} $name ($host:$port)"
        fi
    done
    echo ""
}

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
do_start() {
    echo ""
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}  PMOS — Starting All Services${NC}"
    echo -e "${CYAN}========================================${NC}"
    echo ""
    check_docker
    check_node
    check_mysql || true
    echo ""
    start_backing
    echo ""
    start_backend
    echo ""
    start_client
    echo ""
    log_info "Waiting 10s for services to initialize..."
    sleep 10
    check_health
    log_info "PMOS is ready."
}

do_stop() {
    echo ""
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}  PMOS — Stopping All Services${NC}"
    echo -e "${CYAN}========================================${NC}"
    echo ""
    stop_client
    stop_backend
    stop_backing
    echo ""
    log_info "All PMOS services stopped."
}

do_restart() {
    do_stop
    echo ""
    do_start
}

do_status() {
    echo ""
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}  PMOS — Service Status${NC}"
    echo -e "${CYAN}========================================${NC}"
    echo ""

    # Docker containers
    log_step "Docker containers:"
    docker ps --filter "name=pmos" --format "  {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || echo "  Docker not running"
    echo ""

    # Client process
    if [ -f "$CLIENT_PID_FILE" ]; then
        local PID
        PID=$(cat "$CLIENT_PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            log_info "Client running (PID: $PID)"
        else
            log_warn "Client PID file exists but process is dead."
        fi
    else
        log_warn "Client not running."
    fi
    echo ""

    check_health
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
case "${1:-help}" in
    start)   do_start ;;
    stop)    do_stop ;;
    restart) do_restart ;;
    status)  do_status ;;
    health)  check_health ;;
    *)
        echo ""
        echo "PMOS Service Manager"
        echo ""
        echo "Usage: $0 {start|stop|restart|status|health}"
        echo ""
        echo "  start    Start all services (backing + backend + client)"
        echo "  stop     Stop all services"
        echo "  restart  Stop then start all services"
        echo "  status   Show container status and health checks"
        echo "  health   Quick health check on all endpoints"
        echo ""
        exit 1
        ;;
esac
