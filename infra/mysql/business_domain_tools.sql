-- =============================================================================
-- PMOS Business-Domain Tool Registry
-- Registers one DATABASE tool per business-domain schema in pmos.tools.
-- Agents can then be granted access via pmos.agent_tools.
-- =============================================================================
USE pmos;

INSERT INTO tools
  (tool_id, name, description, tool_type, hostname, endpoint, auth_method, auth_config, status, is_dynamic)
VALUES
  ('a0000001-0000-0000-0000-00000000cmh1',
   'chase_my_home_db',
   'Read-only SQL access to the Chase My Home customer journey schema (Explore / Buy / Manage). Tables: cmh_users, cmh_explore_activity, cmh_buy_offers, cmh_manage_properties.',
   'DATABASE',
   'localhost:3306',
   'mysql://localhost:3306/pmos_chase_my_home',
   'BASIC',
   JSON_OBJECT('database','pmos_chase_my_home','user','pmos_reader','permission','READ_ONLY'),
   'ACTIVE', FALSE),

  ('a0000002-0000-0000-0000-00000000mkt1',
   'marketing_db',
   'Read-only SQL access to the Marketing schema. Tables: marketing_campaigns, marketing_leads, marketing_attribution.',
   'DATABASE',
   'localhost:3306',
   'mysql://localhost:3306/pmos_marketing',
   'BASIC',
   JSON_OBJECT('database','pmos_marketing','user','pmos_reader','permission','READ_ONLY'),
   'ACTIVE', FALSE),

  ('a0000003-0000-0000-0000-00000000sls1',
   'sales_db',
   'Read-only SQL access to the Sales schema (loan officers, leads, pipeline, commissions). Tables: sales_loan_officers, sales_leads, sales_pipeline, sales_commissions.',
   'DATABASE',
   'localhost:3306',
   'mysql://localhost:3306/pmos_sales',
   'BASIC',
   JSON_OBJECT('database','pmos_sales','user','pmos_reader','permission','READ_ONLY'),
   'ACTIVE', FALSE),

  ('a0000004-0000-0000-0000-00000000ocn1',
   'origination_consumer_db',
   'Read-only SQL access to the direct-to-consumer origination schema. Tables: consumer_applications, consumer_underwriting, consumer_disclosures, consumer_closings.',
   'DATABASE',
   'localhost:3306',
   'mysql://localhost:3306/pmos_origination_consumer',
   'BASIC',
   JSON_OBJECT('database','pmos_origination_consumer','user','pmos_reader','permission','READ_ONLY'),
   'ACTIVE', FALSE),

  ('a0000005-0000-0000-0000-00000000ocr1',
   'origination_correspondent_db',
   'Read-only SQL access to the correspondent origination schema (partner-lender purchases). Tables: correspondent_lenders, correspondent_purchases, correspondent_due_diligence.',
   'DATABASE',
   'localhost:3306',
   'mysql://localhost:3306/pmos_origination_correspondent',
   'BASIC',
   JSON_OBJECT('database','pmos_origination_correspondent','user','pmos_reader','permission','READ_ONLY'),
   'ACTIVE', FALSE),

  ('a0000006-0000-0000-0000-00000000svc1',
   'servicing_db',
   'Read-only SQL access to the Servicing schema (loans, payments, defaults, early resolutions, bankruptcies, foreclosures, risk, REDS regulatory filings, investors). Tables: investors, loans, payments, defaults, early_resolutions, bankruptcies, foreclosures, risk_assessments, reds_filings.',
   'DATABASE',
   'localhost:3306',
   'mysql://localhost:3306/pmos_servicing',
   'BASIC',
   JSON_OBJECT('database','pmos_servicing','user','pmos_reader','permission','READ_ONLY'),
   'ACTIVE', FALSE)
ON DUPLICATE KEY UPDATE
  description = VALUES(description),
  endpoint    = VALUES(endpoint),
  auth_config = VALUES(auth_config),
  status      = VALUES(status);

SELECT tool_id, name, tool_type, endpoint, status FROM tools
WHERE name IN ('chase_my_home_db','marketing_db','sales_db',
               'origination_consumer_db','origination_correspondent_db','servicing_db');
