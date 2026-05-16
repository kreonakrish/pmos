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
| translator | Python 3.11, FastAPI, Neo4j, Qdrant | 8005 | pmos-translator | Ontology-grounded NL→domain translation, intent extraction |

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

**Financial Governance (FinOps) endpoints** — token-cost reporting across every LLM call (orchestrator / translator / meta-assembly), all sourced from `pmos.llm_call_log`. Backs the **Financial Governance** frontend page:
- `GET /v1/finops/summary?period=24h|7d|30d|all` — KPI strip + daily trend + top breakdowns
- `GET /v1/finops/breakdown?group_by=service|team|agent|model|conversation|user` — drill-down aggregator
- `GET /v1/finops/conversations` — top conversations by cost
- `GET /v1/finops/conversations/:id` — per-LLM-call timeline for one conversation
- `GET/POST/PUT /v1/finops/pricing` — editable per-MTok `model_pricing` rates
- `GET /v1/finops/whatif?agent_id=&candidate_model=` — projected savings on an agent model swap

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

---

## Translator (port 8005)

**Owns:** Ontology-grounded natural-language translation. Converts a raw user question into a structured, domain-aware decomposition the orchestrator can route — extracts intent, resolves canonical entities, binds them to datasets, and emits per-domain subtasks. The orchestrator calls this *before* decomposition via `TranslatorAdapter`; any failure degrades gracefully to the bare decomposition prompt (`fallback_used=true`).

**Key endpoints:**
- `POST /v1/translate` — translate an NL question. Returns `{intent, domain, canonical_entities, relationships, dataset_bindings, domain_subtasks, used_ontology_subgraph, ontology_versions, matched_reports, clarification_needed, schema_meta_column, fallback_used}`
- `POST /v1/translator/examples` — promote a vetted translation into the `translation_examples` Qdrant collection (few-shot retrieval corpus)
- `GET /health` — Neo4j + Qdrant + LLM readiness

**Consumes:** Ontology Neo4j (business ontology graph — `BusinessAttribute -MAPS_TO-> DataColumn -> DataAsset`), Qdrant (`translation_examples` few-shot collection), an LLM provider.

**Notes:** Multi-turn clarification supported via `prior_turns`. Internal LLM calls are attributed to `pmos.llm_call_log` for Financial Governance (orchestrator forwards `user_id`/`conversation_id`/`team_id` on the request body).
