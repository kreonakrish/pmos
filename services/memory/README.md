# Memory Service

4-tier memory architecture for the PMOS platform. Manages short-term (Redis), long-term (MySQL + FAISS), reasoning (distilled patterns), and episodic (full execution episodes) memory for all agents. Assembles dynamic system prompts at runtime from retrieved memory content across all tiers.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/memory/write` | Write content to a specified memory tier |
| `GET` | `/v1/memory/retrieve` | Retrieve memories from a tier (semantic search for long_term/reasoning/episodic) |
| `POST` | `/v1/memory/assemble-prompt` | Assemble a dynamic system prompt from all requested memory tiers |
| `GET` | `/health` | Service health check (includes Redis and MySQL connectivity) |
| `GET` | `/metrics` | Prometheus metrics endpoint |

### POST /v1/memory/write

```json
{
  "agent_id": 1,
  "tier": "short_term",
  "content": "User prefers concise answers",
  "metadata": {"session_id": "abc-123", "importance": 0.8}
}
```

### GET /v1/memory/retrieve

Query parameters: `agent_id` (required), `tier` (required), `query` (required for long_term/reasoning/episodic), `k` (default 5).

### POST /v1/memory/assemble-prompt

```json
{
  "agent_id": 1,
  "context": {"task_type": "analysis", "domain": "finance", "recent_messages": ["analyze Q4"]},
  "tiers": ["short_term", "long_term", "reasoning", "episodic"]
}
```

Returns assembled `system_prompt` string and `sources` hit counts per tier.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MEMORY_PORT` | `8001` | Service listen port |
| `REDIS_URL` | `redis://localhost:6379` | Redis connection URL |
| `MYSQL_HOST` | `localhost` | MySQL hostname |
| `MYSQL_PORT` | `3306` | MySQL port |
| `MYSQL_DB` | `pmos` | MySQL database name |
| `MYSQL_USER` | `root` | MySQL username |
| `MYSQL_PASSWORD` | *(required)* | MySQL password |
| `FAISS_INDEX_PATH` | `/data/faiss` | Directory for per-agent FAISS index shards |
| `SHORT_TERM_TTL_SEC` | `3600` | TTL for short-term Redis entries (seconds) |
| `DISTILLATION_INTERVAL_MIN` | `30` | Interval for distillation background job (minutes) |
| `DISTILLATION_FREQUENCY_THRESHOLD` | `3` | Min access count to promote short-term to long-term |
| `EMBEDDING_MODEL` | `sentence-transformers/all-mpnet-base-v2` | Embedding model name |
| `LOG_LEVEL` | `INFO` | Logging level |
| `RETRY_MAX_ATTEMPTS` | `3` | Max retry attempts for outbound calls |

## Running Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Start the service
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

## Running with Docker

```bash
docker build -t pmos-memory .
docker run -p 8001:8001 --env-file .env pmos-memory
```

## Running Tests

```bash
# All tests
pytest tests/ -v

# Unit tests only
pytest tests/unit/ -v

# Adapter tests only
pytest tests/adapters/ -v

# With coverage
pytest tests/ --cov=app --cov-report=term-missing
```
