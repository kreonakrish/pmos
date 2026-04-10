# PMOS Gateway Service

API Gateway for the Perpetual Multi-Agent Orchestration System.
All inbound HTTP traffic from the React client and external callers enters here.

## Responsibilities

- JWT Bearer token and API key authentication
- Per-user token-bucket rate limiting via Redis
- Request ID (`x-request-id`) injection and propagation
- Reverse proxy to: Orchestrator, Agent-Mgmt, RAG
- WebSocket streaming endpoint for real-time conversation responses
- Health aggregation across all downstream services
- Prometheus metrics exposure

## Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | None | Aggregated downstream health |
| GET | `/metrics` | None | Prometheus metrics |
| POST | `/v1/chat` | JWT/ApiKey | Start or continue a conversation (proxied to Orchestrator) |
| GET | `/v1/tasks` | JWT/ApiKey | List tasks (proxied to Orchestrator) |
| GET | `/v1/tasks/:id` | JWT/ApiKey | Get task detail (proxied to Orchestrator) |
| GET | `/v1/agents` | JWT/ApiKey | List agents (proxied to Agent-Mgmt) |
| POST | `/v1/agents` | JWT/ApiKey | Create agent (proxied to Agent-Mgmt) |
| GET | `/v1/agents/:id` | JWT/ApiKey | Get agent (proxied to Agent-Mgmt) |
| PUT | `/v1/agents/:id` | JWT/ApiKey | Update agent (proxied to Agent-Mgmt) |
| DELETE | `/v1/agents/:id` | JWT/ApiKey | Delete agent (proxied to Agent-Mgmt) |
| GET | `/v1/tools` | JWT/ApiKey | List tools (proxied to Agent-Mgmt) |
| POST | `/v1/tools` | JWT/ApiKey | Register tool (proxied to Agent-Mgmt) |
| GET | `/v1/teams` | JWT/ApiKey | List teams (proxied to Agent-Mgmt) |
| POST | `/v1/teams` | JWT/ApiKey | Create team (proxied to Agent-Mgmt) |
| POST | `/v1/rag/query` | JWT/ApiKey | RAG query (proxied to RAG service) |
| POST | `/v1/documents` | JWT/ApiKey | Ingest document (proxied to RAG + published to Redis stream `events:documents`) |
| WS | `/v1/ws/chat?token=<JWT>` | JWT (query param) | Streaming conversation |

## WebSocket Protocol

Connect with: `ws://<gateway-host>:4000/v1/ws/chat?token=<JWT>`

Send JSON messages to start a chat session. Receive stream chunks:

```json
{
  "type": "step | tool_call | score | course_correct | complete | error",
  "agent_name": "string",
  "content": "string",
  "score": null,
  "trace_id": "string",
  "timestamp": "ISO8601"
}
```

Connection closes automatically when `type: "complete"` or `type: "error"` is received.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GATEWAY_PORT` | No | `4000` | HTTP listen port |
| `JWT_SECRET` | **Yes** | — | Secret for JWT verification. Min 32 chars. |
| `API_KEY` | No | — | Static API key (alternative to JWT) |
| `RATE_LIMIT_RPM` | No | `120` | Requests per minute per user |
| `ORCHESTRATOR_URL` | **Yes** | — | Base URL of the Orchestrator service |
| `AGENT_MGMT_URL` | **Yes** | — | Base URL of the Agent-Mgmt service |
| `RAG_SERVICE_URL` | **Yes** | — | Base URL of the RAG service |
| `SCORING_SERVICE_URL` | No | `http://localhost:8003` | Base URL of Scoring service (health only) |
| `MEMORY_SERVICE_URL` | No | `http://localhost:8001` | Base URL of Memory service (health only) |
| `META_ASSEMBLY_URL` | No | `http://localhost:8004` | Base URL of Meta-Assembly service (health only) |
| `REDIS_URL` | No | `redis://localhost:6379` | Redis connection URL for rate limiter |
| `LOG_LEVEL` | No | `INFO` | One of: `DEBUG`, `INFO`, `WARN`, `ERROR` |
| `NODE_ENV` | No | `development` | `development`, `production`, or `test` |
| `DOWNSTREAM_TIMEOUT_MS` | No | `3000` | Timeout for downstream health checks (ms) |

## Authentication

**JWT:** Set `Authorization: Bearer <token>` header. Token must be signed with `JWT_SECRET`.

**API Key:** Set `x-api-key: <key>` header. Key must match `API_KEY` env var.

**Public paths** (no auth): `GET /health`, `GET /metrics`

## Running Locally

```bash
# 1. Copy and fill environment
cp ../../.env.example .env
# Required: JWT_SECRET, ORCHESTRATOR_URL, AGENT_MGMT_URL, RAG_SERVICE_URL

# 2. Install dependencies
npm install

# 3. Start in development mode (ts-node)
npm run dev

# 4. Or build and run
npm run build && npm start
```

## Running with Docker

```bash
docker build -t pmos-gateway .
docker run -p 4000:4000 --env-file .env pmos-gateway
```

## Running Tests

```bash
# All tests with coverage
npm test

# Unit tests only
npm run test:unit

# Integration tests only (no external services needed; uses nock)
npm run test:integration
```

Test configuration is in `tests/jest.config.ts`.

### Unit Tests
- `tests/unit/test_auth_middleware.ts` — JWT valid/expired/missing, API key valid/wrong
- `tests/unit/test_rate_limiter.ts` — burst pass, sustained 429, user isolation, fail-open

### Integration Tests
- `tests/integration/test_routing.ts` — proxy routes verified with nock mocks, health aggregation

## Logging

All logs are emitted as structured JSON to stdout. Sample:

```json
{
  "level": "INFO",
  "message": "proxy_chat",
  "service": "gateway",
  "timestamp": "2026-03-27T12:00:00.000Z",
  "trace_id": "550e8400-e29b-41d4-a716-446655440000",
  "layer": "router"
}
```

Every log line includes `service`, `timestamp`. Most include `trace_id` and `layer`.

## Health Check

`GET /health` returns:

```json
{
  "status": "ok | degraded | down",
  "services": {
    "orchestrator": { "status": "ok", "latency_ms": 12 },
    "agent-mgmt": { "status": "ok", "latency_ms": 8 },
    "rag": { "status": "down", "latency_ms": 3001, "error": "connect ECONNREFUSED" },
    "scoring": { "status": "ok", "latency_ms": 15 },
    "memory": { "status": "ok", "latency_ms": 10 },
    "meta-assembly": { "status": "ok", "latency_ms": 20 }
  },
  "timestamp": "2026-03-27T12:00:00.000Z"
}
```

HTTP status is always 200; read `body.status` for the actual health state.
