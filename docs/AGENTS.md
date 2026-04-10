# AGENTS.md — Agent, Tool & Team System

## Current Agents

| Agent | ID | Model | Tools | Role |
|-------|----|-------|-------|------|
| SakilaAnalyst | 45259b12-... | gpt-4o | Sakila MySQL Tool (DATABASE) | Database analytics |
| HomeLendingAnalyst | 89b16647-... | gpt-4o | Home Lending Graph DB (GRAPH) | Neo4j Cypher queries |
| GitHubResearcher | f2dc13db-... | gpt-4o-mini | NFL Data GitHub Tool (GITHUB) | Code search |
| WebResearcher | 3ea45eff-... | gpt-4o-mini | Web Content Fetcher (WEBSERVICE) | Web data |
| PythonAnalyst | 97570662-... | gpt-4o-mini | Python Analysis Tool (PYTHON) | Custom analysis |
| WeatherExpert | 230472d5-... | gpt-4o | Open Meteo Weather API (API) | Weather data |

## Current Tools

| Tool | Type | Endpoint | Status |
|------|------|----------|--------|
| Sakila MySQL Tool | DATABASE | mysql://host.docker.internal:3306/sakila | ACTIVE |
| Home Lending Graph DB | GRAPH | neo4j+s://8414810d.databases.neo4j.io | ACTIVE |
| NFL Data GitHub Tool | GITHUB | https://api.github.com/search/repositories | ACTIVE |
| Python Analysis Tool | PYTHON | subprocess://sandbox | ACTIVE |
| Web Content Fetcher | WEBSERVICE | webservice://content-fetcher | DEGRADED |
| Open Meteo Weather API | API | https://api.open-meteo.com/v1/forecast | OFFLINE |

## Tool Types

| Type | Executor | What It Does |
|------|----------|-------------|
| DATABASE | mysql2 connection | Runs SQL queries against MySQL |
| GRAPH | neo4j-driver | Runs Cypher queries against Neo4j |
| API | axios HTTP client | Makes REST API calls with auth |
| GITHUB | GitHub API wrapper | Code search, file read, PR list |
| PYTHON | subprocess sandbox | Executes Python with timeout + resource limits |
| WEBSERVICE | HTTP client (like API) | Generic HTTP services |

Tool execution flow: LLM calls tool → sandbox POST to agent-mgmt `/v1/tools/test` → type-specific executor → result back to LLM.

## Current Teams

### MultiTool Research Team
- **ID:** 3e37a44b-622e-4802-a922-c42b716b3691
- **Agents:** All 6 agents
- **Purpose:** Original team, all-purpose

### Cross-Domain Research Team
- **ID:** 07207745-e9dc-4724-a307-5d2d9d25f321
- **Agents:** SakilaAnalyst (orchestrator), HomeLendingAnalyst, GitHubResearcher
- **Purpose:** Cross-domain queries combining Sakila DB + Neo4j graph + GitHub

## How Agents Are Selected

### Within a Team
1. **Hierarchy:** Agent with `role=orchestrator` becomes primary coordinator
2. **Specialists:** Remaining agents ordered by `priority ASC, accuracy_rate DESC`
3. **For each sub-task:** Capability negotiation (bidding) selects the best agent

### Capability Negotiation
1. Orchestrator broadcasts task description to all specialist agents
2. Each agent self-assesses (LLM call with its tools + memory context)
3. Returns `{confidence, reasoning, eligible}`
4. Ranked by: `0.6 × confidence + 0.25 × memory_hits + 0.15 × latency`
5. Winner + fallback chain written to Neo4j TaskNode

### Sub-Agent Spawning
Any agent can call `spawn_sub_agent` during its tool-use loop:
- System creates SUB_AGENT TaskNode with SPAWNED_BY link
- Runs capability negotiation to select specialist
- Sub-agent gets own context, tools, memory, agentic loop
- Can recursively spawn further sub-agents (max depth 3)
- Result returned as tool_result to parent

## Creating New Agents/Tools

### Via API
```bash
# Create tool
POST /v1/tools { name, description, tool_type, endpoint, auth_method, auth_config }

# Create agent
POST /v1/agents { name, description, role, foundation_model, status }

# Assign tool to agent
POST /v1/agents/:agent_id/tools { tool_id, permission }

# Add agent to team
POST /v1/teams/:team_id/agents { agent_id, role }
```

### Via UI
1. **Tool Studio** → Create tool, test it, verify
2. **Agent Studio** → Create agent, assign tools
3. **Team Studio** → Create team, add agents with roles

### Neo4j Sync
Agents and teams must also exist as nodes in Neo4j for the orchestrator to find them. The pipeline's `_load_team_hierarchy` method syncs from agent-mgmt, but for new agents you may need to manually create:
```cypher
CREATE (a:Agent {agent_id: "uuid", name: "Name", status: "IDLE", foundation_model: "gpt-4o"})
WITH a MATCH (t:Team {team_id: "team-uuid"}) CREATE (a)-[:MEMBER_OF {role: "specialist"}]->(t)
```

## Tool Health Monitoring

Agent-mgmt runs a background scheduler every 30-60 seconds:
- HTTP tools: GET request, 200-499 → ACTIVE, 500+ → DEGRADED, timeout → OFFLINE
- DATABASE/GRAPH/PYTHON tools: Auto-marked ACTIVE (no HTTP health check possible)
- Status changes published to `events:tool_health` Redis stream
