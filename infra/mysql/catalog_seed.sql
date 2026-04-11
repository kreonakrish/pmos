-- =============================================================================
-- Seed the first crawler for Phase 1 of the Data Catalog.
--
-- Crawls pmos_servicing (the home-lending servicing schema) via MySQL.
-- Host set to host.docker.internal so the orchestrator container reaches
-- the developer's localhost MySQL. sample_rows=3 gives the LLM enough
-- signal without expensive scans; skip_sensitive hides SSN/credit_card etc.
-- =============================================================================
USE pmos;

INSERT INTO crawlers
  (crawler_id, name, description, source_type, connection, options, status)
VALUES
  ('c0000001-0000-0000-0000-servicing001',
   'MySQL — pmos_servicing',
   'Crawls the home-lending servicing schema: loans, payments, defaults, foreclosures, bankruptcies, early resolutions, risk, REDS filings, investors.',
   'MYSQL',
   JSON_OBJECT(
     'host', 'host.docker.internal',
     'port', 3306,
     'user', 'root',
     'database', 'pmos_servicing',
     'schemas', JSON_ARRAY('pmos_servicing')
   ),
   JSON_OBJECT(
     'include_views', TRUE,
     'sample_rows', 3,
     'skip_sensitive', TRUE
   ),
   'ACTIVE')
ON DUPLICATE KEY UPDATE
  connection = VALUES(connection),
  options    = VALUES(options),
  updated_at = CURRENT_TIMESTAMP;

SELECT crawler_id, name, source_type, JSON_EXTRACT(connection,'$.database') AS db, status
FROM crawlers WHERE crawler_id='c0000001-0000-0000-0000-00000servicing';
