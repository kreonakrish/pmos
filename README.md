# PMOS — Perpetual Multi-Agent Orchestration System

A self-extending AI orchestration platform that connects structured and unstructured data sources through collaborative agents for instant cross-domain analytics.

## What It Does

Ask a single natural language question that spans multiple data sources — SQL databases, graph stores, uploaded documents, APIs, and code repositories — and get a synthesized analytical report. The system automatically decomposes the question, selects specialized agents via competitive bidding, executes tools in parallel, self-corrects when quality drops, and learns from every execution.

## Key Features

- **Multi-Agent Orchestration** — Agents negotiate capabilities, bid on tasks, and coordinate via an orchestrator
- **Recursive Sub-Agent Spawning** — Agents delegate complex sub-tasks to specialists (max depth 3)
- **7 Tool Types** — DATABASE (MySQL), GRAPH (Neo4j), API, GITHUB, PYTHON (sandbox), WEBSERVICE, FILE
- **RAG Pipeline** — Upload PDF, DOCX, XLSX, HTML, CSV, JSON, MD → chunk → embed → Qdrant vector store
- **4-Tier Memory** — Short-term (Redis), Long-term, Reasoning, Episodic (MySQL + FAISS)
- **Adaptive Scoring** — RL weight updates via Q-learning with adaptive quality bands
- **Self-Extending** — Meta-assembly detects capability gaps and generates new tools/agents
- **Full Audit Trail** — Every agent interaction, bid, tool call logged in Neo4j graph

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

## Documentation

See [`docs/`](docs/) for detailed documentation:
- [Architecture](docs/ARCHITECTURE.md) — Pipeline flow, negotiation, sub-agents, scoring
- [Services](docs/SERVICES.md) — All 7 services with endpoints and ownership
- [Data](docs/DATA.md) — MySQL (23 tables), Neo4j graph, Redis streams
- [Frontend](docs/FRONTEND.md) — React pages, API hooks, components
- [Agents](docs/AGENTS.md) — Agent/tool/team system, creation guide
- [Conventions](docs/CONVENTIONS.md) — Naming, logging, testing patterns

## Tech Stack

**Frontend:** React 18, TypeScript, Vite, Material UI, D3.js, React Query
**Backend:** Python 3.11 (FastAPI), Node.js 20 (Express 5), TypeScript
**Data:** MySQL 8.0, Neo4j AuraDB, Qdrant, Redis 7, FAISS
**AI/ML:** OpenAI GPT-4o, sentence-transformers, cross-encoder re-ranking, Q-learning RL
**Infra:** Docker Compose, Prometheus, structured JSON logging

## License

MIT
