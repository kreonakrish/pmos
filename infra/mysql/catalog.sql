-- =============================================================================
-- PMOS Data Catalog — Phase 1
--
-- Supports a metadata crawler framework that extracts table/column metadata
-- from source systems, asks an LLM to propose a mapping from physical
-- columns to business entities/attributes, writes the resulting ontology
-- into Neo4j, and keeps a full audit trail of every LLM decision in MySQL
-- so a human auditor can later review, correct, and feed reinforcement
-- signal back into the mapper.
--
-- Tables:
--   crawlers                   — crawler registry (config per source)
--   crawl_runs                 — execution history per crawler
--   semantic_mapping_decisions — every LLM mapping decision, with
--                                auditor review + reward signal
-- =============================================================================
USE pmos;

-- -----------------------------------------------------------------------------
-- Crawler registry
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crawlers (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  crawler_id      VARCHAR(36) NOT NULL UNIQUE,
  name            VARCHAR(255) NOT NULL,
  description     TEXT,
  source_type     ENUM(
                    'MYSQL','POSTGRES','SQLSERVER','ORACLE','TERADATA',
                    'SNOWFLAKE','GLUE','S3','EXCEL','CSV','SSRS_RDL',
                    'NEO4J'
                  ) NOT NULL,
  connection      JSON NOT NULL,        -- host, port, database, schemas[], auth ref
  options         JSON,                 -- crawler-specific options (sample_rows, skip_views, ...)
  schedule_cron   VARCHAR(100),         -- nullable; human triggers for now
  status          ENUM('ACTIVE','PAUSED','ERROR') NOT NULL DEFAULT 'ACTIVE',
  last_run_at     DATETIME,
  last_run_status ENUM('SUCCESS','FAILURE','PARTIAL') NULL,
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_source_type (source_type),
  INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- -----------------------------------------------------------------------------
-- Execution history — one row per crawl invocation
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crawl_runs (
  id              BIGINT AUTO_INCREMENT PRIMARY KEY,
  run_id          VARCHAR(36) NOT NULL UNIQUE,
  crawler_id      VARCHAR(36) NOT NULL,
  started_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finished_at     DATETIME,
  status          ENUM('RUNNING','SUCCESS','FAILURE','PARTIAL') NOT NULL DEFAULT 'RUNNING',
  assets_found    INT NOT NULL DEFAULT 0,
  columns_found   INT NOT NULL DEFAULT 0,
  mappings_made   INT NOT NULL DEFAULT 0,
  entities_created INT NOT NULL DEFAULT 0,
  duration_ms     INT,
  error_message   TEXT,
  stats           JSON,                -- per-table breakdown
  trace_id        VARCHAR(36),
  triggered_by    VARCHAR(255),
  INDEX idx_crawler (crawler_id),
  INDEX idx_started (started_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- -----------------------------------------------------------------------------
-- Semantic mapping decisions — the audit trail + RL feedback surface
--
-- One row per column mapping the LLM ever produces. Status transitions:
--   AUTO_ACCEPTED → (auditor acts) → CONFIRMED | CORRECTED | REJECTED
-- Reward signal:
--   +1.0 for CONFIRMED, -0.5 for CORRECTED, -1.0 for REJECTED
-- Future training runs of the semantic mapper can fine-tune or few-shot
-- from rows where auditor_entity/auditor_attribute differ from the proposed.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS semantic_mapping_decisions (
  id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
  decision_id         VARCHAR(36) NOT NULL UNIQUE,
  run_id              VARCHAR(36) NOT NULL,
  crawler_id          VARCHAR(36) NOT NULL,
  -- Physical side (what the crawler found)
  data_source         VARCHAR(255) NOT NULL,   -- e.g. 'mysql://host:3306/pmos_servicing'
  data_asset          VARCHAR(255) NOT NULL,   -- e.g. 'pmos_servicing.loans'
  data_column         VARCHAR(255) NOT NULL,   -- e.g. 'current_balance'
  data_type           VARCHAR(100),            -- e.g. 'DECIMAL(12,2)'
  is_pk               BOOLEAN NOT NULL DEFAULT FALSE,
  is_fk               BOOLEAN NOT NULL DEFAULT FALSE,
  sample_values       JSON,                    -- up to 3 non-null samples
  -- What the LLM proposed (the "automatic" mapping)
  proposed_domain     VARCHAR(100),
  proposed_entity     VARCHAR(100),
  proposed_attribute  VARCHAR(100),
  confidence          FLOAT,
  reasoning           TEXT,
  model_version       VARCHAR(100),
  -- Auditor review
  status              ENUM('AUTO_ACCEPTED','CONFIRMED','CORRECTED','REJECTED','PENDING') NOT NULL DEFAULT 'AUTO_ACCEPTED',
  auditor_domain      VARCHAR(100),            -- filled only on CONFIRMED/CORRECTED
  auditor_entity      VARCHAR(100),
  auditor_attribute   VARCHAR(100),
  auditor_note        TEXT,
  reviewed_by         VARCHAR(255),
  reviewed_at         DATETIME,
  reward_signal       FLOAT,                   -- +1.0, -0.5, -1.0 (see above)
  -- Provenance
  created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_run (run_id),
  INDEX idx_status (status),
  INDEX idx_source_asset (data_source, data_asset),
  INDEX idx_confidence (confidence),
  INDEX idx_pending (status, created_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

SELECT 'crawlers' AS tbl, COUNT(*) AS n FROM crawlers
UNION ALL SELECT 'crawl_runs', COUNT(*) FROM crawl_runs
UNION ALL SELECT 'semantic_mapping_decisions', COUNT(*) FROM semantic_mapping_decisions;
