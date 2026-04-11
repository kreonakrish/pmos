-- =============================================================================
-- PMOS ML infrastructure tables
--
-- Supports:
--   2C  Node2Vec / graph embedding pipeline  → task_node_embeddings
--   1A  Contextual bandit agent selection    → bandit_agent_state, bandit_decisions
--
-- All rows live in the existing `pmos` database alongside the operational tables.
-- =============================================================================
USE pmos;

-- -----------------------------------------------------------------------------
-- 2C: graph-neighborhood embeddings for TaskNodes from Neo4j
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS task_node_embeddings (
  id             BIGINT AUTO_INCREMENT PRIMARY KEY,
  node_id        VARCHAR(255) NOT NULL,
  graph_id       VARCHAR(255),
  node_type      VARCHAR(50),
  dim            INT NOT NULL,
  algorithm      VARCHAR(50) NOT NULL,        -- 'node2vec' or 'spectral'
  embedding      JSON NOT NULL,               -- array of floats, length=dim
  computed_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_node_id (node_id),
  INDEX idx_graph (graph_id),
  INDEX idx_computed (computed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- -----------------------------------------------------------------------------
-- 1A: Bandit state — one row per (agent, context_bucket) tracking Beta(alpha,beta)
-- alpha  = 1 + total_reward         (smoothed successes)
-- beta   = 1 + (pulls - total_reward) (smoothed failures)
-- Thompson Sampling draws theta ~ Beta(alpha, beta) per arm and picks argmax.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bandit_agent_state (
  id             INT AUTO_INCREMENT PRIMARY KEY,
  agent_id       VARCHAR(36) NOT NULL,
  agent_name     VARCHAR(255),
  context_bucket VARCHAR(255) NOT NULL,      -- e.g. "team:abc|type:general"
  alpha          FLOAT NOT NULL DEFAULT 1.0,
  beta           FLOAT NOT NULL DEFAULT 1.0,
  pulls          INT NOT NULL DEFAULT 0,
  total_reward   FLOAT NOT NULL DEFAULT 0.0,
  last_updated   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_agent_context (agent_id, context_bucket),
  INDEX idx_context (context_bucket),
  INDEX idx_agent (agent_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- -----------------------------------------------------------------------------
-- 1A: Decision log — every bandit decision (live or shadow) for traceability.
-- Rewards are back-filled when scoring completes.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bandit_decisions (
  id                 BIGINT AUTO_INCREMENT PRIMARY KEY,
  decision_id        VARCHAR(36) NOT NULL UNIQUE,
  trace_id           VARCHAR(36),
  session_id         VARCHAR(255),
  graph_id           VARCHAR(255),
  node_id            VARCHAR(255),
  context_bucket     VARCHAR(255) NOT NULL,
  mode               ENUM('SHADOW','LIVE','FALLBACK','EXPLORATION') NOT NULL DEFAULT 'SHADOW',
  candidate_agents   JSON NOT NULL,           -- [{agent_id, agent_name, sampled_theta, alpha, beta, pulls}]
  selected_agent_id  VARCHAR(36) NOT NULL,
  selected_agent_name VARCHAR(255),
  bandit_pick_agent_id   VARCHAR(36),         -- what the bandit WOULD have picked (same as selected in LIVE, differs in SHADOW)
  bandit_pick_agent_name VARCHAR(255),
  reward             FLOAT,                   -- NULL until scoring completes
  reward_recorded_at DATETIME,
  created_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_trace (trace_id),
  INDEX idx_session (session_id),
  INDEX idx_mode_created (mode, created_at),
  INDEX idx_context (context_bucket)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- -----------------------------------------------------------------------------
-- Show what we just created
-- -----------------------------------------------------------------------------
SHOW CREATE TABLE task_node_embeddings\G
SHOW CREATE TABLE bandit_agent_state\G
SHOW CREATE TABLE bandit_decisions\G
