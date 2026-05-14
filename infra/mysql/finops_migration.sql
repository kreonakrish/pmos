-- Financial Governance — model pricing + per-call token/cost log.
-- This file mirrors the FINANCIAL GOVERNANCE block at the bottom of schema.sql
-- and is used to apply the migration to a running MySQL instance without
-- re-running the whole schema. Idempotent (CREATE TABLE IF NOT EXISTS,
-- INSERT IGNORE).

USE pmos;

CREATE TABLE IF NOT EXISTS model_pricing (
  pricing_id      BIGINT AUTO_INCREMENT PRIMARY KEY,
  provider        VARCHAR(20)   NOT NULL,
  model           VARCHAR(100)  NOT NULL,
  input_per_mtok  DECIMAL(10,4) NOT NULL,
  output_per_mtok DECIMAL(10,4) NOT NULL,
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
  service_name         VARCHAR(30)   NOT NULL,
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
  pricing_id           BIGINT        NULL,
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
