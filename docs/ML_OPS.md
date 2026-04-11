# ML_OPS.md — Governance & ML Insights Reference

> Covers the two "Govern" section UI pages (Model Governance and ML Insights),
> their backing endpoints, MySQL tables, pipeline hooks, and offline scripts.
> All of this was added in branch `feat/ml-ops-and-governance`.

## Quick Start

Open `http://localhost:3000`, log in as `admin / pmos2024`, then in the
sidebar under **Govern**:

- **Model Governance** (`/model-governance`) — per-trace reasoning chain
- **ML Insights** (`/ml-insights`) — bandit state, graph embeddings, learned
  scorer, SOP discovery (4 tabs)

## Model Governance — inference traceability

### Purpose
For any answer the system produced, show the full layered hop-by-hop chain:
user request → bid/negotiation → task nodes → tool calls → scoring decisions
→ RL feedback → final response. It is the diagnostic instrument used when an
answer looks wrong or unexpectedly right.

### UI page
`client/src/pages/ModelGovernance/index.tsx`
- Left rail: recent traces with search + paste-trace-id box
- Right pane: summary banner + color-coded timeline with expandable hops
- Accepts `?trace=<uuid>` query param for deep-links (used by ML Insights)

### API
All under `/v1/governance/*`, proxied through gateway with JWT auth.

| Endpoint | Returns |
|---|---|
| `GET /traces?limit=N` | Recent traces with summary stats |
| `GET /traces/{trace_id}` | Full reasoning chain (messages, pipeline steps, tool calls, scores, RL feedback, Neo4j TaskNodes, interactions, collapsed into one time-sorted timeline) |
| `GET /traces/by-conversation/{conversation_id}` | All trace_ids in a conversation |

### Backing data (read-only joins)
- `pmos.messages` — user/assistant content with `trace_id` and `score`
- `pmos.conversations` — user/team/title metadata
- `pmos.execution_graph_log` — per-node status, score, correction flags
- `pmos.tool_execution_history` — joined to `pmos.tools` for tool name/description
- `pmos.score_history` + `pmos.agents` — scoring decisions with factor breakdown
- `pmos.rl_feedback_log` — RL adjustments and rewards
- `pmos.execution_episodes` — episodic memory snapshots
- Neo4j: `TaskGraph`, `TaskNode` (with edges), `AgentInteraction`

### Key file
- `services/orchestrator/app/routes/governance.py` — assembly + timeline ordering
- `services/gateway/app/routes/orchestrator.ts` — proxy routes

### Known convention
Neo4j `datetime` values must be coerced to strings via `_serialize_neo4j()`
before returning through FastAPI — Pydantic cannot serialize `neo4j.time.DateTime`.
The governance endpoint and the fixed `/v1/orchestrator/sops` endpoint both
use this pattern.

---

## ML Insights — the learning loop

`client/src/pages/MLInsights/index.tsx` renders four tabs, each backed by
its own `/v1/ml/*` endpoints. Only Node2Vec runs "live" (read-only features);
the other three loops are in SHADOW / human-in-loop mode until the operator
explicitly promotes them.

### Tab 1 — Contextual Bandits (1A)

| Item | Details |
|---|---|
| Algorithm | Thompson Sampling over Beta(α, β) per `(agent, context_bucket)` |
| Context bucket | `team:{team_id}\|type:{task_type}` |
| Prior | Beta(7, 5) — operator-chosen 60% baseline (`PRIOR_MEAN=0.6, PRIOR_STRENGTH=10`) |
| Mode | SHADOW — decisions logged but do not override the bid winner |
| Min pulls for LIVE | 20 per arm |
| Forced exploration | 10% of decisions |

Implementation:
- `services/orchestrator/app/services/bandit_selector.py` — core module
- Hooked into `pipeline.py:_step3_negotiate` — calls `select(..., mode="SHADOW")`
  after each bid; `record_reward(decision_id, score)` in the post-execution loop.
- Pure Python (no numpy in the orchestrator container). Uses
  `random.betavariate` for sampling.

Tables:
- `pmos.bandit_agent_state` — one row per `(agent_id, context_bucket)` with
  `alpha`, `beta`, `pulls`, `total_reward`
- `pmos.bandit_decisions` — decision log with `mode`, `selected_agent_id`,
  `bandit_pick_agent_id`, `reward`, `trace_id`

Endpoints:
- `GET /v1/ml/bandits/summary` — aggregate stats + per-context readiness
- `GET /v1/ml/bandits/state` — per-arm state with posterior mean + 95% CI
- `GET /v1/ml/bandits/decisions` — decision log (supports `mode=`, `disagreements_only=`)
- `GET /v1/ml/bandits/convergence?agent_id=&context_bucket=` — time series of posterior mean

**Flip to LIVE**: when `MIN(pulls) >= 20` across all arms in a bucket,
change `mode="SHADOW"` to `mode="LIVE"` in
`pipeline.py:_step3_negotiate`. The module already downgrades any under-pulled
arm to FALLBACK, so live mode is safe.

### Tab 2 — Graph Embeddings (2C)

| Item | Details |
|---|---|
| Algorithm | Real Node2Vec via `networkx` + `gensim` (installed in host Python for the batch script) |
| Fallback | Dependency-free Laplacian eigenmaps via pure numpy — same script, `--algorithm spectral` |
| Dimensions | 128 default (64 used in first run — small graph) |
| Cadence | Manual for now; recommend nightly cron/Task Scheduler/k8s CronJob |
| Source graph | Neo4j `TaskNode` with edges `DEPENDS_ON / SPAWNED_BY / EXECUTED_BY / PART_OF` |

Script: `scripts/compute_node2vec.py`
- Pulls nodes/edges from Neo4j, runs Node2Vec, writes to `pmos.task_node_embeddings`
- Run: `python scripts/compute_node2vec.py --dim 128 --walks 10 --length 40`

Table: `pmos.task_node_embeddings` — `(node_id, graph_id, node_type, dim, algorithm, embedding JSON, computed_at)`

Endpoints:
- `GET /v1/ml/embeddings/summary` — total, dim, algorithm, last refresh, by-type breakdown
- `GET /v1/ml/embeddings/projection?limit=500` — 2D PCA coordinates (pure-Python power iteration in `ml_insights.py:_pca_2d`)
- `GET /v1/ml/embeddings/similar?node_id=&k=10` — cosine nearest neighbors

### Tab 3 — Learned Quality Scorer (1B)

| Item | Details |
|---|---|
| Algorithm | Logistic regression trained offline with sklearn |
| Features | 15 numeric (heuristic score, response shape, latency, tool-call count, agent rolling avg, markdown/table/code flags, refusal detection, graph depth) |
| Labels | Real thumbs-up/down from `rl_feedback_log` upweighted 5×, plus synthetic bootstrap from `messages.score >= 0.65` (tuned so ~60% land positive) |
| Inference | Pure Python `sigmoid(standardize(x) · w + b)` — no numpy/sklearn in the container |
| Weight storage | Pickled to `infra/ml_models/learned_scorer_<version>.pkl`, mounted into orchestrator at `/app/models:ro` |
| Mode | SHADOW (`w7_learned_quality=0.0` in `scoring_weights`) |

Scripts:
- `scripts/train_learned_scorer.py` — offline training (sklearn). Run:
  `python scripts/train_learned_scorer.py`. Writes pickle + upserts
  metadata row in `pmos.learned_scorer_models`.

Runtime:
- `services/orchestrator/app/services/learned_scorer.py` — `LearnedScorer` class
  loaded at pipeline startup; `predict_and_log()` called once per node in the
  post-execution loop. Never blocks on failure.
- Feature contract in `extract_features()` must stay **byte-identical** with
  the one in the training script.

Tables:
- `pmos.learned_scorer_models` — versioned model metadata, `is_active` flag,
  train/val accuracy, val AUC, `weights_path`, feature names JSON
- `pmos.learned_scorer_predictions` — one row per scored node with
  `heuristic_score`, `learned_score`, `features` JSON, `trace_id`,
  and `user_feedback` (back-fillable from thumbs)

Endpoints:
- `GET /v1/ml/learned-scorer/summary` — active model, prediction aggregates,
  MAE vs heuristic, current `w7` weight
- `GET /v1/ml/learned-scorer/predictions?limit=100&labeled_only=` — prediction log

**Flip to LIVE**: `UPDATE pmos.scoring_weights SET parameter_value=0.1 WHERE parameter_name='w7_learned_quality'`
after the MAE-vs-heuristic and val-accuracy metrics look good on real labels.
The RL loop auto-adjusts from there.

### Tab 4 — SOP Auto-Discovery (2D)

| Item | Details |
|---|---|
| Algorithm | TF-IDF (uni + bigrams, 2000 features) + DBSCAN with cosine metric |
| Defaults | `eps=0.55` (cosine distance), `min_samples=3`, 90-day window |
| Promotion | Human-in-loop — operator clicks Promote, creates `SOPNode` in Neo4j |
| Cadence | Manual; recommend weekly |

Script: `scripts/discover_sops.py`
- Pulls recent user messages, clusters, builds per-cluster summary + keywords
  + best agent, writes PENDING rows to `pmos.sop_proposals`
- **Clears previous PENDING rows on each run** to avoid duplicates — PROMOTED
  and REJECTED rows are preserved.
- Run: `python scripts/discover_sops.py --window-days 90 --min-cluster 3`

Table: `pmos.sop_proposals` — `cluster_size`, `avg_score`, `best_agent_name`,
`summary`, `sample_messages` JSON, `keywords` JSON, `status`
(`PENDING/PROMOTED/REJECTED`), `promoted_sop_id`, review audit

Endpoints:
- `GET /v1/ml/sops/proposals?status=PENDING` — list proposals
- `POST /v1/ml/sops/proposals/{id}/promote` — creates `SOPNode` in Neo4j
  with `source='auto_discovery'`, updates MySQL row to PROMOTED
- `POST /v1/ml/sops/proposals/{id}/reject` — marks rejected

Promoted SOPs automatically feed back into `pipeline.py:_step1_intake`'s SOP
lookup — no additional wiring required.

---

## Pipeline hooks (where the loops tap in)

`services/orchestrator/app/services/pipeline.py`:

| Hook | Location | Purpose |
|---|---|---|
| Bandit shadow decision | `_step3_negotiate` after `neg_result` | One `bandit.select()` per subtask, logged |
| Bandit reward back-fill | `execute()` after `_step4_to_7_execution` | `record_reward(score)` per node |
| Learned scorer shadow | Same loop, right after bandit rewards | `predict_and_log()` per node using `llm_response` + metadata |

All hooks are non-blocking on failure — they log warnings and never raise
into the pipeline hot path.

---

## Conventions to preserve when extending

1. **SHADOW first.** Any new learning loop starts in shadow mode and only
   influences live decisions after an operator explicitly flips a weight or
   changes a mode string.
2. **60% baseline.** When introducing a new Beta-distributed metric, seed
   with `Beta(1 + 0.6*k, 1 + 0.4*k)` (typically `k=10`) to match the existing
   prior convention.
3. **Pure-Python inference.** The orchestrator container has no numpy,
   sklearn, or torch. Train offline in scripts, pickle lightweight weights
   (logistic regression, linear model, or small decision tree), and do
   inference in stdlib Python at runtime.
4. **Trace IDs everywhere.** Every new ML table should carry `trace_id` so
   it can be joined back to a governance trace for debugging.
5. **Human-in-loop for self-modification.** Anything that writes to Neo4j
   (SOPs, agent definitions, tool registry) goes through a pending-review
   table and an operator approval step.

---

## Key files

### Backend (Python)
- `services/orchestrator/app/routes/governance.py`
- `services/orchestrator/app/routes/ml_insights.py`
- `services/orchestrator/app/services/bandit_selector.py`
- `services/orchestrator/app/services/learned_scorer.py`
- `services/orchestrator/app/services/pipeline.py` — hooks in `execute()` and `_step3_negotiate()`
- `services/orchestrator/app/main.py` — router registration

### Backend (Node gateway)
- `services/gateway/app/routes/orchestrator.ts` — proxy routes for `/v1/governance/*` and `/v1/ml/*`

### Frontend (React)
- `client/src/pages/ModelGovernance/index.tsx`
- `client/src/pages/MLInsights/index.tsx`
- `client/src/api/governance.ts`
- `client/src/api/mlInsights.ts`
- `client/src/components/Layout/Sidebar.tsx` — "Govern" section entries
- `client/src/App.tsx` — `/model-governance` and `/ml-insights` routes

### Offline scripts
- `scripts/compute_node2vec.py`
- `scripts/train_learned_scorer.py`
- `scripts/discover_sops.py`
- `scripts/cross_system_query.py` — independent example of Neo4j ⋈ MySQL joins

### Schema
- `infra/mysql/ml_infra.sql` — tasks 1A + 2C tables
- `infra/mysql/ml_infra_1b_2d.sql` — tasks 1B + 2D tables + `w7_learned_quality` weight

### Model artifacts
- `infra/ml_models/learned_scorer_<version>.pkl` — mounted into orchestrator
  at `/app/models:ro` via `docker-compose.yml`

---

## Pending / deferred work (as of this doc)

- **Scheduling**: all three ML batch scripts (`compute_node2vec.py`,
  `train_learned_scorer.py`, `discover_sops.py`) are still manual. Needs
  host cron / Windows Task Scheduler / k8s CronJob wiring — deployment-dependent.
- **Flip 1A to LIVE** once any context bucket reaches `pulls >= 20`.
- **Flip 1B to LIVE** by raising `w7_learned_quality` in scoring_weights once
  MAE vs heuristic stabilizes and val accuracy on real feedback is good.
- **GNN-based scoring** as the ambitious successor to 1B — not started;
  would reuse Node2Vec features as input.
