# PMOS Agent Management Service

Node.js 20 / Express 5 / TypeScript service for managing Agents, Tools, Teams, and Capabilities.

**Port:** 4001

---

## Environment Variables

| Variable | Default | Required | Description |
|---|---|---|---|
| `AGENT_MGMT_PORT` | `4001` | No | HTTP listen port |
| `MYSQL_HOST` | `localhost` | No | MySQL host |
| `MYSQL_PORT` | `3306` | No | MySQL port |
| `MYSQL_DB` | `pmos` | No | MySQL database name |
| `MYSQL_USER` | `root` | No | MySQL user |
| `MYSQL_PASSWORD` | — | **Yes** | MySQL password |
| `MYSQL_POOL_SIZE` | `20` | No | Connection pool size |
| `REDIS_URL` | `redis://localhost:6379` | No | Redis connection URL |
| `TOOL_HEALTH_INTERVAL_SEC` | `60` | No | Seconds between tool health poll cycles |
| `LOG_LEVEL` | `INFO` | No | Log level: DEBUG / INFO / WARN / ERROR |
| `NODE_ENV` | `development` | No | Runtime environment |

---

## API Endpoints

All routes are versioned under `/v1`. Errors always return:
```json
{ "error": "message", "code": "ERROR_CODE", "trace_id": "..." }
```

### Agents

| Method | Path | Description |
|---|---|---|
| GET | `/v1/agents` | List agents (query: `status`, `meta_capable`) |
| POST | `/v1/agents` | Create agent |
| GET | `/v1/agents/:agent_id` | Get agent by UUID |
| PUT | `/v1/agents/:agent_id` | Update agent |
| DELETE | `/v1/agents/:agent_id` | Soft-delete agent (sets status=DEPRECATED) |
| GET | `/v1/agents/:agent_id/tools` | List agent's assigned tools |
| POST | `/v1/agents/:agent_id/tools` | Assign tool to agent |

### Tools

| Method | Path | Description |
|---|---|---|
| GET | `/v1/tools` | List all tools |
| POST | `/v1/tools` | Create tool |
| GET | `/v1/tools/:tool_id` | Get tool by UUID |
| PUT | `/v1/tools/:tool_id` | Update tool |
| DELETE | `/v1/tools/:tool_id` | Delete tool |

### Teams

| Method | Path | Description |
|---|---|---|
| GET | `/v1/teams` | List teams |
| POST | `/v1/teams` | Create team |
| GET | `/v1/teams/:team_id` | Get team with agent roster |
| PUT | `/v1/teams/:team_id` | Update team |
| POST | `/v1/teams/:team_id/agents` | Add agent to team |
| DELETE | `/v1/teams/:team_id/agents/:agent_id` | Remove agent from team |

### Capabilities

| Method | Path | Description |
|---|---|---|
| GET | `/v1/capabilities` | List active capabilities |
| POST | `/v1/capabilities` | Register capability (from meta-assembly) |

**POST /v1/capabilities body:**
```json
{
  "capability_type": "TOOL | SKILL | AGENT",
  "capability_id": "string",
  "name": "string",
  "description": "string (optional)",
  "spec_json": { } ,
  "gap_id": "string (optional)",
  "validation_score": 0.91
}
```

### Infrastructure

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Service health + MySQL/Redis connectivity |
| GET | `/metrics` | Prometheus metrics |

---

## Tool Health Scheduler

Runs every `TOOL_HEALTH_INTERVAL_SEC` seconds. For each ACTIVE/DEGRADED tool with a `hostname`/`endpoint`:
- Issues HTTP GET with 5-second timeout
- Updates `avg_latency_ms` and `success_rate` via EMA (alpha=0.2)
- Publishes to Redis stream `events:tool_health` **only when status changes**

Redis event schema:
```json
{
  "schema_version": "1",
  "trace_id": "uuid-v4",
  "source_service": "agent-mgmt",
  "timestamp": "ISO8601",
  "tool_id": "...",
  "tool_name": "...",
  "previous_status": "ACTIVE",
  "current_status": "DEGRADED",
  "avg_latency_ms": 234.5,
  "success_rate": 0.82
}
```

---

## Running Tests

```bash
# All tests with coverage
npm test

# Unit tests only
npm run test:unit

# Integration tests only
npm run test:integration
```

Tests use Jest with ts-jest. No real DB or Redis connections — all adapters are mocked.

---

## Local Development

```bash
# Install dependencies
npm install

# Set required env vars
export MYSQL_PASSWORD=yourpassword

# Build TypeScript
npm run build

# Start service
npm start
```

---

## Docker

```bash
# Build image
docker build -t pmos-agent-mgmt .

# Run with env vars
docker run -p 4001:4001 \
  -e MYSQL_PASSWORD=yourpassword \
  -e MYSQL_HOST=mysql \
  -e REDIS_URL=redis://redis:6379 \
  pmos-agent-mgmt
```

---

## Prometheus Metrics

Exposed on `GET /metrics` (Prometheus text format):

| Metric | Type | Labels |
|---|---|---|
| `request_total` | Counter | `method`, `path`, `status` |
| `request_duration_seconds` | Histogram | `method`, `path` |
| Default Node.js / process metrics | — | — |
