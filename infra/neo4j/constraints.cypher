// =============================================================================
// PMOS Neo4j 5.x Constraints & Indexes
// Run via: cypher-shell -u neo4j -p <password> -f constraints.cypher
// Or via the Neo4j browser / bootstrap.sh script
// =============================================================================

// =============================================================================
// UNIQUENESS CONSTRAINTS
// =============================================================================

// Agent nodes — agent_id is UUID
CREATE CONSTRAINT agent_id_unique IF NOT EXISTS
FOR (a:Agent) REQUIRE a.agent_id IS UNIQUE;

// Tool nodes — tool_id is UUID
CREATE CONSTRAINT tool_id_unique IF NOT EXISTS
FOR (t:Tool) REQUIRE t.tool_id IS UNIQUE;

// Skill nodes — skill_id is UUID
CREATE CONSTRAINT skill_id_unique IF NOT EXISTS
FOR (s:Skill) REQUIRE s.skill_id IS UNIQUE;

// Team nodes — team_id is UUID
CREATE CONSTRAINT team_id_unique IF NOT EXISTS
FOR (t:Team) REQUIRE t.team_id IS UNIQUE;

// TaskGraph nodes — graph_id is UUID
CREATE CONSTRAINT task_graph_id_unique IF NOT EXISTS
FOR (g:TaskGraph) REQUIRE g.graph_id IS UNIQUE;

// TaskNode nodes — node_id is UUID
CREATE CONSTRAINT task_node_id_unique IF NOT EXISTS
FOR (n:TaskNode) REQUIRE n.node_id IS UNIQUE;

// SOP nodes — sop_id is UUID
CREATE CONSTRAINT sop_id_unique IF NOT EXISTS
FOR (s:SOP) REQUIRE s.sop_id IS UNIQUE;

// ExecutionEvent nodes — event_id is UUID
CREATE CONSTRAINT execution_event_id_unique IF NOT EXISTS
FOR (e:ExecutionEvent) REQUIRE e.event_id IS UNIQUE;

// Memory nodes — memory_id is UUID
CREATE CONSTRAINT memory_id_unique IF NOT EXISTS
FOR (m:Memory) REQUIRE m.memory_id IS UNIQUE;

// CapabilityGap nodes — gap_id is UUID
CREATE CONSTRAINT capability_gap_id_unique IF NOT EXISTS
FOR (c:CapabilityGap) REQUIRE c.gap_id IS UNIQUE;

// AgentCapabilityNode — agent_id
CREATE CONSTRAINT agent_capability_node_id_unique IF NOT EXISTS
FOR (n:AgentCapabilityNode) REQUIRE n.agent_id IS UNIQUE;

// =============================================================================
// PROPERTY EXISTENCE CONSTRAINTS
// =============================================================================

CREATE CONSTRAINT agent_name_exists IF NOT EXISTS
FOR (a:Agent) REQUIRE a.name IS NOT NULL;

CREATE CONSTRAINT task_node_status_exists IF NOT EXISTS
FOR (n:TaskNode) REQUIRE n.status IS NOT NULL;

CREATE CONSTRAINT task_node_graph_id_exists IF NOT EXISTS
FOR (n:TaskNode) REQUIRE n.graph_id IS NOT NULL;

// =============================================================================
// B-TREE INDEXES (for filtering by common predicates)
// =============================================================================

// Agent indexes
CREATE INDEX agent_status_idx IF NOT EXISTS
FOR (a:Agent) ON (a.status);

CREATE INDEX agent_accuracy_idx IF NOT EXISTS
FOR (a:Agent) ON (a.accuracy_rate);

CREATE INDEX agent_meta_capable_idx IF NOT EXISTS
FOR (a:Agent) ON (a.meta_capable);

// Tool indexes
CREATE INDEX tool_status_idx IF NOT EXISTS
FOR (t:Tool) ON (t.status);

CREATE INDEX tool_type_idx IF NOT EXISTS
FOR (t:Tool) ON (t.tool_type);

// TaskNode indexes
CREATE INDEX task_node_status_idx IF NOT EXISTS
FOR (n:TaskNode) ON (n.status);

CREATE INDEX task_node_graph_id_idx IF NOT EXISTS
FOR (n:TaskNode) ON (n.graph_id);

CREATE INDEX task_node_criticality_idx IF NOT EXISTS
FOR (n:TaskNode) ON (n.criticality);

CREATE INDEX task_node_iteration_idx IF NOT EXISTS
FOR (n:TaskNode) ON (n.iteration);

// TaskGraph indexes
CREATE INDEX task_graph_status_idx IF NOT EXISTS
FOR (g:TaskGraph) ON (g.status);

CREATE INDEX task_graph_session_idx IF NOT EXISTS
FOR (g:TaskGraph) ON (g.session_id);

// SOP indexes
CREATE INDEX sop_domain_idx IF NOT EXISTS
FOR (s:SOP) ON (s.domain);

CREATE INDEX sop_usage_idx IF NOT EXISTS
FOR (s:SOP) ON (s.usage_count);

// ExecutionEvent indexes
CREATE INDEX execution_event_type_idx IF NOT EXISTS
FOR (e:ExecutionEvent) ON (e.event_type);

CREATE INDEX execution_event_agent_idx IF NOT EXISTS
FOR (e:ExecutionEvent) ON (e.agent_id);

CREATE INDEX execution_event_timestamp_idx IF NOT EXISTS
FOR (e:ExecutionEvent) ON (e.timestamp);

// Memory indexes
CREATE INDEX memory_tier_idx IF NOT EXISTS
FOR (m:Memory) ON (m.memory_tier);

CREATE INDEX memory_agent_id_idx IF NOT EXISTS
FOR (m:Memory) ON (m.agent_id);

CREATE INDEX memory_expires_idx IF NOT EXISTS
FOR (m:Memory) ON (m.expires_at);

// CapabilityGap indexes
CREATE INDEX capability_gap_status_idx IF NOT EXISTS
FOR (c:CapabilityGap) ON (c.resolution_status);

CREATE INDEX capability_gap_type_idx IF NOT EXISTS
FOR (c:CapabilityGap) ON (c.gap_type);

// =============================================================================
// COMPOSITE INDEXES (for common multi-predicate queries)
// =============================================================================

CREATE INDEX agent_status_accuracy_idx IF NOT EXISTS
FOR (a:Agent) ON (a.status, a.accuracy_rate);

CREATE INDEX task_node_graph_status_idx IF NOT EXISTS
FOR (n:TaskNode) ON (n.graph_id, n.status);

CREATE INDEX memory_agent_tier_idx IF NOT EXISTS
FOR (m:Memory) ON (m.agent_id, m.memory_tier);

// =============================================================================
// VECTOR INDEX (for semantic SOP similarity search)
// Requires Neo4j 5.11+ with GDS or native vector index
// =============================================================================

CREATE VECTOR INDEX sop_embeddings IF NOT EXISTS
FOR (s:SOP) ON (s.embedding)
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 768,
    `vector.similarity_function`: 'cosine'
  }
};

CREATE VECTOR INDEX skill_embeddings IF NOT EXISTS
FOR (s:Skill) ON (s.embedding)
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 768,
    `vector.similarity_function`: 'cosine'
  }
};

CREATE VECTOR INDEX memory_embeddings IF NOT EXISTS
FOR (m:Memory) ON (m.embedding)
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 768,
    `vector.similarity_function`: 'cosine'
  }
};
