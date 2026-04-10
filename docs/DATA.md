# DATA.md — Database Schemas, Graph Model & Redis Streams

## MySQL Tables (23 tables in `pmos` database)

### Service Ownership

| Table | Owner | Purpose |
|-------|-------|---------|
| agents | agent-mgmt | Agent registry (UUID, name, model, status) |
| tools | agent-mgmt | Tool registry (UUID, name, type, endpoint, auth) |
| teams | agent-mgmt | Team definitions |
| team_agents | agent-mgmt | Agent ↔ Team membership |
| agent_tools | agent-mgmt | Agent ↔ Tool assignments |
| tool_execution_history | agent-mgmt | Tool call audit log |
| capability_registry | meta-assembly (W), agent-mgmt (R) | Generated capabilities |
| conversations | orchestrator | Chat sessions |
| messages | orchestrator | User + agent messages |
| task_assignments | orchestrator | Task → agent mapping |
| execution_graph_log | orchestrator | Pipeline execution log |
| agent_interactions | orchestrator (W), gateway (R) | Full interaction payloads |
| agent_memory_extended | memory | Long-term memory store |
| execution_episodes | memory | Episodic memory (127+ entries) |
| rag_documents | rag | Document metadata (filename, status, chunks) |
| rag_chunks | rag | Chunk metadata |
| scoring_weights | scoring | Per-agent weight vectors |
| rl_feedback_log | scoring | RL training log |
| score_history | scoring | Score audit trail (50+ entries) |
| retry_configuration | orchestrator (R), agent-mgmt (W) | Retry policies |
| conversation_steps | gateway | Step tracking |
| agent_execution_history | orchestrator | Agent execution audit |

### Key Table: tools

```sql
tool_type ENUM('DATABASE','API','GITHUB','PYTHON','WEBSERVICE','FILE','VECTOR','GRAPH')
-- GRAPH type added for Neo4j Cypher queries via neo4j-driver
```

---

## Neo4j Graph Model (AuraDB Cloud)

### Nodes

| Label | Key Properties | Owner |
|-------|---------------|-------|
| TaskGraph | graph_id, session_id, conversation_id, status | orchestrator |
| TaskNode | node_id, graph_id, parent_id, description, node_type, status, score, depth | orchestrator |
| ExecutionEvent | event_id, event_type, agent_id, score, action_taken | orchestrator |
| AgentInteraction | interaction_id, agent_name, interaction_type, latency_ms, tools_used | orchestrator |
| Agent | agent_id, name, status, foundation_model | orchestrator (seed) |
| Team | team_id, name | orchestrator (seed) |
| AgentCapabilityNode | agent_id, tool_ids, domains | orchestrator |
| SOPNode | sop_id, domain, steps_json | orchestrator |

### TaskNode Types
- `ROOT` — original user question
- `SUBTASK` — LLM-decomposed sub-task
- `SUB_AGENT` — recursively spawned sub-agent task
- `VALIDATION`, `AGGREGATION`, `CORRECTION` — pipeline steps

### Relationships
```
(TaskNode)-[:SPAWNED_BY]->(TaskNode)          # parent-child task hierarchy
(TaskNode)-[:HAS_INTERACTION]->(AgentInteraction)
(TaskNode)-[:PRODUCED_EVENT]->(ExecutionEvent)
(Agent)-[:MEMBER_OF {role, priority}]->(Team)
(Agent)-[:REPORTS_TO]->(Agent)
(TaskNode)-[:ASSIGNED_TO]->(AgentCapabilityNode)
(TaskGraph)-[:HAS_ROOT]->(TaskNode)
```

### Home Lending Data (Pre-loaded)

The Neo4j database also contains home lending lifecycle nodes:
```
MortgageLoan(loan_id, interest_rate, original_loan_amount, loan_type, ...)
Borrower(borrower_id, first_name, last_name, credit_score, annual_income, ...)
Property(property_id, address, city, state, zip_code, appraised_value, ...)
Payment, Fee, Investor, Servicer, Lender, Broker, Employer, County, MSA, Zip,
QCReview, Document, Communication, Condition, Event, LoanAccount, Appraisal,
ValuationModel, HELOC, HomeEquityLoan, JumboLoan, BridgeLoan, ...
```
99 node labels total. Key: `(Borrower)-[:BORROWS]->(MortgageLoan)-[:SECURED_BY]->(Property)-[:IN_ZIP]->(Zip)-[:IN_COUNTY]->(County)-[:IN_MSA]->(MSA)`

---

## Redis Streams

| Stream | Producer | Consumer (Group) | Messages | Purpose |
|--------|----------|-----------------|----------|---------|
| `memory:writes` | orchestrator | memory (memory-service) | ~103 | Episodic memory persistence |
| `scoring:feedback` | scoring | orchestrator (orchestrator-group) + scoring (rl-engine) | ~30 | RL weight updates |
| `events:telemetry` | all services | (observability) | ~210 | System events |
| `events:tool_health` | agent-mgmt | orchestrator | ~41 | Tool status changes |
| `events:capability_added` | meta-assembly | orchestrator, agent-mgmt | ~6 | New capabilities |
| `events:documents` | gateway | rag (rag-ingestor) | 0 (consumed) | Document ingestion |
| `orchestrator:tasks` | orchestrator | (monitoring) | 0 | Task dispatch |

All stream messages include: `trace_id`, `source_service`, `timestamp`, `schema_version: "1"`.

### Other Redis Usage
- **Rate limiting**: String keys `gateway:rate:{user_id}` with Lua token bucket
- **Short-term memory**: Hash keys `agent:{id}:short_term` with TTL
