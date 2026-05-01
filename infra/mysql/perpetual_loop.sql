-- =============================================================================
-- PMOS Perpetual Agentic Loop — schema additions
-- Run via: mysql -u root -p pmos < perpetual_loop.sql
-- Idempotent (CREATE TABLE IF NOT EXISTS).
-- =============================================================================

USE pmos;

-- -----------------------------------------------------------------------------
-- pipeline_events — chronological, replayable event stream.
-- Phase A: complete observability for the Decomposition Timeline UI.
-- One row per event published by orchestrator / sandbox / course corrector.
-- Mirrors what is XADDed to the Redis stream pmos:events:<conversation_id> so
-- that the UI can replay a completed conversation without keeping the stream
-- alive forever.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pipeline_events (
    event_id        CHAR(36) PRIMARY KEY,
    trace_id        VARCHAR(128) NOT NULL,
    conversation_id VARCHAR(255) NOT NULL,
    graph_id        VARCHAR(255),
    node_id         VARCHAR(255),
    iteration       INT NOT NULL DEFAULT 0,
    round           INT NOT NULL DEFAULT 0,
    kind            VARCHAR(80) NOT NULL,
    status          VARCHAR(40) NOT NULL DEFAULT 'IN_PROGRESS',
    payload         JSON,
    ts              DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    INDEX idx_conversation (conversation_id, ts),
    INDEX idx_graph (graph_id, ts),
    INDEX idx_kind (kind, ts),
    INDEX idx_trace (trace_id),
    INDEX idx_node (node_id, ts)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- -----------------------------------------------------------------------------
-- Phase C: durable learning artifacts. Written at the end of every successful
-- outer-loop round so a future run on a similar question can short-circuit
-- entity resolution, reuse known-good decompositions, and weight bid scoring
-- by which agent actually delivered with which tool.
-- -----------------------------------------------------------------------------

-- Resolved entity → canonical mapping. One row per (intent, raw_phrase) pair
-- the team successfully grounded. The prompt assembler reads this on future
-- turns to skip re-grounding identical phrases.
CREATE TABLE IF NOT EXISTS entity_resolution_log (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    conversation_id     VARCHAR(255),
    graph_id            VARCHAR(255),
    intent              VARCHAR(120),
    raw_phrase          VARCHAR(500) NOT NULL,
    canonical_entity    VARCHAR(500),
    ontology_version    VARCHAR(60),
    score               FLOAT,
    source              VARCHAR(60) NOT NULL DEFAULT 'pipeline',
    ts                  DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    INDEX idx_phrase (raw_phrase, intent),
    INDEX idx_intent (intent, ts),
    INDEX idx_canonical (canonical_entity, ts)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Successful decomposition pattern. One row per outer-round that ended with
-- sufficient=true, capturing the sub-task list that worked. The pattern
-- dispatcher consults this table as a learned fallback when no hard-coded
-- pattern claims a question.
CREATE TABLE IF NOT EXISTS effective_decompositions (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    conversation_id     VARCHAR(255),
    graph_id            VARCHAR(255) NOT NULL,
    intent              VARCHAR(120),
    user_question       TEXT NOT NULL,
    subtask_list        JSON NOT NULL,
    n_subtasks          INT NOT NULL DEFAULT 0,
    rounds_to_success   INT NOT NULL DEFAULT 1,
    avg_score           FLOAT,
    ts                  DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    INDEX idx_intent (intent, ts),
    INDEX idx_graph (graph_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Per-(agent, tool, intent) affinity. One row per successful tool use during
-- execution, with the score the agent's response earned. Bid evaluator on the
-- next turn weights bids by historical affinity.
CREATE TABLE IF NOT EXISTS agent_tool_affinity (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    agent_id            VARCHAR(36),
    agent_name          VARCHAR(255),
    tool_id             VARCHAR(36),
    tool_name           VARCHAR(255),
    intent              VARCHAR(120),
    score               FLOAT NOT NULL,
    success             TINYINT(1) NOT NULL DEFAULT 1,
    graph_id            VARCHAR(255),
    node_id             VARCHAR(255),
    ts                  DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    INDEX idx_agent_tool (agent_id, tool_id),
    INDEX idx_intent (intent, ts),
    INDEX idx_agent_intent (agent_id, intent, ts)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- User feedback per assistant message. Phase C.3 captures explicit signals
-- (thumbs / free text) so the next turn's prompt assembly can incorporate
-- "user rejected approach X on turn N" into the system prompt.
CREATE TABLE IF NOT EXISTS user_feedback (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    conversation_id     VARCHAR(255) NOT NULL,
    trace_id            VARCHAR(128),
    graph_id            VARCHAR(255),
    turn_id             VARCHAR(255),
    user_id             INT,
    rating              ENUM('UP','DOWN','NEUTRAL') NOT NULL DEFAULT 'NEUTRAL',
    comment             TEXT,
    created_at          DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    INDEX idx_conversation (conversation_id, created_at),
    INDEX idx_user (user_id, created_at),
    INDEX idx_rating (rating, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
