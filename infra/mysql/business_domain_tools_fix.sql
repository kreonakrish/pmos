-- =============================================================================
-- Fixes for business-domain DATABASE tools registered earlier.
--
-- Problem 1 (credentials): auth_config.user="pmos_reader" was overriding the
--   default MySQL user in agent-mgmt/toolExecutor.ts, but pmos_reader doesn't
--   exist. Rewrite auth_config to keep only the `database` hint so the
--   container's root credentials are used.
--
-- Problem 2 (schema discovery): the LLM was guessing column names
--   (`borrowers`, `borrower_id`, `current_principal_balance`) because the
--   description didn't spell out the real layout. Put a compact table+column
--   reference in the description so the agent generates correct SQL on the
--   first try.
-- =============================================================================
USE pmos;

UPDATE tools SET
  description = 'Read-only SQL against the Chase My Home customer journey (Explore / Buy / Manage) schema. Tables and key columns:\n  cmh_users(user_id PK, email, full_name, signup_date, journey_stage ENUM[EXPLORE/BUY/MANAGE], fico_estimate, household_income)\n  cmh_explore_activity(activity_id PK, user_id FK, activity_type, property_zip, property_price, activity_date)\n  cmh_buy_offers(offer_id PK, user_id FK, property_address, offer_amount, offer_date, status ENUM[SUBMITTED/ACCEPTED/REJECTED/WITHDRAWN/CLOSED])\n  cmh_manage_properties(property_id PK, user_id FK, address, current_value, loan_id -> pmos_servicing.loans, enrolled_date)',
  auth_config = JSON_OBJECT('database','pmos_chase_my_home','permission','READ_ONLY')
WHERE name='chase_my_home_db';

UPDATE tools SET
  description = 'Read-only SQL against the Marketing schema. Tables and key columns:\n  marketing_campaigns(campaign_id PK, name, channel ENUM[EMAIL/PAID_SOCIAL/SEARCH/DIRECT_MAIL/EVENT/REFERRAL], start_date, end_date, budget, status)\n  marketing_leads(lead_id PK, campaign_id FK, cmh_user_id -> pmos_chase_my_home.cmh_users, email, captured_date, lead_score)\n  marketing_attribution(attrib_id PK, lead_id FK, touchpoint, channel, touch_date, weight)',
  auth_config = JSON_OBJECT('database','pmos_marketing','permission','READ_ONLY')
WHERE name='marketing_db';

UPDATE tools SET
  description = 'Read-only SQL against the Sales schema (loan officers, leads, pipeline, commissions). Tables and key columns:\n  sales_loan_officers(officer_id PK, full_name, region, hire_date, status ENUM[ACTIVE/LEAVE/TERMINATED], ytd_volume)\n  sales_leads(lead_id PK, marketing_lead_id -> pmos_marketing.marketing_leads, customer_name, customer_email, source, estimated_loan, lead_date, status ENUM[NEW/QUALIFIED/NURTURE/CONVERTED/LOST])\n  sales_pipeline(pipeline_id PK, lead_id FK, officer_id FK, stage ENUM[PROSPECT/QUALIFIED/APPLICATION/UNDERWRITING/CLOSING/FUNDED/LOST], expected_close, expected_value)\n  sales_commissions(commission_id PK, pipeline_id FK, officer_id FK, amount, paid_date, status ENUM[ACCRUED/PAID/CLAWBACK])',
  auth_config = JSON_OBJECT('database','pmos_sales','permission','READ_ONLY')
WHERE name='sales_db';

UPDATE tools SET
  description = 'Read-only SQL against the direct-to-consumer origination schema. Tables and key columns:\n  consumer_applications(application_id PK, sales_lead_id -> pmos_sales.sales_leads, customer_name, email, ssn_last4, application_date, loan_amount, property_value, fico_score, status ENUM[SUBMITTED/PROCESSING/APPROVED/DENIED/WITHDRAWN], channel)\n  consumer_underwriting(underwriting_id PK, application_id FK, underwriter, dti_ratio, ltv_ratio, decision ENUM[APPROVE/APPROVE_WITH_CONDITIONS/SUSPEND/DENY], decision_date, notes)\n  consumer_disclosures(disclosure_id PK, application_id FK, disclosure_type ENUM[LE/CD/TIL/GFE/HOI/PRIVACY], sent_date, acknowledged_date)\n  consumer_closings(closing_id PK, application_id FK, scheduled_date, actual_date, location, status ENUM[SCHEDULED/COMPLETED/RESCHEDULED/CANCELLED], funded_loan_id -> pmos_servicing.loans)',
  auth_config = JSON_OBJECT('database','pmos_origination_consumer','permission','READ_ONLY')
WHERE name='origination_consumer_db';

UPDATE tools SET
  description = 'Read-only SQL against the correspondent origination schema (partner-lender loan purchases). Tables and key columns:\n  correspondent_lenders(lender_id PK, name, agreement_date, tier ENUM[PLATINUM/GOLD/SILVER/BRONZE], status, ytd_volume)\n  correspondent_purchases(purchase_id PK, lender_id FK, loan_amount, purchase_date, premium_pct, status ENUM[PENDING/PURCHASED/REJECTED/REPURCHASED], funded_loan_id -> pmos_servicing.loans)\n  correspondent_due_diligence(dd_id PK, purchase_id FK, reviewer, status ENUM[PASS/PASS_WITH_FINDINGS/FAIL], findings, completed_date)',
  auth_config = JSON_OBJECT('database','pmos_origination_correspondent','permission','READ_ONLY')
WHERE name='origination_correspondent_db';

UPDATE tools SET
  description = 'Read-only SQL against the Servicing schema (loans, payments, defaults, early resolutions, bankruptcies, foreclosures, risk, REDS regulatory filings, investors). Tables and key columns:\n  investors(investor_id PK, name, investor_type ENUM[GSE/PRIVATE/BANK/REIT/GOVT], contact_email, total_holdings, onboarded_date)\n  loans(loan_id PK, investor_id FK, origination_source ENUM[CONSUMER/CORRESPONDENT], origination_ref, borrower_name, property_address, original_balance, current_balance, interest_rate, term_months, origination_date, status ENUM[CURRENT/DELINQUENT/DEFAULT/BANKRUPTCY/FORECLOSURE/PAID_OFF/REO])\n  payments(payment_id PK, loan_id FK, payment_date, scheduled_amount, paid_amount, principal, interest, escrow, status ENUM[ON_TIME/LATE/MISSED/PARTIAL/NSF])\n  defaults(default_id PK, loan_id FK, default_date, days_past_due, reason, status ENUM[NEW/WORKOUT/RESOLVED/ESCALATED])\n  early_resolutions(resolution_id PK, loan_id FK, resolution_type ENUM[FORBEARANCE/MODIFICATION/REPAYMENT_PLAN/DEED_IN_LIEU/SHORT_SALE], agreement_date, terms, status)\n  bankruptcies(bankruptcy_id PK, loan_id FK, chapter ENUM[CH7/CH11/CH13], filing_date, attorney, status ENUM[FILED/DISCHARGED/DISMISSED/CONVERTED])\n  foreclosures(foreclosure_id PK, loan_id FK, initiated_date, sale_date, sale_amount, status ENUM[INITIATED/HALTED/SOLD/REO])\n  risk_assessments(assessment_id PK, loan_id FK, assessment_date, risk_score, risk_band ENUM[LOW/MODERATE/HIGH/SEVERE], factors JSON)\n  reds_filings(filing_id PK, loan_id FK, regulator ENUM[CFPB/HUD/FHFA/OCC/STATE_AG], filing_type, filing_date, status ENUM[DRAFT/SUBMITTED/ACCEPTED/REJECTED/AMENDED])',
  auth_config = JSON_OBJECT('database','pmos_servicing','permission','READ_ONLY')
WHERE name='servicing_db';

SELECT name, JSON_EXTRACT(auth_config,'$.database') AS db, LEFT(description,80) AS description_preview
FROM tools
WHERE name IN ('chase_my_home_db','marketing_db','sales_db',
               'origination_consumer_db','origination_correspondent_db','servicing_db')
ORDER BY name;
