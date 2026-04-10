# CONVENTIONS.md — Code Standards, Naming & Patterns

## Service Internal Layout

Every service follows this structure:
```
services/<name>/
├── app/
│   ├── __init__.py (Python) or main.ts (Node)
│   ├── main.py / main.ts          # entry point
│   ├── config.py / config.ts      # env var loader
│   ├── routes/                    # HTTP handlers
│   ├── services/                  # business logic
│   ├── models/                    # data models
│   ├── adapters/                  # swappable backends
│   └── utils/
│       ├── logger.py / logger.ts  # structured JSON logger
│       └── telemetry.py / telemetry.ts
├── tests/
│   ├── unit/
│   ├── integration/
│   └── conftest.py / jest.config.ts
├── Dockerfile
├── requirements.txt / package.json
└── README.md
```

## Naming

### Python
- Files: `snake_case.py`
- Classes: `PascalCase` (adapters end with `Adapter`, services with `Service`)
- Functions/variables: `snake_case`
- Constants: `UPPER_SNAKE_CASE`

### TypeScript
- Files: `camelCase.ts` (utilities), `PascalCase.tsx` (React components)
- All route handlers: function name matches HTTP method + noun (`getAgents`, `createTool`)

### API Endpoints
- REST: `/{resource}/{id}/{sub-resource}` — pluralized nouns
- All versioned: `/v1/...`
- Error format: `{ "error": str, "code": str, "trace_id": str }`

### Database
- MySQL tables: `snake_case`, plural
- Neo4j nodes: `PascalCase` labels
- Neo4j relationships: `UPPER_SNAKE_CASE`
- Redis keys: `{service}:{entity}:{id}:{field}`

## Logging

Every service uses structured JSON logging. No bare `print()`.

```python
# Every log line includes:
{
  "level": "INFO",
  "message": "...",
  "service": "orchestrator",
  "layer": "service",        # router | service | adapter | model
  "trace_id": "uuid",
  "span_id": "uuid",
  "duration_ms": 42,
  "timestamp": "2026-04-09T..."
}
```

## Configuration

All env vars loaded via Pydantic `BaseSettings` (Python) or `dotenv` (Node). Never hardcode:
- Connection strings, passwords, API keys
- Scoring thresholds or weights
- Prompt templates
- Timeout values

```python
# Pattern:
from app.config import settings
# settings.neo4j_uri, settings.redis_url, etc.
```

## Retry & Circuit Breaker

Every outbound HTTP call uses tenacity retry with exponential backoff:
```python
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=10))
```

Orchestrator wraps downstream calls in circuit breakers (CLOSED → OPEN after N failures → HALF_OPEN after timeout → CLOSED on success).

## Testing

| Level | Location | Scope | Mocking |
|-------|----------|-------|---------|
| Unit | `tests/unit/` | Single function/class | Mock all externals |
| Integration | `tests/integration/` | Service with real DB | Real containers |
| Adapter | `tests/adapters/` | Backend implementations | Mock client libraries |

Run all: `./scripts/run_tests.sh`

## Docker

All services containerized. Local dev:
```bash
docker compose up -d --build <service-name>   # rebuild one service
docker compose up -d                          # all services
docker logs pmos-<service> --tail 50          # check logs
```

Networking: Services inside Docker reach MySQL on host via `host.docker.internal:3306`. Services reach each other via container names or `host.docker.internal:{port}`.
