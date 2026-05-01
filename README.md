# PMOS — Perpetual Multi-Agent Orchestration System

A self-extending AI orchestration platform that connects structured and unstructured data sources through collaborative agents for instant cross-domain analytics.

## What It Does

Ask a single natural language question that spans multiple data sources — SQL databases, graph stores, uploaded documents, APIs, and code repositories — and get a synthesized analytical report. The system automatically decomposes the question, selects specialized agents via competitive bidding, executes tools in parallel, self-corrects when quality drops, and learns from every execution.

## Key Features

- **Multi-Agent Orchestration** — Agents negotiate capabilities, bid on tasks, and coordinate via an orchestrator
- **Perpetual Agentic Loop** — Sufficiency-judged outer loop that re-decomposes mid-flight when gaps remain, with a per-conversation blackboard so siblings see each other's findings, real auto-correct re-prompting on below-band scores, score-plateau / token-budget termination, durable learning artifacts, and user-feedback carry-over between turns
- **Recursive Sub-Agent Spawning** — Agents delegate complex sub-tasks to specialists (max depth 3)
- **7 Tool Types** — DATABASE (MySQL), GRAPH (Neo4j), API, GITHUB, PYTHON (sandbox), WEBSERVICE, FILE
- **RAG Pipeline** — Upload PDF, DOCX, XLSX, HTML, CSV, JSON, MD → chunk → embed → Qdrant vector store
- **4-Tier Memory** — Short-term (Redis), Long-term, Reasoning, Episodic (MySQL + FAISS)
- **Adaptive Scoring** — RL weight updates via Q-learning with adaptive quality bands; optional learned-scorer LIVE blend behind a config weight (`SCORING_WEIGHT_W7_LEARNED`) and contextual-bandit LIVE selection behind a flag (`BANDIT_LIVE_SELECTION`)
- **Self-Extending** — Meta-assembly detects capability gaps and generates new tools/agents
- **Full Audit Trail** — Every agent interaction, bid, tool call logged in Neo4j graph; live SSE stream + `pipeline_events` MySQL replay drives the **Decomposition Timeline** UI at `/conversations/:id/timeline`

## Architecture

```
User → React Frontend (3000) → Gateway (4000) → Orchestrator (8000)
         │                        │ auth, rate-limit
         │                        ↓
         │                   10-Step Pipeline:
         │                   Decompose → Negotiate → Execute → Score → Learn
         │                        │
         │              ┌─────────┼──────────┬──────────┬──────────┐
         │              ↓         ↓          ↓          ↓          ↓
         │         Agent-Mgmt  Memory      RAG      Scoring   Meta-Assembly
         │          (4001)    (8001)     (8002)     (8003)      (8004)
         │              │         │          │          │
         │              ↓         ↓          ↓          ↓
         │           MySQL    Redis+FAISS  Qdrant    Redis Streams
         │           Neo4j
```

## Quick Start

```bash
# Prerequisites: Docker Desktop, MySQL 8.0, Node.js 20+

# 1. Clone and configure
cp .env.example .env  # fill in OPENAI_API_KEY, MYSQL_PASSWORD, NEO4J_PASSWORD

# 2. Start everything (one-shot fresh-server install)
./scripts/deploy.sh install   # Redis, Qdrant, 7 services, dockerized client

# Day-to-day:
./scripts/deploy.sh up        # start everything
./scripts/deploy.sh down      # stop everything
./scripts/deploy.sh status    # health + container status

# 3. Open
open http://localhost:3000
```

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for the full deployment guide,
per-component commands (`up gateway`, `restart rag`, `logs orchestrator`, etc.),
and production hardening checklist.

## Enabling the Perpetual Agentic Loop

The team-level outer loop (sufficiency judge → delta re-decompose →
re-execute → re-aggregate, capped at 3 rounds), per-conversation
blackboard, real auto-correct retry, score-plateau termination,
sub-agent token/spawn budget, durable learning artifacts, and the live
Decomposition Timeline UI are **always on** — no flags needed. Open any
conversation at `/conversations/:id/timeline` to watch the team work.

Two ML-driven decision points are gated behind flags so operators can
flip them on once they have enough data:

```bash
# .env (or compose env override)
BANDIT_LIVE_SELECTION=true        # bandit pick can override the bid winner
SCORING_WEIGHT_W7_LEARNED=0.2     # blend the learned scorer at w7 into the live score
```

Both default OFF and have built-in safeguards (the bandit auto-downgrades
to FALLBACK when an arm has < 20 historical pulls; the learned-scorer
blend is `(1 - w7) × heuristic + w7 × learned` and is no-op at w7=0). See
[docs/ML_OPS.md](docs/ML_OPS.md) for the full rollout playbook,
ml.rationale event schema, and tuning notes.

## Documentation

See [`docs/`](docs/) for detailed documentation:
- [Architecture](docs/ARCHITECTURE.md) — Pipeline flow, negotiation, sub-agents, scoring
- [Services](docs/SERVICES.md) — All 7 services with endpoints and ownership
- [Data](docs/DATA.md) — MySQL (23 tables), Neo4j graph, Redis streams
- [Frontend](docs/FRONTEND.md) — React pages, API hooks, components
- [Agents](docs/AGENTS.md) — Agent/tool/team system, creation guide
- [Conventions](docs/CONVENTIONS.md) — Naming, logging, testing patterns
- [ML Ops](docs/ML_OPS.md) — Bandit, learned scorer, perpetual-loop ML rollout

## Tech Stack

**Frontend:** React 18, TypeScript, Vite, Material UI, D3.js, React Query
**Backend:** Python 3.11 (FastAPI), Node.js 20 (Express 5), TypeScript
**Data:** MySQL 8.0, Neo4j AuraDB, Qdrant, Redis 7, FAISS
**AI/ML:** OpenAI GPT-4o, sentence-transformers, cross-encoder re-ranking, Q-learning RL
**Infra:** Docker Compose, Prometheus, structured JSON logging

## License

MIT
