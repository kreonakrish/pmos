# SERVICES.md — Backend Service Reference

## Service Map

| Service | Stack | Port | Docker Image | Purpose |
|---------|-------|------|-------------|---------|
| gateway | Node.js 20, Express 5, TypeScript | 4000 | pmos-gateway | Auth, rate-limit, routing, WebSocket |
| agent-mgmt | Node.js 20, Express 5, TypeScript, mysql2 | 4001 | pmos-agent-mgmt | Agent/Tool/Team CRUD, tool execution, health checks |
| orchestrator | Python 3.11, FastAPI, neo4j-driver | 8000 | pmos-orchestrator | Pipeline execution, graph management, negotiation |
| memory | Python 3.11, FastAPI, FAISS, Redis | 8001 | pmos-memory | 4-tier memory, prompt assembly, distillation |
| rag | Python 3.11, FastAPI, Qdrant, FAISS | 8002 | pmos-rag | Document ingestion, chunking, retrieval, re-ranking |
| scoring | Python 3.11, FastAPI, numpy | 8003 | pmos-scoring | Score computation, adaptive bands, RL weight updates |
| meta-assembly | Python 3.11, FastAPI, openai | 8004 | pmos-meta-assembly | Gap detection, spec generation, sandbox execution |

## Backing Services

| Service | Port | Container | Notes |
|---------|------|-----------|-------|
| MySQL 8.0 | 3306 | Host-installed | Database: pmos |
| Redis 7 | 6379 | pmos_redis | Streams + rate limiting |
| Qdrant | 6333 | pmos_qdrant | Vector store for RAG |
| Neo4j AuraDB | Cloud | N/A | neo4j+s://8414810d.databases.neo4j.io |

---

## Gateway (port 4000)

**Owns:** Inbound HTTP, JWT auth (`POST /v1/auth/login`, password: `pmos2024`), rate limiting, request routing, WebSocket streaming.

**Key endpoints:**
- `POST /v1/auth/login` — returns JWT token
- `GET /health` — aggregated health from all services
- All `/v1/*` routes proxied to downstream services
- WebSocket at `/ws` for streaming responses

**Does NOT own:** Business logic, DB access, LLM calls.

---

## Agent-Mgmt (port 4001)

**Owns:** CRUD for agents, tools, teams. Tool execution dispatch. Tool health scheduling.

**Key endpoints:**
- `GET/POST /v1/agents` — agent CRUD
- `GET/POST /v1/tools` — tool CRUD
- `POST /v1/tools/test` — execute any tool (DATABASE, API, GITHUB, PYTHON, WEBSERVICE, GRAPH)
- `GET/POST /v1/teams` — team CRUD
- `POST /v1/teams/:id/agents` — add agent to team
- `GET /v1/agents/:id/tools` — list agent's tools
- `POST /v1/agents/:id/tools` — assign tool to agent

**Tool types supported:** DATABASE (MySQL), GRAPH (Neo4j), API (HTTP), GITHUB, PYTHON (sandbox), WEBSERVICE, FILE, VECTOR

**MySQL tables owned:** agents, tools, teams, team_agents, agent_tools, tool_execution_history, capability_registry (reads)

---

## Orchestrator (port 8000)

**Owns:** The 10-step execution pipeline, Neo4j graph, capability negotiation, sub-agent spawning, interaction logging.

**Key endpoints:**
- `POST /v1/orchestrator/conversations/:id/messages` — trigger pipeline
- `GET /v1/orchestrator/conversations/:id/decomposition` — task graph DAG
- `GET /v1/orchestrator/conversations/:id/interactions` — agent interactions
- `POST /v1/sandbox/agent-execute` — agentic tool-use loop
- `GET /v1/jobs` — pipeline execution history
- `GET /v1/graph/tasks` — all task nodes

**Neo4j nodes owned:** TaskGraph, TaskNode, ExecutionEvent, AgentInteraction, AgentCapabilityNode, SOPNode
**MySQL tables owned:** conversations, messages, task_assignments, execution_graph_log, agent_interactions

---

## Memory (port 8001)

**Owns:** 4-tier memory (SHORT_TERM, LONG_TERM, REASONING, EPISODIC), prompt assembly, distillation.

**Key endpoints:**
- `POST /v1/memory/assemble-prompt` — build system prompt from all 4 tiers
- `POST /v1/memory/write` — write to any tier
- `GET /v1/memory/retrieve` — semantic search across tiers

**Consumes:** `memory:writes` Redis stream (from orchestrator)
**MySQL tables owned:** agent_memory_extended, execution_episodes

---

## RAG (port 8002)

**Owns:** Document ingestion, chunking, embedding, multi-source retrieval, re-ranking.

**Key endpoints:**
- `POST /v1/rag/ingest` — chunk + embed + store document
- `POST /v1/rag/query` — parallel retrieval from Qdrant + FAISS + MySQL + memory
- `GET /v1/rag/documents` — list ingested documents
- `DELETE /v1/rag/documents/:id` — remove document

**Consumes:** `events:documents` Redis stream (from gateway)
**Vector stores:** Qdrant (primary), FAISS (backup)
**MySQL tables owned:** rag_documents, rag_chunks

---

## Scoring (port 8003)

**Owns:** Score computation, adaptive bands, RL weight updates.

**Key endpoints:**
- `POST /v1/scoring/evaluate` — compute score for execution
- `POST /v1/scoring/band` — get current band for agent + context
- `GET /v1/scoring/history/:agent_id` — score history with rolling bands
- `GET /v1/scoring/weights/:agent_id` — current weight vector
- `POST /v1/scoring/feedback` — submit feedback signal

**Produces + consumes:** `scoring:feedback` Redis stream
**MySQL tables owned:** scoring_weights, rl_feedback_log, score_history

---

## Meta-Assembly (port 8004)

**Owns:** Capability gap detection, LLM-driven spec generation, sandbox validation.

**Key endpoints:**
- `POST /v1/meta/detect-gap` — analyze failed tasks for missing capabilities
- `POST /v1/meta/generate-spec` — LLM generates tool/skill/agent spec
- `POST /v1/meta/register` — validate and register new capability

**Produces:** `events:capability_added` Redis stream
**Safety:** All generated code runs in isolated subprocess with timeout + memory limits
