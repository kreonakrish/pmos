# PMOS Redis Stream Definitions

All streams use Redis Streams (XADD/XREAD/XREADGROUP).
All messages MUST include: `trace_id`, `source_service`, `timestamp`, `schema_version: "1"`.

## Stream Registry

| Stream Name | Producer | Consumer(s) | Purpose |
|---|---|---|---|
| `orchestrator:tasks` | orchestrator | orchestrator workers | Internal task dispatch queue |
| `memory:writes` | orchestrator | memory service | Async memory persistence (fire-and-forget) |
| `scoring:feedback` | scoring service | scoring RL engine | RL weight update queue |
| `events:telemetry` | all services | observability collector | Structured event log for all services |
| `events:tool_health` | agent-mgmt | orchestrator | Tool availability state changes |
| `events:capability_added` | meta-assembly | orchestrator, agent-mgmt | New dynamic capability available |
| `events:documents` | gateway | rag service | Document ingestion trigger |

---

## Message Schemas

### `orchestrator:tasks`

```json
{
  "schema_version": "1",
  "trace_id": "uuid-v4",
  "source_service": "orchestrator",
  "timestamp": "2026-01-01T00:00:00Z",
  "task_id": "uuid-v4",
  "session_id": "uuid-v4",
  "conversation_id": "uuid-v4",
  "user_request": "string",
  "team_id": "uuid-v4",
  "priority": "LOW | MEDIUM | HIGH | CRITICAL"
}
```

**Consumer group:** `orchestrator-workers`
**Max stream length:** 10,000 entries (MAXLEN ~)
**Retention:** Messages ACK'd after processing; unacknowledged entries re-delivered after 30s (XCLAIM)

---

### `memory:writes`

```json
{
  "schema_version": "1",
  "trace_id": "uuid-v4",
  "source_service": "orchestrator",
  "timestamp": "2026-01-01T00:00:00Z",
  "agent_id": 42,
  "tier": "short_term | long_term | episodic",
  "content": "string content to store",
  "metadata": {
    "task_id": "uuid-v4",
    "session_id": "uuid-v4",
    "importance": 0.75
  }
}
```

**Consumer group:** `memory-service`
**Processing:** At-least-once; idempotent writes via content_hash deduplication
**Max stream length:** 50,000 entries

---

### `scoring:feedback`

```json
{
  "schema_version": "1",
  "trace_id": "uuid-v4",
  "source_service": "scoring",
  "timestamp": "2026-01-01T00:00:00Z",
  "agent_id": 42,
  "task_id": "uuid-v4",
  "session_id": "uuid-v4",
  "feedback_source": "AUTOMATED | USER | INTER_AGENT | ORCHESTRATOR",
  "feedback_type": "SCORE | CORRECTION | BAND_ADJUST | RETRY | FALLBACK | AUTOCORRECT",
  "score": 0.85,
  "reward_signal": 0.1,
  "context_type": "string"
}
```

**Consumer group:** `rl-engine`
**Processing:** Ordered; RL weight updates are stateful — must process in order per agent_id
**Max stream length:** 100,000 entries

---

### `events:telemetry`

```json
{
  "schema_version": "1",
  "trace_id": "uuid-v4",
  "span_id": "uuid-v4",
  "source_service": "gateway | orchestrator | memory | rag | scoring | agent-mgmt | meta-assembly",
  "timestamp": "2026-01-01T00:00:00Z",
  "event_type": "string",
  "layer": "router | service | adapter | model",
  "duration_ms": 123,
  "status": "success | error",
  "metadata": {}
}
```

**Consumer group:** `telemetry-collector`
**Processing:** Best-effort; dropped messages acceptable
**Max stream length:** 500,000 entries (MAXLEN ~)

---

### `events:tool_health`

```json
{
  "schema_version": "1",
  "trace_id": "uuid-v4",
  "source_service": "agent-mgmt",
  "timestamp": "2026-01-01T00:00:00Z",
  "tool_id": "uuid-v4",
  "tool_name": "string",
  "previous_status": "ACTIVE | DEGRADED | OFFLINE",
  "current_status": "ACTIVE | DEGRADED | OFFLINE",
  "avg_latency_ms": 45.2,
  "success_rate": 0.98
}
```

**Consumer group:** `orchestrator-health-listener`
**Processing:** At-least-once; triggers agent fallback reassignment on DEGRADED/OFFLINE
**Max stream length:** 10,000 entries

---

### `events:capability_added`

```json
{
  "schema_version": "1",
  "trace_id": "uuid-v4",
  "source_service": "meta-assembly",
  "timestamp": "2026-01-01T00:00:00Z",
  "capability_id": "uuid-v4",
  "capability_type": "TOOL | SKILL | AGENT",
  "capability_name": "string",
  "gap_id": "uuid-v4",
  "validation_score": 0.87,
  "neo4j_node_id": "string"
}
```

**Consumer groups:** `orchestrator-capability-listener`, `agent-mgmt-capability-listener`
**Processing:** At-least-once; triggers Neo4j graph update and agent capability refresh
**Max stream length:** 5,000 entries

---

### `events:documents`

```json
{
  "schema_version": "1",
  "trace_id": "uuid-v4",
  "source_service": "gateway",
  "timestamp": "2026-01-01T00:00:00Z",
  "document_id": "uuid-v4",
  "filename": "string",
  "mime_type": "string",
  "storage_path": "string",
  "team_id": "uuid-v4",
  "agent_id": 42,
  "ingest_options": {
    "chunk_size": 500,
    "chunk_overlap": 50,
    "targets": ["faiss", "qdrant", "mysql"]
  }
}
```

**Consumer group:** `rag-ingestor`
**Processing:** At-least-once; idempotent via document_id
**Max stream length:** 20,000 entries

---

## Configuration

```
# In .env
REDIS_STREAM_MAX_LEN=10000          # default MAXLEN for all streams
REDIS_URL=redis://redis:6379
REDIS_MAX_CONNECTIONS=100
```

## Consumer Group Bootstrap

The `bootstrap.sh` script creates all consumer groups:

```bash
redis-cli XGROUP CREATE orchestrator:tasks orchestrator-workers $ MKSTREAM
redis-cli XGROUP CREATE memory:writes memory-service $ MKSTREAM
redis-cli XGROUP CREATE scoring:feedback rl-engine $ MKSTREAM
redis-cli XGROUP CREATE events:telemetry telemetry-collector $ MKSTREAM
redis-cli XGROUP CREATE events:tool_health orchestrator-health-listener $ MKSTREAM
redis-cli XGROUP CREATE events:capability_added orchestrator-capability-listener $ MKSTREAM
redis-cli XGROUP CREATE events:capability_added agent-mgmt-capability-listener $ MKSTREAM
redis-cli XGROUP CREATE events:documents rag-ingestor $ MKSTREAM
```
