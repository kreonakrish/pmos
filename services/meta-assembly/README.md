# PMOS Meta-Assembly Service

Self-extending capability generation for the Perpetual Multi-Agent Orchestration System.

When the orchestrator cannot find a qualified agent for a task, the meta-assembly service
detects the capability gap, generates a new tool/skill/agent spec via LLM, validates it
through static analysis and sandboxed execution, and registers it across all backing stores.

## Safety

- Generated code is **never** executed via `eval()` or `exec()` in the main process.
- All generated code runs in an **isolated subprocess** with configurable timeout
  (`META_SANDBOX_TIMEOUT_SEC`, default 30s) and memory limit (`META_SANDBOX_MEMORY_MB`,
  default 256 MB via `RLIMIT_AS` on Linux).
- Imports are restricted to a configurable whitelist (`META_ALLOWED_IMPORTS`).
- Three-stage AST-based validation (syntax, dependency whitelist, safety patterns)
  runs before any code execution.
- Every generated spec is logged in full at INFO level for audit trail.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/meta/detect-gap` | Analyse a failed task context and identify the missing capability |
| POST | `/v1/meta/generate-spec` | Generate a capability spec from a gap description, validate, and sandbox-test |
| POST | `/v1/meta/register` | Register a validated spec into MySQL, Neo4j, and publish Redis event |
| GET | `/health` | Liveness check with MySQL, Neo4j, Redis connectivity status |
| GET | `/metrics` | Prometheus metrics in text exposition format |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `META_ASSEMBLY_PORT` | `8004` | Service listen port |
| `MYSQL_HOST` | `localhost` | MySQL host |
| `MYSQL_PORT` | `3306` | MySQL port |
| `MYSQL_DB` | `pmos` | MySQL database name |
| `MYSQL_USER` | `root` | MySQL user |
| `MYSQL_PASSWORD` | *(required)* | MySQL password |
| `NEO4J_URI` | `neo4j+s://8414810d.databases.neo4j.io` | Neo4j connection URI |
| `NEO4J_USER` | `neo4j` | Neo4j user |
| `NEO4J_PASSWORD` | *(required)* | Neo4j password |
| `REDIS_URL` | `redis://localhost:6379` | Redis connection URL |
| `LLM_PROVIDER` | `openai` | LLM provider |
| `LLM_MODEL` | `gpt-4o` | LLM model name |
| `OPENAI_API_KEY` | *(required)* | OpenAI API key |
| `META_ALLOWED_IMPORTS` | `requests,json,re,math,...` | Comma-separated import whitelist for generated code |
| `META_SANDBOX_TIMEOUT_SEC` | `30` | Subprocess execution timeout |
| `META_SANDBOX_MEMORY_MB` | `256` | Subprocess memory limit (Linux RLIMIT_AS) |
| `RETRY_MAX_ATTEMPTS` | `3` | Max retry attempts for outbound HTTP calls |
| `RETRY_WAIT_MULTIPLIER` | `1` | Exponential backoff multiplier |
| `RETRY_WAIT_MAX_SEC` | `10` | Max wait between retries |
| `LOG_LEVEL` | `INFO` | Structured log level |

## Running

```bash
# Development
uvicorn app.main:app --host 0.0.0.0 --port 8004 --reload

# Docker
docker build -t pmos-meta-assembly .
docker run -p 8004:8004 --env-file .env pmos-meta-assembly
```

## Testing

```bash
# All tests
pytest tests/ -v --cov=app --cov-report=term-missing

# Unit tests only
pytest tests/unit/ -v

# Integration tests only
pytest tests/integration/ -v
```
