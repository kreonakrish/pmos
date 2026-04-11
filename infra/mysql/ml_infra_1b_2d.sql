-- =============================================================================
-- PMOS ML infrastructure — 1B learned scorer + 2D SOP discovery
--
-- 1B: Shadow-mode learned quality scorer.
--     train_learned_scorer.py writes model metadata to learned_scorer_models
--     and pickles the weights to a file on a shared volume. The orchestrator's
--     LearnedScorer module runs inference in pure Python after each scoring
--     call and logs its shadow prediction to learned_scorer_predictions for
--     later comparison with the real scoring service's output. No live score
--     influence yet — w7_learned_quality starts at 0.0 in scoring_weights.
--
-- 2D: SOP discovery via nightly clustering of user messages.
--     discover_sops.py writes proposed SOPs here with status='PENDING'; a
--     human promotes via the ML Insights UI, which flips the row to
--     'PROMOTED' and writes an SOPNode into Neo4j.
-- =============================================================================
USE pmos;

-- -----------------------------------------------------------------------------
-- 1B: model metadata — one row per trained model version
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS learned_scorer_models (
  id             INT AUTO_INCREMENT PRIMARY KEY,
  model_version  VARCHAR(64) NOT NULL UNIQUE,        -- e.g. "2026-04-10_21-50"
  algorithm      VARCHAR(50) NOT NULL DEFAULT 'logreg',
  feature_names  JSON NOT NULL,
  n_features     INT NOT NULL,
  n_samples      INT NOT NULL,
  n_positive     INT NOT NULL,
  n_synthetic    INT NOT NULL,                       -- rows from bootstrap
  n_real         INT NOT NULL,                       -- rows from rl_feedback_log
  train_accuracy FLOAT,
  val_accuracy   FLOAT,
  val_auc        FLOAT,
  weights_path   VARCHAR(500) NOT NULL,              -- path to pickled weights
  notes          TEXT,
  is_active      BOOLEAN NOT NULL DEFAULT FALSE,     -- exactly one row is_active=TRUE
  created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_active (is_active),
  INDEX idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- -----------------------------------------------------------------------------
-- 1B: shadow prediction log — one row per scoring call
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS learned_scorer_predictions (
  id                BIGINT AUTO_INCREMENT PRIMARY KEY,
  prediction_id     VARCHAR(36) NOT NULL UNIQUE,
  model_version     VARCHAR(64),
  trace_id          VARCHAR(36),
  session_id        VARCHAR(255),
  graph_id          VARCHAR(255),
  node_id           VARCHAR(255),
  agent_id          VARCHAR(36),
  agent_name        VARCHAR(255),
  heuristic_score   FLOAT,            -- what the real scoring service returned
  learned_score     FLOAT NOT NULL,   -- what this model predicts
  features          JSON NOT NULL,    -- the feature vector we used, for debugging
  user_feedback     ENUM('positive','negative') NULL,  -- backfilled if thumbs come in
  created_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_trace (trace_id),
  INDEX idx_session (session_id),
  INDEX idx_model (model_version),
  INDEX idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- -----------------------------------------------------------------------------
-- 1B: register w7_learned_quality factor, starting at 0.0 (inactive)
-- -----------------------------------------------------------------------------
INSERT IGNORE INTO scoring_weights
  (scope_type, scope_id, parameter_name, parameter_value, auto_adjust)
VALUES
  ('GLOBAL', NULL, 'w7_learned_quality', 0.0, TRUE);

-- -----------------------------------------------------------------------------
-- 2D: SOP proposals table — populated by discover_sops.py
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sop_proposals (
  id                BIGINT AUTO_INCREMENT PRIMARY KEY,
  proposal_id       VARCHAR(36) NOT NULL UNIQUE,
  cluster_size      INT NOT NULL,
  avg_score         FLOAT,                        -- average score of messages in this cluster
  best_agent_id     VARCHAR(36),
  best_agent_name   VARCHAR(255),
  summary           TEXT NOT NULL,                -- short machine-generated SOP description
  sample_messages   JSON NOT NULL,                -- up to 5 representative user requests
  keywords          JSON,                         -- top 10 TF-IDF terms for the cluster
  status            ENUM('PENDING','PROMOTED','REJECTED') NOT NULL DEFAULT 'PENDING',
  promoted_sop_id   VARCHAR(255),                 -- Neo4j SOPNode id when promoted
  reviewed_by       VARCHAR(255),
  reviewed_at       DATETIME,
  created_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_status_created (status, created_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

SELECT 'learned_scorer_models' AS tbl, COUNT(*) FROM learned_scorer_models
UNION ALL SELECT 'learned_scorer_predictions', COUNT(*) FROM learned_scorer_predictions
UNION ALL SELECT 'sop_proposals', COUNT(*) FROM sop_proposals;
