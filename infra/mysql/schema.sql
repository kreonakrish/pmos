-- =============================================================================
-- PMOS MySQL Schema
-- MySQL 8.2 — Run via: mysql -u root -p pmos < schema.sql
-- All tables use utf8mb4 charset and InnoDB engine
-- =============================================================================

CREATE DATABASE IF NOT EXISTS pmos CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE pmos;

-- =============================================================================
-- AGENT MANAGEMENT SERVICE TABLES
-- =============================================================================

CREATE TABLE IF NOT EXISTS agents (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  agent_id        VARCHAR(36) NOT NULL UNIQUE,          -- UUID
  name            VARCHAR(255) NOT NULL,
  description     TEXT,
  foundation_model VARCHAR(100) NOT NULL DEFAULT 'gpt-4o',
  status          ENUM('IDLE','ACTIVE','BUSY','DEGRADED','DEPRECATED') NOT NULL DEFAULT 'IDLE',
  accuracy_rate   FLOAT NOT NULL DEFAULT 0.0,
  success_rate    FLOAT NOT NULL DEFAULT 0.0,
  total_executions INT NOT NULL DEFAULT 0,
  health_score    FLOAT NOT NULL DEFAULT 1.0,
  meta_capable    BOOLEAN NOT NULL DEFAULT FALSE,
  is_primary      BOOLEAN NOT NULL DEFAULT FALSE,
  degraded_at     DATETIME NULL,
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_status (status),
  INDEX idx_meta_capable (meta_capable)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS tools (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  tool_id         VARCHAR(36) NOT NULL UNIQUE,          -- UUID
  name            VARCHAR(255) NOT NULL,
  description     TEXT,
  tool_type       ENUM('DATABASE','API','GITHUB','PYTHON','WEBSERVICE','FILE','VECTOR','GRAPH') NOT NULL,
  hostname        VARCHAR(500),
  endpoint        VARCHAR(500),
  auth_method     ENUM('NONE','API_KEY','BEARER','BASIC','OAUTH2') NOT NULL DEFAULT 'NONE',
  auth_config     JSON,
  status          ENUM('ACTIVE','DEGRADED','OFFLINE') NOT NULL DEFAULT 'ACTIVE',
  avg_latency_ms  FLOAT NOT NULL DEFAULT 0.0,
  success_rate    FLOAT NOT NULL DEFAULT 1.0,
  last_health_check DATETIME NULL,
  is_dynamic      BOOLEAN NOT NULL DEFAULT FALSE,        -- true if created by meta-assembly
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_status (status),
  INDEX idx_tool_type (tool_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS teams (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  team_id         VARCHAR(36) NOT NULL UNIQUE,          -- UUID
  name            VARCHAR(255) NOT NULL,
  description     TEXT,
  use_smart_workflow BOOLEAN NOT NULL DEFAULT TRUE,
  accuracy_threshold FLOAT NOT NULL DEFAULT 0.7,
  max_retries     INT NOT NULL DEFAULT 3,
  retry_strategy  ENUM('LINEAR','EXPONENTIAL','FIBONACCI') NOT NULL DEFAULT 'EXPONENTIAL',
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS team_agents (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  team_id         VARCHAR(36) NOT NULL,
  agent_id        VARCHAR(36) NOT NULL,
  priority        INT NOT NULL DEFAULT 0,               -- lower = higher priority
  role            VARCHAR(100),
  accuracy        FLOAT NOT NULL DEFAULT 0.0,
  success_rate    FLOAT NOT NULL DEFAULT 0.0,
  assigned_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_team_agent (team_id, agent_id),
  INDEX idx_team_id (team_id),
  INDEX idx_agent_id (agent_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS agent_tools (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  agent_id        VARCHAR(36) NOT NULL,
  tool_id         VARCHAR(36) NOT NULL,
  permission_level ENUM('READ','WRITE','ADMIN') NOT NULL DEFAULT 'READ',
  assigned_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_agent_tool (agent_id, tool_id),
  INDEX idx_agent_id (agent_id),
  INDEX idx_tool_id (tool_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =============================================================================
-- META-ASSEMBLY SERVICE TABLES (writes), AGENT-MGMT (reads)
-- =============================================================================

CREATE TABLE IF NOT EXISTS capability_registry (
  id              BIGINT AUTO_INCREMENT PRIMARY KEY,
  capability_type ENUM('TOOL','SKILL','AGENT') NOT NULL,
  capability_id   VARCHAR(255) NOT NULL,
  name            VARCHAR(255) NOT NULL,
  description     TEXT,
  spec_json       JSON,                                 -- full generated spec
  source          ENUM('STATIC','DYNAMIC') NOT NULL DEFAULT 'STATIC',
  gap_id          VARCHAR(255),                         -- CapabilityGap that triggered creation
  validation_score FLOAT,
  is_active       BOOLEAN NOT NULL DEFAULT TRUE,
  usage_count     INT NOT NULL DEFAULT 0,
  last_used       DATETIME NULL,
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_cap (capability_type, capability_id),
  INDEX idx_active (is_active),
  INDEX idx_gap (gap_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =============================================================================
-- MEMORY SERVICE TABLES
-- =============================================================================

CREATE TABLE IF NOT EXISTS agent_memory_extended (
  id              BIGINT AUTO_INCREMENT PRIMARY KEY,
  agent_id        INT NOT NULL,
  memory_tier     ENUM('SHORT_TERM','LONG_TERM','REASONING','EPISODIC') NOT NULL,
  content         TEXT NOT NULL,
  content_vector_id VARCHAR(255),                       -- reference to vector store entry
  metadata        JSON,
  relevance_score FLOAT NOT NULL DEFAULT 0.5,
  access_count    INT NOT NULL DEFAULT 0,
  last_accessed   DATETIME NULL,
  decay_factor    FLOAT NOT NULL DEFAULT 1.0,
  expires_at      DATETIME NULL,                        -- NULL = permanent
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_agent_tier (agent_id, memory_tier),
  INDEX idx_expires (expires_at),
  INDEX idx_relevance (agent_id, relevance_score)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS execution_episodes (
  id              BIGINT AUTO_INCREMENT PRIMARY KEY,
  episode_id      VARCHAR(36) NOT NULL UNIQUE,
  agent_id        INT NOT NULL,
  session_id      VARCHAR(255) NOT NULL,
  task_description TEXT,
  input_context   JSON,
  steps_taken     JSON,
  final_output    TEXT,
  final_score     FLOAT,
  outcome         ENUM('SUCCESS','FAILURE','PARTIAL') NOT NULL,
  embedding_id    VARCHAR(255),                         -- vector store reference
  importance_score FLOAT NOT NULL DEFAULT 0.5,
  expires_at      DATETIME NULL,
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_agent (agent_id),
  INDEX idx_session (session_id),
  INDEX idx_outcome (outcome),
  INDEX idx_expires (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =============================================================================
-- SCORING SERVICE TABLES
-- =============================================================================

CREATE TABLE IF NOT EXISTS scoring_weights (
  id              BIGINT AUTO_INCREMENT PRIMARY KEY,
  scope_type      ENUM('GLOBAL','TEAM','AGENT','TASK_TYPE') NOT NULL,
  scope_id        VARCHAR(255),                         -- team_id, agent_id, or task_type
  parameter_name  VARCHAR(100) NOT NULL,                -- w1..w6 or named factor
  parameter_value FLOAT NOT NULL,
  band_low        FLOAT,
  band_high       FLOAT,
  auto_adjust     BOOLEAN NOT NULL DEFAULT TRUE,
  last_adjusted   DATETIME NULL,
  adjustment_count INT NOT NULL DEFAULT 0,
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_scope_param (scope_type, scope_id, parameter_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS rl_feedback_log (
  id              BIGINT AUTO_INCREMENT PRIMARY KEY,
  session_id      VARCHAR(255),
  node_id         VARCHAR(255),
  agent_id        INT,
  feedback_source ENUM('AUTOMATED','USER','INTER_AGENT','ORCHESTRATOR') NOT NULL,
  feedback_type   ENUM('SCORE','CORRECTION','BAND_ADJUST','RETRY','FALLBACK','AUTOCORRECT') NOT NULL,
  original_score  FLOAT,
  adjusted_score  FLOAT,
  reward_signal   FLOAT,
  band_low_before FLOAT,
  band_high_before FLOAT,
  band_low_after  FLOAT,
  band_high_after FLOAT,
  feedback_payload JSON,
  processed_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_agent_feedback (agent_id, feedback_source),
  INDEX idx_session (session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS score_history (
  id              BIGINT AUTO_INCREMENT PRIMARY KEY,
  agent_id        INT NOT NULL,
  task_id         VARCHAR(255),
  context_type    VARCHAR(100) NOT NULL DEFAULT 'general',
  score           FLOAT NOT NULL,
  factors         JSON,                                 -- breakdown: {w1: 0.3, ...}
  band_low        FLOAT,
  band_high       FLOAT,
  within_band     BOOLEAN,
  correction_triggered BOOLEAN NOT NULL DEFAULT FALSE,
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_agent_context (agent_id, context_type),
  INDEX idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =============================================================================
-- ORCHESTRATOR SERVICE TABLES
-- =============================================================================

CREATE TABLE IF NOT EXISTS task_assignments (
  id              BIGINT AUTO_INCREMENT PRIMARY KEY,
  task_id         VARCHAR(255) NOT NULL UNIQUE,
  graph_id        VARCHAR(255) NOT NULL,
  session_id      VARCHAR(255) NOT NULL,
  parent_task_id  VARCHAR(255),
  assigned_agent_id INT,
  status          ENUM('PENDING','RUNNING','SUCCESS','FAILED','SKIPPED','CORRECTING') NOT NULL DEFAULT 'PENDING',
  criticality     ENUM('LOW','MEDIUM','HIGH','CRITICAL') NOT NULL DEFAULT 'MEDIUM',
  retry_count     INT NOT NULL DEFAULT 0,
  max_retries     INT NOT NULL DEFAULT 3,
  score           FLOAT,
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_graph (graph_id),
  INDEX idx_session (session_id),
  INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS execution_graph_log (
  id              BIGINT AUTO_INCREMENT PRIMARY KEY,
  graph_id        VARCHAR(255) NOT NULL,
  node_id         VARCHAR(255) NOT NULL,
  session_id      VARCHAR(255),
  agent_id        INT,
  iteration       INT NOT NULL DEFAULT 0,
  node_type       VARCHAR(50),
  status          VARCHAR(50),
  score           FLOAT,
  execution_time_ms INT,
  correction_triggered BOOLEAN NOT NULL DEFAULT FALSE,
  auto_corrected  BOOLEAN NOT NULL DEFAULT FALSE,
  fallback_triggered BOOLEAN NOT NULL DEFAULT FALSE,
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_graph (graph_id),
  INDEX idx_session (session_id),
  INDEX idx_agent (agent_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS retry_configuration (
  id              BIGINT AUTO_INCREMENT PRIMARY KEY,
  scope_type      ENUM('GLOBAL','TEAM','AGENT','TASK_TYPE') NOT NULL,
  scope_id        VARCHAR(255),
  max_retries     INT NOT NULL DEFAULT 3,
  retry_strategy  ENUM('LINEAR','EXPONENTIAL','FIBONACCI') NOT NULL DEFAULT 'EXPONENTIAL',
  base_delay_ms   INT NOT NULL DEFAULT 1000,
  max_delay_ms    INT NOT NULL DEFAULT 30000,
  jitter_enabled  BOOLEAN NOT NULL DEFAULT TRUE,
  auto_adjust     BOOLEAN NOT NULL DEFAULT TRUE,
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_scope (scope_type, scope_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =============================================================================
-- AGENT-MGMT SERVICE — TOOL EXECUTION HISTORY
-- =============================================================================

CREATE TABLE IF NOT EXISTS tool_execution_history (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  execution_id    VARCHAR(36) NOT NULL UNIQUE,
  tool_id         VARCHAR(36) NOT NULL,
  tool_type       VARCHAR(20) NOT NULL,
  status          ENUM('success','failure') NOT NULL,
  inputs          JSON,
  output          JSON,
  error_message   TEXT,
  latency_ms      INT NOT NULL DEFAULT 0,
  trace_id        VARCHAR(36),
  agent_id        VARCHAR(36),
  agent_name      VARCHAR(255),
  team_id         VARCHAR(36),
  team_name       VARCHAR(255),
  conversation_id VARCHAR(36),
  source          ENUM('manual','pipeline','health_check') DEFAULT 'manual',
  created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_tool_id (tool_id),
  INDEX idx_created_at (created_at),
  INDEX idx_tool_created (tool_id, created_at DESC),
  INDEX idx_agent_id (agent_id),
  INDEX idx_conversation_id (conversation_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =============================================================================
-- GATEWAY SERVICE TABLES
-- =============================================================================

CREATE TABLE IF NOT EXISTS conversations (
  id              BIGINT AUTO_INCREMENT PRIMARY KEY,
  conversation_id VARCHAR(36) NOT NULL UNIQUE,
  user_id         VARCHAR(255),
  team_id         VARCHAR(36),
  title           VARCHAR(500),
  status          ENUM('ACTIVE','COMPLETED','ARCHIVED') NOT NULL DEFAULT 'ACTIVE',
  metadata        JSON,
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_user (user_id),
  INDEX idx_team (team_id),
  INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS conversation_steps (
  id              BIGINT AUTO_INCREMENT PRIMARY KEY,
  step_id         VARCHAR(36) NOT NULL UNIQUE,
  conversation_id VARCHAR(36) NOT NULL,
  session_id      VARCHAR(255),
  graph_id        VARCHAR(255),
  step_order      INT NOT NULL DEFAULT 0,
  status          ENUM('PENDING','RUNNING','COMPLETED','FAILED') NOT NULL DEFAULT 'PENDING',
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_conversation (conversation_id),
  INDEX idx_session (session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS messages (
  id              BIGINT AUTO_INCREMENT PRIMARY KEY,
  message_id      VARCHAR(36) NOT NULL UNIQUE,
  conversation_id VARCHAR(36) NOT NULL,
  role            ENUM('user','assistant','system','tool') NOT NULL,
  content         TEXT NOT NULL,
  trace_id        VARCHAR(255),
  score           FLOAT,
  metadata        JSON,
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_conversation (conversation_id),
  INDEX idx_trace (trace_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =============================================================================
-- AUDIT EVENTS — system-wide audit log (Phase E2)
-- One row per meaningful hop in any pipeline (orchestrator, translator, ...)
-- =============================================================================

CREATE TABLE IF NOT EXISTS audit_events (
    event_id      CHAR(36) PRIMARY KEY,
    trace_id      CHAR(36) NOT NULL,
    actor         VARCHAR(255) NOT NULL,            -- 'system', user_id, agent_id, or service name
    actor_type    ENUM('USER','AGENT','SERVICE','SYSTEM') NOT NULL DEFAULT 'SYSTEM',
    action        VARCHAR(100) NOT NULL,            -- e.g. 'pipeline.intake', 'translator.translate', 'agent.bid_won'
    resource_type VARCHAR(80),                      -- 'TaskGraph','TaskNode','Tool','Crawler','Conversation'
    resource_id   VARCHAR(255),
    severity      ENUM('INFO','WARN','ERROR') NOT NULL DEFAULT 'INFO',
    payload       JSON,
    ts            DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    INDEX idx_trace (trace_id),
    INDEX idx_actor (actor, ts),
    INDEX idx_action (action, ts),
    INDEX idx_resource (resource_type, resource_id),
    INDEX idx_ts (ts)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =============================================================================
-- SYNONYM PROPOSALS — Phase F5
-- Post-crawl LLM-clustered BusinessAttribute synonyms / duplications / grain
-- variants. Data Stewards review and pick a canonical attribute + canonical
-- physical column; on CONFIRM, non-canonical BAs are merged into the canonical
-- one, their MAPS_TO edges are superseded, and the canonical BA gains a new
-- CANONICAL MAPS_TO to the chosen physical column.
-- =============================================================================

CREATE TABLE IF NOT EXISTS synonym_proposals (
    proposal_id      CHAR(36) PRIMARY KEY,
    kind             ENUM('SYNONYM','DUPLICATION','GRAIN','NAMING','OTHER') NOT NULL,
    domain           VARCHAR(120),
    members_json     JSON NOT NULL,          -- list of BusinessAttribute fq_names in this cluster
    member_columns_json JSON,                -- list of {ba_fq_name, column_fq_name, source_uri, sample_values}
    suggested_canonical_attr  VARCHAR(255),  -- LLM's best guess, auditor can override
    suggested_canonical_column VARCHAR(512), -- LLM's best guess, auditor can override
    rationale        TEXT,
    confidence       FLOAT,
    status           ENUM('PROPOSED','IN_REVIEW','CONFIRMED','REJECTED','APPLIED','SUPERSEDED')
                          NOT NULL DEFAULT 'PROPOSED',
    chosen_canonical_attr   VARCHAR(255),    -- auditor's pick
    chosen_canonical_column VARCHAR(512),    -- auditor's pick
    reviewed_by      VARCHAR(255),
    reviewed_at      DATETIME(3),
    applied_at       DATETIME(3),
    created_at       DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    INDEX idx_status (status, kind),
    INDEX idx_domain (domain, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =============================================================================
-- SEED DATA — Default global scoring weights
-- w1=relevance, w2=accuracy, w3=tool_success, w4=latency, w5=memory_util, w6=validation
-- =============================================================================

INSERT IGNORE INTO scoring_weights (scope_type, scope_id, parameter_name, parameter_value, auto_adjust)
VALUES
  ('GLOBAL', NULL, 'w1_relevance',         0.30, TRUE),
  ('GLOBAL', NULL, 'w2_accuracy',          0.25, TRUE),
  ('GLOBAL', NULL, 'w3_tool_success',      0.20, TRUE),
  ('GLOBAL', NULL, 'w4_latency',           0.10, TRUE),
  ('GLOBAL', NULL, 'w5_memory_utilization',0.05, TRUE),
  ('GLOBAL', NULL, 'w6_validation',        0.10, TRUE);

-- Default global retry configuration
INSERT IGNORE INTO retry_configuration (scope_type, scope_id, max_retries, retry_strategy, base_delay_ms, max_delay_ms)
VALUES ('GLOBAL', NULL, 3, 'EXPONENTIAL', 1000, 30000);

-- =============================================================================
-- FINANCIAL GOVERNANCE — model pricing + per-call token/cost log
-- Persists every LLM call across orchestrator/translator/meta-assembly with
-- full attribution (service, team, agent, conversation, user, tool, trace).
-- =============================================================================

CREATE TABLE IF NOT EXISTS model_pricing (
  pricing_id      BIGINT AUTO_INCREMENT PRIMARY KEY,
  provider        VARCHAR(20)   NOT NULL,                   -- openai|anthropic|google|ollama
  model           VARCHAR(100)  NOT NULL,                   -- gpt-4o, claude-sonnet-4-6, etc.
  input_per_mtok  DECIMAL(10,4) NOT NULL,                   -- USD per 1M input tokens
  output_per_mtok DECIMAL(10,4) NOT NULL,                   -- USD per 1M output tokens
  effective_from  TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  notes           VARCHAR(500),
  created_at      TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_pricing (provider, model, effective_from),
  INDEX idx_pricing_lookup (provider, model, effective_from)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS llm_call_log (
  call_id              CHAR(36)      NOT NULL PRIMARY KEY,
  ts                   TIMESTAMP(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  service_name         VARCHAR(30)   NOT NULL,              -- orchestrator|translator|meta-assembly
  trace_id             VARCHAR(64),
  conversation_id      VARCHAR(64),
  user_id              VARCHAR(255),
  team_id              VARCHAR(64),
  agent_id             VARCHAR(64),
  tool_invocation_id   VARCHAR(64),
  provider             VARCHAR(20)   NOT NULL,
  model                VARCHAR(100)  NOT NULL,
  prompt_tokens        INT           NOT NULL DEFAULT 0,
  completion_tokens    INT           NOT NULL DEFAULT 0,
  total_tokens         INT           NOT NULL DEFAULT 0,
  cost_usd             DECIMAL(12,6) NOT NULL DEFAULT 0,
  pricing_id           BIGINT        NULL,                  -- audit: which pricing row was applied
  latency_ms           INT,
  finish_reason        VARCHAR(30),
  had_tool_calls       TINYINT(1)    NOT NULL DEFAULT 0,
  error                TEXT,
  INDEX idx_llm_ts (ts),
  INDEX idx_llm_conv (conversation_id, ts),
  INDEX idx_llm_user (user_id, ts),
  INDEX idx_llm_agent (agent_id, ts),
  INDEX idx_llm_team (team_id, ts),
  INDEX idx_llm_model (provider, model, ts),
  INDEX idx_llm_service (service_name, ts),
  INDEX idx_llm_trace (trace_id),
  CONSTRAINT fk_llm_pricing FOREIGN KEY (pricing_id) REFERENCES model_pricing(pricing_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Seed published per-MTok pricing for the models PMOS uses today.
-- Update via the FinOps Pricing Admin UI when providers change rates.
INSERT IGNORE INTO model_pricing (provider, model, input_per_mtok, output_per_mtok, effective_from, notes) VALUES
  ('openai',    'gpt-4o',              2.5000, 10.0000, '2026-01-01 00:00:00', 'OpenAI public pricing'),
  ('openai',    'gpt-4o-mini',         0.1500,  0.6000, '2026-01-01 00:00:00', 'OpenAI public pricing'),
  ('openai',    'gpt-4.1',             3.0000, 12.0000, '2026-01-01 00:00:00', 'OpenAI public pricing'),
  ('anthropic', 'claude-opus-4-7',    15.0000, 75.0000, '2026-01-01 00:00:00', 'Anthropic public pricing'),
  ('anthropic', 'claude-sonnet-4-6',   3.0000, 15.0000, '2026-01-01 00:00:00', 'Anthropic public pricing'),
  ('anthropic', 'claude-haiku-4-5',    1.0000,  5.0000, '2026-01-01 00:00:00', 'Anthropic public pricing'),
  ('google',    'gemini-1.5-pro',      1.2500,  5.0000, '2026-01-01 00:00:00', 'Google public pricing'),
  ('google',    'gemini-1.5-flash',    0.0750,  0.3000, '2026-01-01 00:00:00', 'Google public pricing'),
  ('ollama',    'llama3',              0.0000,  0.0000, '2026-01-01 00:00:00', 'Local — no provider cost'),
  ('ollama',    'mistral',             0.0000,  0.0000, '2026-01-01 00:00:00', 'Local — no provider cost');
