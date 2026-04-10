# Orchestrator Service

The orchestrator service is the core execution engine of the PMOS platform. It owns the 9-step execution pipeline, the living Neo4j task graph, agent selection with fallback chains, severity-aware course correction, and circuit-breaker-protected calls to all downstream services.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/orchestrator/chat` | Execute the full 9-step pipeline for a user message. Accepts optional `stream: true` for SSE streaming. |
| `GET` | `/v1/orchestrator/sessions/{session_id}` | Retrieve session details including graph status and task nodes. |
| `GET` | `/health` | Health check. Returns status of Neo4j and Redis connections. |
| `GET` | `/metrics` | Prometheus metrics endpoint. |

### POST /v1/orchestrator/chat

**Request body:**

```json
{
  "conversation_id": "string",
  "message": "string",
  "team_id": "string",
  "stream": false,
  "agent_id": null,
  "metadata": {}
}
```

**Response (non-streaming):**

```json
{
  "session_id": "string",
  "conversation_id": "string",
  "response": "string",
  "graph_id": "string",
  "score": 0.85,
  "trace_id": "string",
  "steps": []
}
```

### GET /v1/orchestrator/sessions/{session_id}

**Response:**

```json
{
  "session_id": "string",
  "graph_id": "string",
  "status": "COMPLETED",
  "nodes": [],
  "trace_id": "string"
}
```

### GET /health

**Response:**

```json
{
  "status": "ok",
  "neo4j": true,
  "redis": true,
  "service": "orchestrator"
}
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NEO4J_URI` | Yes | `neo4j+s://8414810d.databases.neo4j.io` | Neo4j AuraDB connection URI |
| `NEO4J_USER` | Yes | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | Yes | _(none)_ | Neo4j password |
| `NEO4J_DATABASE` | No | `neo4j` | Neo4j database name |
| `REDIS_URL` | No | `redis://localhost:6379` | Redis connection URL |
| `MEMORY_SERVICE_URL` | No | `http://localhost:8001` | Memory service base URL |
| `SCORING_SERVICE_URL` | No | `http://localhost:8003` | Scoring service base URL |
| `RAG_SERVICE_URL` | No | `http://localhost:8002` | RAG service base URL |
| `META_ASSEMBLY_URL` | No | `http://localhost:8004` | Meta-assembly service base URL |
| `AGENT_MGMT_URL` | No | `http://localhost:4001` | Agent management service base URL |
| `LLM_PROVIDER` | No | `openai` | LLM provider identifier |
| `LLM_MODEL` | No | `gpt-4o` | LLM model name |
| `LLM_TEMPERATURE` | No | `0.2` | LLM sampling temperature |
| `LLM_MAX_TOKENS` | No | `4096` | Maximum tokens per LLM call |
| `OPENAI_API_KEY` | Yes | _(none)_ | OpenAI API key |
| `MAX_CONCURRENT_LLM_CALLS` | No | `10` | Semaphore limit for concurrent LLM calls |
| `ORCHESTRATOR_PORT` | No | `8000` | Service listen port |
| `CB_TIMEOUT_SEC` | No | `30` | Circuit breaker recovery timeout in seconds |
| `CB_FAILURE_THRESHOLD` | No | `5` | Consecutive failures before circuit opens |
| `RETRY_MAX_ATTEMPTS` | No | `3` | Maximum retry attempts for outbound calls |
| `RETRY_STRATEGY` | No | `EXPONENTIAL` | Retry backoff strategy (LINEAR, EXPONENTIAL, FIBONACCI) |
| `RETRY_WAIT_MULTIPLIER` | No | `1.0` | Retry wait multiplier |
| `RETRY_WAIT_MAX_SEC` | No | `10` | Maximum retry wait in seconds |
| `LOG_LEVEL` | No | `INFO` | Logging level |
| `MYSQL_HOST` | No | `localhost` | MySQL host for orchestrator-owned tables |
| `MYSQL_PORT` | No | `3306` | MySQL port |
| `MYSQL_DB` | No | `pmos` | MySQL database name |
| `MYSQL_USER` | No | `root` | MySQL username |
| `MYSQL_PASSWORD` | Yes | _(none)_ | MySQL password |

## Running

### Development

```bash
# Install dependencies
pip install -r requirements.txt

# Start the service
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Docker

```bash
docker build -t pmos-orchestrator .
docker run -p 8000:8000 --env-file .env pmos-orchestrator
```

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=app --cov-report=term-missing

# Run unit tests only
pytest tests/unit/ -v

# Run integration tests only
pytest tests/integration/ -v
```
