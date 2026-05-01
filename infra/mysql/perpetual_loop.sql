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
