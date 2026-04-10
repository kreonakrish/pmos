# ARCHITECTURE.md — System Design & Execution Pipeline

## How a User Question Gets Solved

```
User types message in React frontend (port 3000)
  → Gateway (4000): auth, rate-limit, inject trace_id
    → Orchestrator (8000): 10-step pipeline
      → Step 0: Load team hierarchy from agent-mgmt into Neo4j
      → Step 1-2: LLM decomposes question into TaskGraph (Neo4j)
      → Step 3: Capability negotiation — agents bid in parallel
      → Step 4-7: Agentic tool-use loop per task node
        → Tool calls: DATABASE, GRAPH, API, GITHUB, PYTHON
        → spawn_sub_agent: recursive sub-agent delegation
        → Scoring → adaptive band check → fallback if needed
      → Step 8: Aggregate sub-task results via LLM
      → Step 9: Memory write (episodic) + RL feedback
      → Step 10: Return synthesized response
    → Gateway → Frontend
```

## Capability Negotiation (Step 3)

For each sub-task, the orchestrator broadcasts a bid request to all team specialists:

1. Each agent's LLM self-assesses using its tools + memory context
2. Returns `{confidence: 0.0-1.0, reasoning, eligible}`
3. Bids ranked: `0.6 × confidence + 0.25 × memory_relevance + 0.15 × latency_score`
4. Winner assigned to TaskNode; others form fallback chain
5. All bids persisted as ExecutionEvent nodes in Neo4j

## Agentic Tool-Use Loop (Steps 4-7)

Each agent runs inside a sandbox execution loop:

```
LOOP (max 5 iterations):
  1. LLM sees: system_prompt + task + tools (including spawn_sub_agent)
  2. LLM responds:
     ├── Text → done, return response
     ├── Tool call(s) → execute each, feed results back as tool_result
     └── spawn_sub_agent → negotiate specialist, recurse (max depth 3)
  3. Continue until text response or max iterations
  If response truncated → auto-continue (up to 3x)
```

## Sub-Agent Spawning (Recursive)

When an agent calls `spawn_sub_agent`:
- Creates `SUB_AGENT` TaskNode in Neo4j with `SPAWNED_BY` relationship
- Runs capability negotiation among team specialists
- Winner gets own memory context, own tools, own agentic loop
- Result returned to parent as tool_result
- Depth limit configurable (`max_sub_agent_depth`, default 3)

## Scoring & Course Correction

After each execution:
- Scoring service computes: `S = w1·Relevance + w2·Accuracy + w3·Precision + w4·Latency + w5·Confidence + w6·Knowledge`
- Compared against adaptive band: `rolling_mean ± (rolling_std × sensitivity)`
- If within band → SUCCESS
- If below band → escalate to next fallback agent
- If all fallbacks exhausted → meta-assembly gap detection

## Memory Tiers

| Tier | Storage | TTL | Purpose |
|------|---------|-----|---------|
| SHORT_TERM | Redis hash | Configurable | Current session context |
| LONG_TERM | MySQL + FAISS | Permanent | Persistent knowledge |
| REASONING | MySQL JSON | Permanent | Distilled patterns |
| EPISODIC | MySQL + FAISS | Permanent | Full execution episodes |

Memory is assembled at runtime into every agent's system prompt before execution.

## RAG Pipeline

Documents uploaded via chat or Documents page:
1. Content chunked (fixed/sentence/paragraph strategy)
2. Embedded via sentence-transformers/all-mpnet-base-v2
3. Stored in Qdrant (primary) + FAISS (backup) + MySQL metadata
4. During pipeline execution, relevant chunks retrieved and injected into agent prompts

## RL Weight Updates

The scoring service runs a Q-learning engine:
- Consumes `scoring:feedback` Redis stream
- Updates per-agent weights: `w_new = w_old + α(reward - w_old)`
- Weights adapt over time based on automated, user, inter-agent, and orchestrator feedback
