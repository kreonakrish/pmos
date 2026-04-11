-- =============================================================================
-- PMOS Business Domain Schemas — Home Lending Lifecycle
-- MySQL 8.x — Run via: mysql -u root -p < business_domains.sql
--
-- Six logical databases model the full loan lifecycle:
--   pmos_chase_my_home          — Explore / Buy / Manage customer journey
--   pmos_marketing              — campaigns, leads, attribution
--   pmos_sales                  — leads, loan officers, pipeline, commissions
--   pmos_origination_consumer   — direct-to-consumer applications
--   pmos_origination_correspondent — correspondent lender purchases
--   pmos_servicing              — loans, payments, defaults, FC, BK, REDS, investors
--
-- Cross-schema columns are stored as plain VARCHARs (no enforced FK across DBs)
-- but values are kept consistent at seed time so joins work end-to-end.
-- All tables use utf8mb4 + InnoDB.  Each table loaded with 10 sample rows.
-- =============================================================================


-- =============================================================================
-- 1. CHASE MY HOME — Explore / Buy / Manage
-- =============================================================================
CREATE DATABASE IF NOT EXISTS pmos_chase_my_home CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE pmos_chase_my_home;

CREATE TABLE IF NOT EXISTS cmh_users (
  user_id        VARCHAR(20) PRIMARY KEY,
  email          VARCHAR(255) NOT NULL UNIQUE,
  full_name      VARCHAR(255) NOT NULL,
  signup_date    DATE NOT NULL,
  journey_stage  ENUM('EXPLORE','BUY','MANAGE') NOT NULL,
  fico_estimate  INT,
  household_income DECIMAL(12,2),
  created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS cmh_explore_activity (
  activity_id    VARCHAR(20) PRIMARY KEY,
  user_id        VARCHAR(20) NOT NULL,
  activity_type  ENUM('SEARCH','VIEW_LISTING','SAVE','AFFORDABILITY_CALC','RATE_QUOTE') NOT NULL,
  property_zip   VARCHAR(10),
  property_price DECIMAL(12,2),
  activity_date  DATETIME NOT NULL,
  CONSTRAINT fk_cmh_act_user FOREIGN KEY (user_id) REFERENCES cmh_users(user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS cmh_buy_offers (
  offer_id       VARCHAR(20) PRIMARY KEY,
  user_id        VARCHAR(20) NOT NULL,
  property_address VARCHAR(255) NOT NULL,
  offer_amount   DECIMAL(12,2) NOT NULL,
  offer_date     DATE NOT NULL,
  status         ENUM('SUBMITTED','ACCEPTED','REJECTED','WITHDRAWN','CLOSED') NOT NULL,
  CONSTRAINT fk_cmh_offer_user FOREIGN KEY (user_id) REFERENCES cmh_users(user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS cmh_manage_properties (
  property_id    VARCHAR(20) PRIMARY KEY,
  user_id        VARCHAR(20) NOT NULL,
  address        VARCHAR(255) NOT NULL,
  current_value  DECIMAL(12,2) NOT NULL,
  loan_id        VARCHAR(20),  -- cross-ref to pmos_servicing.loans
  enrolled_date  DATE NOT NULL,
  CONSTRAINT fk_cmh_prop_user FOREIGN KEY (user_id) REFERENCES cmh_users(user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO cmh_users VALUES
('U0001','alice.nguyen@example.com','Alice Nguyen','2025-01-12','MANAGE',782,185000,DEFAULT),
('U0002','bob.patel@example.com','Bob Patel','2025-02-03','MANAGE',741,142000,DEFAULT),
('U0003','carla.diaz@example.com','Carla Diaz','2025-03-19','BUY',709,98000,DEFAULT),
('U0004','derek.wong@example.com','Derek Wong','2025-04-22','BUY',756,167500,DEFAULT),
('U0005','elena.romero@example.com','Elena Romero','2025-05-04','EXPLORE',688,76000,DEFAULT),
('U0006','farah.kahn@example.com','Farah Kahn','2025-06-15','EXPLORE',721,112000,DEFAULT),
('U0007','george.miller@example.com','George Miller','2025-07-08','MANAGE',803,221000,DEFAULT),
('U0008','hannah.lee@example.com','Hannah Lee','2025-08-30','BUY',665,88000,DEFAULT),
('U0009','ian.olsen@example.com','Ian Olsen','2025-09-12','MANAGE',775,154000,DEFAULT),
('U0010','julia.fischer@example.com','Julia Fischer','2025-10-21','EXPLORE',693,103000,DEFAULT);

INSERT INTO cmh_explore_activity VALUES
('A0001','U0005','SEARCH','78701',NULL,'2026-01-04 09:12:00'),
('A0002','U0005','AFFORDABILITY_CALC','78701',420000,'2026-01-04 09:25:00'),
('A0003','U0006','VIEW_LISTING','60614',512000,'2026-01-08 18:43:00'),
('A0004','U0006','SAVE','60614',512000,'2026-01-08 18:51:00'),
('A0005','U0010','RATE_QUOTE','94110',785000,'2026-01-22 11:02:00'),
('A0006','U0003','VIEW_LISTING','30303',289000,'2026-02-12 15:30:00'),
('A0007','U0003','AFFORDABILITY_CALC','30303',289000,'2026-02-12 15:34:00'),
('A0008','U0004','SEARCH','98101',NULL,'2026-02-25 08:09:00'),
('A0009','U0004','VIEW_LISTING','98101',640000,'2026-02-25 08:18:00'),
('A0010','U0008','RATE_QUOTE','33101',355000,'2026-03-02 12:47:00');

INSERT INTO cmh_buy_offers VALUES
('O0001','U0003','142 Peachtree Ln, Atlanta GA 30303',285000,'2026-02-20','ACCEPTED'),
('O0002','U0004','881 Pike St, Seattle WA 98101',638000,'2026-03-01','ACCEPTED'),
('O0003','U0008','22 Ocean Dr, Miami FL 33101',352000,'2026-03-08','SUBMITTED'),
('O0004','U0003','142 Peachtree Ln, Atlanta GA 30303',280000,'2026-02-15','REJECTED'),
('O0005','U0004','881 Pike St, Seattle WA 98101',625000,'2026-02-26','REJECTED'),
('O0006','U0008','22 Ocean Dr, Miami FL 33101',345000,'2026-03-04','REJECTED'),
('O0007','U0003','17 Magnolia Ct, Atlanta GA 30303',310000,'2026-01-30','WITHDRAWN'),
('O0008','U0004','45 Elliott Ave, Seattle WA 98101',598000,'2026-02-12','WITHDRAWN'),
('O0009','U0008','9 Bay Front, Miami FL 33101',360000,'2026-02-28','WITHDRAWN'),
('O0010','U0003','142 Peachtree Ln, Atlanta GA 30303',285000,'2026-03-15','CLOSED');

INSERT INTO cmh_manage_properties VALUES
('P0001','U0001','55 Cedar St, Austin TX 78701',512000,'L0001','2025-01-20'),
('P0002','U0002','812 Lakeview Rd, Chicago IL 60614',388000,'L0002','2025-02-15'),
('P0003','U0007','3 Hillcrest Dr, Boston MA 02108',745000,'L0003','2025-07-15'),
('P0004','U0009','920 Maple Ave, Denver CO 80202',488000,'L0004','2025-09-19'),
('P0005','U0001','55 Cedar St, Austin TX 78701',512000,'L0005','2025-01-20'),
('P0006','U0002','812 Lakeview Rd, Chicago IL 60614',388000,'L0006','2025-02-15'),
('P0007','U0007','3 Hillcrest Dr, Boston MA 02108',745000,'L0007','2025-07-15'),
('P0008','U0009','920 Maple Ave, Denver CO 80202',488000,'L0008','2025-09-19'),
('P0009','U0001','21 Pecan Ln, Austin TX 78701',295000,'L0009','2025-11-01'),
('P0010','U0007','77 Beacon Hill, Boston MA 02108',1110000,'L0010','2025-12-04');


-- =============================================================================
-- 2. MARKETING — campaigns, leads, attribution
-- =============================================================================
CREATE DATABASE IF NOT EXISTS pmos_marketing CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE pmos_marketing;

CREATE TABLE IF NOT EXISTS marketing_campaigns (
  campaign_id    VARCHAR(20) PRIMARY KEY,
  name           VARCHAR(255) NOT NULL,
  channel        ENUM('EMAIL','PAID_SOCIAL','SEARCH','DIRECT_MAIL','EVENT','REFERRAL') NOT NULL,
  start_date     DATE NOT NULL,
  end_date       DATE,
  budget         DECIMAL(12,2) NOT NULL,
  status         ENUM('PLANNED','ACTIVE','PAUSED','COMPLETED') NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS marketing_leads (
  lead_id        VARCHAR(20) PRIMARY KEY,
  campaign_id    VARCHAR(20) NOT NULL,
  cmh_user_id    VARCHAR(20),  -- cross-ref to pmos_chase_my_home.cmh_users
  email          VARCHAR(255) NOT NULL,
  captured_date  DATE NOT NULL,
  lead_score     INT NOT NULL,
  CONSTRAINT fk_mkt_lead_camp FOREIGN KEY (campaign_id) REFERENCES marketing_campaigns(campaign_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS marketing_attribution (
  attrib_id      VARCHAR(20) PRIMARY KEY,
  lead_id        VARCHAR(20) NOT NULL,
  touchpoint     VARCHAR(100) NOT NULL,
  channel        VARCHAR(50) NOT NULL,
  touch_date     DATETIME NOT NULL,
  weight         DECIMAL(4,3) NOT NULL,
  CONSTRAINT fk_mkt_attr_lead FOREIGN KEY (lead_id) REFERENCES marketing_leads(lead_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO marketing_campaigns VALUES
('C0001','Spring Refi Push 2026','EMAIL','2026-02-01','2026-04-30',75000,'ACTIVE'),
('C0002','First-Time Buyer Search','SEARCH','2026-01-15','2026-06-30',125000,'ACTIVE'),
('C0003','HomeLink Webinar Series','EVENT','2026-03-01','2026-03-31',32000,'COMPLETED'),
('C0004','Q1 Direct Mail Burst','DIRECT_MAIL','2026-01-05','2026-02-15',58000,'COMPLETED'),
('C0005','Social Discovery — Millennials','PAID_SOCIAL','2026-02-10','2026-05-10',95000,'ACTIVE'),
('C0006','Loyalty Refer-a-Friend','REFERRAL','2025-12-01','2026-12-01',40000,'ACTIVE'),
('C0007','Veterans Day Outreach','EMAIL','2025-11-01','2025-11-30',18000,'COMPLETED'),
('C0008','Reverse-Mortgage Awareness','SEARCH','2026-03-15','2026-09-15',62000,'ACTIVE'),
('C0009','HELOC for Home Improvement','PAID_SOCIAL','2026-04-01','2026-07-31',48000,'PLANNED'),
('C0010','Correspondent Partner Drive','EVENT','2026-02-20','2026-04-20',27000,'ACTIVE');

INSERT INTO marketing_leads VALUES
('L0001','C0002','U0003','carla.diaz@example.com','2026-01-22',82),
('L0002','C0002','U0004','derek.wong@example.com','2026-01-29',74),
('L0003','C0001','U0005','elena.romero@example.com','2026-02-08',55),
('L0004','C0005','U0006','farah.kahn@example.com','2026-02-14',61),
('L0005','C0008','U0010','julia.fischer@example.com','2026-02-19',47),
('L0006','C0003','U0008','hannah.lee@example.com','2026-03-05',68),
('L0007','C0001','U0001','alice.nguyen@example.com','2026-02-12',91),
('L0008','C0006','U0002','bob.patel@example.com','2026-01-04',78),
('L0009','C0007','U0007','george.miller@example.com','2025-11-09',88),
('L0010','C0004','U0009','ian.olsen@example.com','2026-01-18',72);

INSERT INTO marketing_attribution VALUES
('AT0001','L0001','google_search_buy','SEARCH','2026-01-20 14:02:00',0.500),
('AT0002','L0001','email_followup_a','EMAIL','2026-01-22 09:14:00',0.500),
('AT0003','L0002','google_search_buy','SEARCH','2026-01-27 11:50:00',0.700),
('AT0004','L0003','spring_refi_email','EMAIL','2026-02-08 06:30:00',1.000),
('AT0005','L0004','fb_carousel_millennial','PAID_SOCIAL','2026-02-14 19:22:00',1.000),
('AT0006','L0005','reverse_mortgage_ads','SEARCH','2026-02-19 10:09:00',1.000),
('AT0007','L0006','homelink_webinar_3','EVENT','2026-03-05 13:00:00',1.000),
('AT0008','L0007','spring_refi_email','EMAIL','2026-02-12 07:45:00',1.000),
('AT0009','L0008','referral_friend','REFERRAL','2026-01-04 16:18:00',1.000),
('AT0010','L0009','vets_day_outreach','EMAIL','2025-11-09 08:00:00',1.000);


-- =============================================================================
-- 3. SALES — leads, loan officers, pipeline, commissions
-- =============================================================================
CREATE DATABASE IF NOT EXISTS pmos_sales CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE pmos_sales;

CREATE TABLE IF NOT EXISTS sales_loan_officers (
  officer_id     VARCHAR(20) PRIMARY KEY,
  full_name      VARCHAR(255) NOT NULL,
  region         VARCHAR(50) NOT NULL,
  hire_date      DATE NOT NULL,
  status         ENUM('ACTIVE','LEAVE','TERMINATED') NOT NULL,
  ytd_volume     DECIMAL(14,2) NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sales_leads (
  lead_id        VARCHAR(20) PRIMARY KEY,
  marketing_lead_id VARCHAR(20),  -- cross-ref to pmos_marketing.marketing_leads
  customer_name  VARCHAR(255) NOT NULL,
  customer_email VARCHAR(255) NOT NULL,
  source         ENUM('MARKETING','REFERRAL','BRANCH','WEBSITE','CALLBACK') NOT NULL,
  estimated_loan DECIMAL(12,2) NOT NULL,
  lead_date      DATE NOT NULL,
  status         ENUM('NEW','QUALIFIED','NURTURE','CONVERTED','LOST') NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sales_pipeline (
  pipeline_id    VARCHAR(20) PRIMARY KEY,
  lead_id        VARCHAR(20) NOT NULL,
  officer_id     VARCHAR(20) NOT NULL,
  stage          ENUM('PROSPECT','QUALIFIED','APPLICATION','UNDERWRITING','CLOSING','FUNDED','LOST') NOT NULL,
  expected_close DATE,
  expected_value DECIMAL(12,2),
  CONSTRAINT fk_sp_lead FOREIGN KEY (lead_id) REFERENCES sales_leads(lead_id),
  CONSTRAINT fk_sp_officer FOREIGN KEY (officer_id) REFERENCES sales_loan_officers(officer_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sales_commissions (
  commission_id  VARCHAR(20) PRIMARY KEY,
  pipeline_id    VARCHAR(20) NOT NULL,
  officer_id     VARCHAR(20) NOT NULL,
  amount         DECIMAL(10,2) NOT NULL,
  paid_date      DATE,
  status         ENUM('ACCRUED','PAID','CLAWBACK') NOT NULL,
  CONSTRAINT fk_sc_pipeline FOREIGN KEY (pipeline_id) REFERENCES sales_pipeline(pipeline_id),
  CONSTRAINT fk_sc_officer FOREIGN KEY (officer_id) REFERENCES sales_loan_officers(officer_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO sales_loan_officers VALUES
('LO001','Maria Sanchez','Southwest','2019-04-12','ACTIVE',12450000),
('LO002','Tom Hughes','Northeast','2017-09-01','ACTIVE',9870000),
('LO003','Priya Iyer','Southeast','2021-02-22','ACTIVE',6200000),
('LO004','Kevin Brown','Midwest','2015-06-30','ACTIVE',15200000),
('LO005','Sara Kim','West','2020-11-14','LEAVE',4100000),
('LO006','David Foster','South','2018-08-19','ACTIVE',8800000),
('LO007','Linda Wei','Pacific','2022-01-09','ACTIVE',5100000),
('LO008','Aaron Walsh','Mountain','2016-03-25','ACTIVE',11000000),
('LO009','Nina Park','Atlantic','2019-10-08','TERMINATED',3300000),
('LO010','Carlos Ortega','Gulf','2023-05-17','ACTIVE',2700000);

INSERT INTO sales_leads VALUES
('SL0001','L0001','Carla Diaz','carla.diaz@example.com','MARKETING',285000,'2026-01-25','CONVERTED'),
('SL0002','L0002','Derek Wong','derek.wong@example.com','MARKETING',640000,'2026-02-01','CONVERTED'),
('SL0003','L0003','Elena Romero','elena.romero@example.com','MARKETING',180000,'2026-02-10','NURTURE'),
('SL0004','L0004','Farah Kahn','farah.kahn@example.com','MARKETING',420000,'2026-02-16','QUALIFIED'),
('SL0005','L0005','Julia Fischer','julia.fischer@example.com','MARKETING',520000,'2026-02-22','NEW'),
('SL0006','L0006','Hannah Lee','hannah.lee@example.com','MARKETING',355000,'2026-03-08','CONVERTED'),
('SL0007','L0007','Alice Nguyen','alice.nguyen@example.com','MARKETING',190000,'2026-02-15','CONVERTED'),
('SL0008','L0008','Bob Patel','bob.patel@example.com','REFERRAL',150000,'2026-01-08','CONVERTED'),
('SL0009','L0009','George Miller','george.miller@example.com','BRANCH',745000,'2025-11-12','CONVERTED'),
('SL0010','L0010','Ian Olsen','ian.olsen@example.com','WEBSITE',488000,'2026-01-21','CONVERTED');

INSERT INTO sales_pipeline VALUES
('SP0001','SL0001','LO003','FUNDED','2026-03-15',285000),
('SP0002','SL0002','LO007','FUNDED','2026-03-25',640000),
('SP0003','SL0003','LO001','APPLICATION','2026-05-01',180000),
('SP0004','SL0004','LO001','UNDERWRITING','2026-04-15',420000),
('SP0005','SL0005','LO005','PROSPECT','2026-06-01',520000),
('SP0006','SL0006','LO006','FUNDED','2026-04-05',355000),
('SP0007','SL0007','LO004','FUNDED','2026-03-10',190000),
('SP0008','SL0008','LO004','FUNDED','2026-02-08',150000),
('SP0009','SL0009','LO002','FUNDED','2025-12-10',745000),
('SP0010','SL0010','LO008','FUNDED','2026-02-22',488000);

INSERT INTO sales_commissions VALUES
('SC0001','SP0001','LO003',2850,'2026-03-30','PAID'),
('SC0002','SP0002','LO007',6400,'2026-04-05','PAID'),
('SC0003','SP0003','LO001',1800,NULL,'ACCRUED'),
('SC0004','SP0004','LO001',4200,NULL,'ACCRUED'),
('SC0005','SP0005','LO005',5200,NULL,'ACCRUED'),
('SC0006','SP0006','LO006',3550,'2026-04-15','PAID'),
('SC0007','SP0007','LO004',1900,'2026-03-22','PAID'),
('SC0008','SP0008','LO004',1500,'2026-02-20','PAID'),
('SC0009','SP0009','LO002',7450,'2025-12-30','PAID'),
('SC0010','SP0010','LO008',4880,'2026-03-05','PAID');


-- =============================================================================
-- 4. ORIGINATION — CONSUMER (direct-to-consumer)
-- =============================================================================
CREATE DATABASE IF NOT EXISTS pmos_origination_consumer CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE pmos_origination_consumer;

CREATE TABLE IF NOT EXISTS consumer_applications (
  application_id VARCHAR(20) PRIMARY KEY,
  sales_lead_id  VARCHAR(20),  -- cross-ref to pmos_sales.sales_leads
  customer_name  VARCHAR(255) NOT NULL,
  email          VARCHAR(255) NOT NULL,
  ssn_last4      CHAR(4) NOT NULL,
  application_date DATE NOT NULL,
  loan_amount    DECIMAL(12,2) NOT NULL,
  property_value DECIMAL(12,2) NOT NULL,
  fico_score     INT NOT NULL,
  status         ENUM('SUBMITTED','PROCESSING','APPROVED','DENIED','WITHDRAWN') NOT NULL,
  channel        ENUM('WEB','MOBILE','CALL_CENTER','BRANCH') NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS consumer_underwriting (
  underwriting_id VARCHAR(20) PRIMARY KEY,
  application_id VARCHAR(20) NOT NULL,
  underwriter    VARCHAR(255) NOT NULL,
  dti_ratio      DECIMAL(5,2) NOT NULL,
  ltv_ratio      DECIMAL(5,2) NOT NULL,
  decision       ENUM('APPROVE','APPROVE_WITH_CONDITIONS','SUSPEND','DENY') NOT NULL,
  decision_date  DATE NOT NULL,
  notes          TEXT,
  CONSTRAINT fk_uw_app FOREIGN KEY (application_id) REFERENCES consumer_applications(application_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS consumer_disclosures (
  disclosure_id  VARCHAR(20) PRIMARY KEY,
  application_id VARCHAR(20) NOT NULL,
  disclosure_type ENUM('LE','CD','TIL','GFE','HOI','PRIVACY') NOT NULL,
  sent_date      DATE NOT NULL,
  acknowledged_date DATE,
  CONSTRAINT fk_dis_app FOREIGN KEY (application_id) REFERENCES consumer_applications(application_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS consumer_closings (
  closing_id     VARCHAR(20) PRIMARY KEY,
  application_id VARCHAR(20) NOT NULL,
  scheduled_date DATE NOT NULL,
  actual_date    DATE,
  location       VARCHAR(255),
  status         ENUM('SCHEDULED','COMPLETED','RESCHEDULED','CANCELLED') NOT NULL,
  funded_loan_id VARCHAR(20),  -- cross-ref to pmos_servicing.loans
  CONSTRAINT fk_cls_app FOREIGN KEY (application_id) REFERENCES consumer_applications(application_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO consumer_applications VALUES
('APC0001','SL0001','Carla Diaz','carla.diaz@example.com','3344','2026-01-28',285000,310000,709,'APPROVED','WEB'),
('APC0002','SL0002','Derek Wong','derek.wong@example.com','5577','2026-02-04',640000,720000,756,'APPROVED','MOBILE'),
('APC0003','SL0006','Hannah Lee','hannah.lee@example.com','9081','2026-03-12',355000,390000,665,'APPROVED','WEB'),
('APC0004','SL0007','Alice Nguyen','alice.nguyen@example.com','7012','2026-02-18',190000,512000,782,'APPROVED','BRANCH'),
('APC0005','SL0008','Bob Patel','bob.patel@example.com','4490','2026-01-15',150000,388000,741,'APPROVED','BRANCH'),
('APC0006','SL0010','Ian Olsen','ian.olsen@example.com','6701','2026-01-25',488000,540000,775,'APPROVED','MOBILE'),
('APC0007','SL0004','Farah Kahn','farah.kahn@example.com','1158','2026-02-20',420000,460000,721,'PROCESSING','CALL_CENTER'),
('APC0008','SL0003','Elena Romero','elena.romero@example.com','8845','2026-02-15',180000,205000,688,'SUBMITTED','WEB'),
('APC0009','SL0005','Julia Fischer','julia.fischer@example.com','2233','2026-02-25',520000,580000,693,'PROCESSING','WEB'),
('APC0010','SL0009','George Miller','george.miller@example.com','3309','2025-11-15',745000,830000,803,'APPROVED','BRANCH');

INSERT INTO consumer_underwriting VALUES
('UWC0001','APC0001','Sandra Reyes',32.5,91.9,'APPROVE','2026-02-10','Strong reserves'),
('UWC0002','APC0002','Mark Liu',28.0,88.9,'APPROVE','2026-02-15','High income, low DTI'),
('UWC0003','APC0003','Sandra Reyes',38.2,91.0,'APPROVE_WITH_CONDITIONS','2026-03-22','Need updated W2'),
('UWC0004','APC0004','Tony Esposito',24.0,37.1,'APPROVE','2026-02-25','Excellent credit'),
('UWC0005','APC0005','Tony Esposito',26.5,38.7,'APPROVE','2026-01-25','Repeat customer'),
('UWC0006','APC0006','Mark Liu',31.0,90.4,'APPROVE','2026-02-04','Solid file'),
('UWC0007','APC0007','Sandra Reyes',41.5,91.3,'SUSPEND','2026-03-01','Need recent paystubs'),
('UWC0008','APC0008','Tony Esposito',36.0,87.8,'SUSPEND','2026-02-22','Credit explanation needed'),
('UWC0009','APC0009','Mark Liu',34.0,89.7,'APPROVE_WITH_CONDITIONS','2026-03-08','Pending appraisal'),
('UWC0010','APC0010','Sandra Reyes',22.0,89.8,'APPROVE','2025-11-25','High net worth');

INSERT INTO consumer_disclosures VALUES
('DSC0001','APC0001','LE','2026-01-29','2026-01-30'),
('DSC0002','APC0002','LE','2026-02-05','2026-02-05'),
('DSC0003','APC0003','LE','2026-03-13','2026-03-15'),
('DSC0004','APC0004','LE','2026-02-19','2026-02-19'),
('DSC0005','APC0005','LE','2026-01-16','2026-01-16'),
('DSC0006','APC0006','LE','2026-01-26','2026-01-27'),
('DSC0007','APC0001','CD','2026-03-08','2026-03-09'),
('DSC0008','APC0002','CD','2026-03-18','2026-03-19'),
('DSC0009','APC0010','LE','2025-11-16','2025-11-17'),
('DSC0010','APC0010','CD','2025-12-01','2025-12-02');

INSERT INTO consumer_closings VALUES
('CLC0001','APC0001','2026-03-15','2026-03-15','Atlanta GA Branch','COMPLETED','L0011'),
('CLC0002','APC0002','2026-03-25','2026-03-25','Seattle WA Branch','COMPLETED','L0012'),
('CLC0003','APC0003','2026-04-05','2026-04-05','Miami FL Branch','COMPLETED','L0013'),
('CLC0004','APC0004','2026-03-10','2026-03-10','Austin TX Branch','COMPLETED','L0001'),
('CLC0005','APC0005','2026-02-08','2026-02-08','Chicago IL Branch','COMPLETED','L0002'),
('CLC0006','APC0006','2026-02-22','2026-02-22','Denver CO Branch','COMPLETED','L0004'),
('CLC0007','APC0007','2026-04-15',NULL,'Phoenix AZ Branch','SCHEDULED',NULL),
('CLC0008','APC0008','2026-04-20',NULL,'Online','SCHEDULED',NULL),
('CLC0009','APC0009','2026-04-12',NULL,'Online','RESCHEDULED',NULL),
('CLC0010','APC0010','2025-12-10','2025-12-10','Boston MA Branch','COMPLETED','L0003');


-- =============================================================================
-- 5. ORIGINATION — CORRESPONDENT (loans bought from partner lenders)
-- =============================================================================
CREATE DATABASE IF NOT EXISTS pmos_origination_correspondent CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE pmos_origination_correspondent;

CREATE TABLE IF NOT EXISTS correspondent_lenders (
  lender_id      VARCHAR(20) PRIMARY KEY,
  name           VARCHAR(255) NOT NULL,
  agreement_date DATE NOT NULL,
  tier           ENUM('PLATINUM','GOLD','SILVER','BRONZE') NOT NULL,
  status         ENUM('ACTIVE','SUSPENDED','TERMINATED') NOT NULL,
  ytd_volume     DECIMAL(14,2) NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS correspondent_purchases (
  purchase_id    VARCHAR(20) PRIMARY KEY,
  lender_id      VARCHAR(20) NOT NULL,
  loan_amount    DECIMAL(12,2) NOT NULL,
  purchase_date  DATE NOT NULL,
  premium_pct    DECIMAL(5,3) NOT NULL,
  status         ENUM('PENDING','PURCHASED','REJECTED','REPURCHASED') NOT NULL,
  funded_loan_id VARCHAR(20),  -- cross-ref to pmos_servicing.loans
  CONSTRAINT fk_corr_pur_lender FOREIGN KEY (lender_id) REFERENCES correspondent_lenders(lender_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS correspondent_due_diligence (
  dd_id          VARCHAR(20) PRIMARY KEY,
  purchase_id    VARCHAR(20) NOT NULL,
  reviewer       VARCHAR(255) NOT NULL,
  status         ENUM('PASS','PASS_WITH_FINDINGS','FAIL') NOT NULL,
  findings       TEXT,
  completed_date DATE NOT NULL,
  CONSTRAINT fk_dd_pur FOREIGN KEY (purchase_id) REFERENCES correspondent_purchases(purchase_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO correspondent_lenders VALUES
('CL001','Pacific Crest Mortgage','2018-01-10','PLATINUM','ACTIVE',88000000),
('CL002','Lone Star Lending','2019-06-22','GOLD','ACTIVE',54000000),
('CL003','Northern Light Capital','2020-09-15','GOLD','ACTIVE',47000000),
('CL004','Bayview Home Loans','2017-03-08','SILVER','SUSPENDED',12000000),
('CL005','Atlas Funding Group','2021-11-04','SILVER','ACTIVE',31000000),
('CL006','Heritage Bancorp','2016-05-19','PLATINUM','ACTIVE',102000000),
('CL007','Summit Mortgage Corp','2022-02-28','BRONZE','ACTIVE',8500000),
('CL008','Greenfield Lending','2019-12-12','GOLD','ACTIVE',39000000),
('CL009','Cascade Home Loans','2015-08-01','PLATINUM','ACTIVE',78000000),
('CL010','Riverstone Mortgage','2023-04-17','BRONZE','TERMINATED',2400000);

INSERT INTO correspondent_purchases VALUES
('CP0001','CL001',412000,'2025-08-12',1.250,'PURCHASED','L0005'),
('CP0002','CL002',265000,'2025-09-04',1.000,'PURCHASED','L0006'),
('CP0003','CL003',805000,'2025-09-30',1.500,'PURCHASED','L0007'),
('CP0004','CL006',192000,'2025-10-22',0.875,'PURCHASED','L0008'),
('CP0005','CL005',345000,'2025-11-19',1.125,'PURCHASED','L0009'),
('CP0006','CL009',588000,'2025-12-08',1.375,'PURCHASED','L0010'),
('CP0007','CL001',278000,'2026-01-15',1.250,'PURCHASED','L0014'),
('CP0008','CL008',429000,'2026-02-02',1.150,'PENDING',NULL),
('CP0009','CL004',315000,'2026-02-20',1.000,'REJECTED',NULL),
('CP0010','CL007',158000,'2026-03-01',0.750,'PENDING',NULL);

INSERT INTO correspondent_due_diligence VALUES
('DD0001','CP0001','Olivia Bennett','PASS','Clean file','2025-08-15'),
('DD0002','CP0002','Robert Kim','PASS','Clean file','2025-09-08'),
('DD0003','CP0003','Olivia Bennett','PASS_WITH_FINDINGS','Missing 1 paystub','2025-10-03'),
('DD0004','CP0004','Wendy Cho','PASS','Clean file','2025-10-26'),
('DD0005','CP0005','Robert Kim','PASS','Clean file','2025-11-22'),
('DD0006','CP0006','Olivia Bennett','PASS','Investor-ready','2025-12-12'),
('DD0007','CP0007','Wendy Cho','PASS_WITH_FINDINGS','Appraisal age borderline','2026-01-18'),
('DD0008','CP0008','Robert Kim','PASS','In review','2026-02-05'),
('DD0009','CP0009','Olivia Bennett','FAIL','Income verification failed','2026-02-23'),
('DD0010','CP0010','Wendy Cho','PASS','Clean file','2026-03-04');


-- =============================================================================
-- 6. SERVICING — loans, payments, defaults, FC, BK, REDS, investors, risk
-- =============================================================================
CREATE DATABASE IF NOT EXISTS pmos_servicing CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE pmos_servicing;

CREATE TABLE IF NOT EXISTS investors (
  investor_id    VARCHAR(20) PRIMARY KEY,
  name           VARCHAR(255) NOT NULL,
  investor_type  ENUM('GSE','PRIVATE','BANK','REIT','GOVT') NOT NULL,
  contact_email  VARCHAR(255),
  total_holdings DECIMAL(14,2) NOT NULL DEFAULT 0,
  onboarded_date DATE NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS loans (
  loan_id        VARCHAR(20) PRIMARY KEY,
  investor_id    VARCHAR(20) NOT NULL,
  origination_source ENUM('CONSUMER','CORRESPONDENT') NOT NULL,
  origination_ref VARCHAR(20),  -- application_id or purchase_id
  borrower_name  VARCHAR(255) NOT NULL,
  property_address VARCHAR(255) NOT NULL,
  original_balance DECIMAL(12,2) NOT NULL,
  current_balance DECIMAL(12,2) NOT NULL,
  interest_rate  DECIMAL(5,3) NOT NULL,
  term_months    INT NOT NULL,
  origination_date DATE NOT NULL,
  status         ENUM('CURRENT','DELINQUENT','DEFAULT','BANKRUPTCY','FORECLOSURE','PAID_OFF','REO') NOT NULL,
  CONSTRAINT fk_loan_investor FOREIGN KEY (investor_id) REFERENCES investors(investor_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS payments (
  payment_id     VARCHAR(20) PRIMARY KEY,
  loan_id        VARCHAR(20) NOT NULL,
  payment_date   DATE NOT NULL,
  scheduled_amount DECIMAL(10,2) NOT NULL,
  paid_amount    DECIMAL(10,2) NOT NULL,
  principal      DECIMAL(10,2) NOT NULL,
  interest       DECIMAL(10,2) NOT NULL,
  escrow         DECIMAL(10,2) NOT NULL DEFAULT 0,
  status         ENUM('ON_TIME','LATE','MISSED','PARTIAL','NSF') NOT NULL,
  CONSTRAINT fk_pmt_loan FOREIGN KEY (loan_id) REFERENCES loans(loan_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS defaults (
  default_id     VARCHAR(20) PRIMARY KEY,
  loan_id        VARCHAR(20) NOT NULL,
  default_date   DATE NOT NULL,
  days_past_due  INT NOT NULL,
  reason         VARCHAR(255),
  status         ENUM('NEW','WORKOUT','RESOLVED','ESCALATED') NOT NULL,
  CONSTRAINT fk_def_loan FOREIGN KEY (loan_id) REFERENCES loans(loan_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS early_resolutions (
  resolution_id  VARCHAR(20) PRIMARY KEY,
  loan_id        VARCHAR(20) NOT NULL,
  resolution_type ENUM('FORBEARANCE','MODIFICATION','REPAYMENT_PLAN','DEED_IN_LIEU','SHORT_SALE') NOT NULL,
  agreement_date DATE NOT NULL,
  terms          TEXT,
  status         ENUM('PROPOSED','ACTIVE','COMPLETED','BROKEN') NOT NULL,
  CONSTRAINT fk_er_loan FOREIGN KEY (loan_id) REFERENCES loans(loan_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS bankruptcies (
  bankruptcy_id  VARCHAR(20) PRIMARY KEY,
  loan_id        VARCHAR(20) NOT NULL,
  chapter        ENUM('CH7','CH11','CH13') NOT NULL,
  filing_date    DATE NOT NULL,
  attorney       VARCHAR(255),
  status         ENUM('FILED','DISCHARGED','DISMISSED','CONVERTED') NOT NULL,
  CONSTRAINT fk_bk_loan FOREIGN KEY (loan_id) REFERENCES loans(loan_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS foreclosures (
  foreclosure_id VARCHAR(20) PRIMARY KEY,
  loan_id        VARCHAR(20) NOT NULL,
  initiated_date DATE NOT NULL,
  sale_date      DATE,
  sale_amount    DECIMAL(12,2),
  status         ENUM('INITIATED','HALTED','SOLD','REO') NOT NULL,
  CONSTRAINT fk_fc_loan FOREIGN KEY (loan_id) REFERENCES loans(loan_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS risk_assessments (
  assessment_id  VARCHAR(20) PRIMARY KEY,
  loan_id        VARCHAR(20) NOT NULL,
  assessment_date DATE NOT NULL,
  risk_score     INT NOT NULL,
  risk_band      ENUM('LOW','MODERATE','HIGH','SEVERE') NOT NULL,
  factors        JSON,
  CONSTRAINT fk_risk_loan FOREIGN KEY (loan_id) REFERENCES loans(loan_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS reds_filings (
  filing_id      VARCHAR(20) PRIMARY KEY,
  loan_id        VARCHAR(20) NOT NULL,
  regulator      ENUM('CFPB','HUD','FHFA','OCC','STATE_AG') NOT NULL,
  filing_type    VARCHAR(100) NOT NULL,
  filing_date    DATE NOT NULL,
  status         ENUM('DRAFT','SUBMITTED','ACCEPTED','REJECTED','AMENDED') NOT NULL,
  CONSTRAINT fk_reds_loan FOREIGN KEY (loan_id) REFERENCES loans(loan_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO investors VALUES
('INV001','Fannie Mae','GSE','rmbs@fanniemae.example',850000000,'2010-01-01'),
('INV002','Freddie Mac','GSE','rmbs@freddiemac.example',780000000,'2010-01-01'),
('INV003','Ginnie Mae','GOVT','rmbs@ginniemae.example',610000000,'2010-01-01'),
('INV004','BlackRock RMBS Fund','PRIVATE','desk@blackrock.example',420000000,'2014-06-15'),
('INV005','PIMCO Mortgage Trust','PRIVATE','desk@pimco.example',365000000,'2013-09-22'),
('INV006','State Street Bank','BANK','rmbs@statestreet.example',290000000,'2012-03-10'),
('INV007','Annaly Capital Mgmt','REIT','desk@annaly.example',175000000,'2015-08-04'),
('INV008','AGNC Investment Corp','REIT','desk@agnc.example',158000000,'2016-04-19'),
('INV009','Wells Fargo Bank','BANK','rmbs@wf.example',310000000,'2011-11-05'),
('INV010','JP Morgan Chase Bank','BANK','rmbs@jpmc.example',410000000,'2010-05-30');

INSERT INTO loans VALUES
('L0001','INV001','CONSUMER','APC0004','Alice Nguyen','55 Cedar St, Austin TX 78701',190000,182300,5.875,360,'2026-03-10','CURRENT'),
('L0002','INV002','CONSUMER','APC0005','Bob Patel','812 Lakeview Rd, Chicago IL 60614',150000,144900,6.125,360,'2026-02-08','CURRENT'),
('L0003','INV010','CONSUMER','APC0010','George Miller','3 Hillcrest Dr, Boston MA 02108',745000,720500,5.750,360,'2025-12-10','CURRENT'),
('L0004','INV001','CONSUMER','APC0006','Ian Olsen','920 Maple Ave, Denver CO 80202',488000,478100,6.000,360,'2026-02-22','CURRENT'),
('L0005','INV004','CORRESPONDENT','CP0001','Pacific Crest Customer #1','17 Vista Ridge, Phoenix AZ 85001',412000,404600,6.250,360,'2025-08-12','DELINQUENT'),
('L0006','INV005','CORRESPONDENT','CP0002','Lone Star Customer #1','990 Cypress Way, Dallas TX 75201',265000,259200,5.990,360,'2025-09-04','CURRENT'),
('L0007','INV007','CORRESPONDENT','CP0003','Northern Light Customer #1','41 Birch Ln, Minneapolis MN 55401',805000,790100,6.375,360,'2025-09-30','DEFAULT'),
('L0008','INV006','CORRESPONDENT','CP0004','Heritage Customer #1','12 Walnut St, Cleveland OH 44101',192000,188900,5.875,360,'2025-10-22','BANKRUPTCY'),
('L0009','INV008','CORRESPONDENT','CP0005','Atlas Customer #1','601 Oak Pl, Tampa FL 33601',345000,340100,6.500,360,'2025-11-19','FORECLOSURE'),
('L0010','INV009','CORRESPONDENT','CP0006','Cascade Customer #1','77 Beacon Hill, Boston MA 02108',1110000,1095000,5.625,360,'2025-12-08','CURRENT');

INSERT INTO payments VALUES
('PMT0001','L0001','2026-04-01',1124.50,1124.50,250.20,874.30,180.00,'ON_TIME'),
('PMT0002','L0002','2026-03-01',912.40,912.40,182.50,729.90,160.00,'ON_TIME'),
('PMT0003','L0003','2026-01-01',4347.20,4347.20,748.00,3599.20,420.00,'ON_TIME'),
('PMT0004','L0004','2026-03-22',2925.10,2925.10,535.40,2389.70,260.00,'ON_TIME'),
('PMT0005','L0005','2026-01-12',2538.20,0.00,0.00,0.00,0.00,'MISSED'),
('PMT0006','L0006','2026-02-04',1588.60,1588.60,310.20,1278.40,170.00,'ON_TIME'),
('PMT0007','L0007','2025-12-30',5023.30,2511.65,0.00,2511.65,0.00,'PARTIAL'),
('PMT0008','L0008','2025-11-22',1136.00,1136.00,225.50,910.50,140.00,'LATE'),
('PMT0009','L0009','2026-02-19',2179.50,0.00,0.00,0.00,0.00,'NSF'),
('PMT0010','L0010','2026-01-08',6391.20,6391.20,1290.40,5100.80,540.00,'ON_TIME');

INSERT INTO defaults VALUES
('DEF001','L0005','2026-01-12',32,'Job loss','WORKOUT'),
('DEF002','L0005','2026-02-12',62,'Job loss','ESCALATED'),
('DEF003','L0007','2025-12-30',45,'Income reduction','WORKOUT'),
('DEF004','L0007','2026-01-30',76,'Income reduction','ESCALATED'),
('DEF005','L0008','2025-11-22',15,'Medical event','WORKOUT'),
('DEF006','L0008','2025-12-22',45,'Medical event','RESOLVED'),
('DEF007','L0009','2026-02-19',30,'Divorce','WORKOUT'),
('DEF008','L0009','2026-03-19',60,'Divorce','ESCALATED'),
('DEF009','L0009','2026-04-19',90,'Divorce','ESCALATED'),
('DEF010','L0007','2026-03-01',105,'Income reduction','ESCALATED');

INSERT INTO early_resolutions VALUES
('ER0001','L0005','FORBEARANCE','2026-02-15','3 months payment relief','ACTIVE'),
('ER0002','L0007','MODIFICATION','2026-02-01','Rate reduced to 5.5% for 24 mo','ACTIVE'),
('ER0003','L0008','REPAYMENT_PLAN','2025-12-10','Catch-up over 6 months','COMPLETED'),
('ER0004','L0007','REPAYMENT_PLAN','2025-11-15','Initial 4-month plan','BROKEN'),
('ER0005','L0009','FORBEARANCE','2026-03-05','60-day relief','BROKEN'),
('ER0006','L0009','SHORT_SALE','2026-04-10','List price 320k','PROPOSED'),
('ER0007','L0005','MODIFICATION','2026-04-12','Term extension','PROPOSED'),
('ER0008','L0008','MODIFICATION','2025-12-18','Cap arrears','COMPLETED'),
('ER0009','L0007','DEED_IN_LIEU','2026-04-20','Deed in lieu pending','PROPOSED'),
('ER0010','L0009','REPAYMENT_PLAN','2026-02-22','3-month plan','BROKEN');

INSERT INTO bankruptcies VALUES
('BK0001','L0008','CH13','2025-12-01','Lawson & Associates','FILED'),
('BK0002','L0008','CH13','2026-01-15','Lawson & Associates','DISCHARGED'),
('BK0003','L0007','CH7','2026-03-10','Marcus Legal Group','FILED'),
('BK0004','L0009','CH13','2026-04-01','Sun State Law','FILED'),
('BK0005','L0005','CH13','2026-04-18','Greene PLLC','FILED'),
('BK0006','L0008','CH7','2025-11-10','Lawson & Associates','DISMISSED'),
('BK0007','L0007','CH13','2026-02-25','Marcus Legal Group','CONVERTED'),
('BK0008','L0009','CH7','2026-04-25','Sun State Law','FILED'),
('BK0009','L0005','CH7','2026-04-22','Greene PLLC','DISMISSED'),
('BK0010','L0008','CH13','2026-02-01','Lawson & Associates','DISCHARGED');

INSERT INTO foreclosures VALUES
('FC0001','L0009','2026-04-15',NULL,NULL,'INITIATED'),
('FC0002','L0007','2026-04-22',NULL,NULL,'INITIATED'),
('FC0003','L0009','2026-05-30','2026-06-12',315000,'SOLD'),
('FC0004','L0007','2026-05-15',NULL,NULL,'HALTED'),
('FC0005','L0009','2026-03-01',NULL,NULL,'HALTED'),
('FC0006','L0007','2026-03-12',NULL,NULL,'HALTED'),
('FC0007','L0009','2026-06-13',NULL,NULL,'REO'),
('FC0008','L0005','2026-05-01',NULL,NULL,'INITIATED'),
('FC0009','L0005','2026-05-20',NULL,NULL,'HALTED'),
('FC0010','L0008','2025-12-15',NULL,NULL,'HALTED');

INSERT INTO risk_assessments VALUES
('RA0001','L0001','2026-03-15',12,'LOW','{"fico":782,"ltv":37.1,"dti":24.0}'),
('RA0002','L0002','2026-02-15',18,'LOW','{"fico":741,"ltv":38.7,"dti":26.5}'),
('RA0003','L0003','2025-12-15',8,'LOW','{"fico":803,"ltv":89.8,"dti":22.0}'),
('RA0004','L0004','2026-02-25',22,'LOW','{"fico":775,"ltv":90.4,"dti":31.0}'),
('RA0005','L0005','2026-01-13',74,'HIGH','{"fico":688,"ltv":91.0,"dti":41.0,"missed_pmts":2}'),
('RA0006','L0006','2026-02-10',28,'MODERATE','{"fico":705,"ltv":85.2,"dti":35.0}'),
('RA0007','L0007','2025-12-31',86,'SEVERE','{"fico":640,"ltv":94.0,"dti":48.0,"missed_pmts":4}'),
('RA0008','L0008','2025-11-23',62,'HIGH','{"fico":660,"ltv":91.0,"dti":42.0,"bk_filed":true}'),
('RA0009','L0009','2026-02-20',91,'SEVERE','{"fico":622,"ltv":96.0,"dti":52.0,"fc_initiated":true}'),
('RA0010','L0010','2026-01-12',16,'LOW','{"fico":790,"ltv":80.5,"dti":25.0}');

INSERT INTO reds_filings VALUES
('REDS0001','L0001','CFPB','HMDA-LAR','2026-03-31','SUBMITTED'),
('REDS0002','L0002','CFPB','HMDA-LAR','2026-03-31','SUBMITTED'),
('REDS0003','L0003','HUD','FHA-Quarterly','2026-03-31','ACCEPTED'),
('REDS0004','L0005','OCC','Default-Notice','2026-02-01','SUBMITTED'),
('REDS0005','L0007','OCC','Default-Notice','2026-01-31','ACCEPTED'),
('REDS0006','L0008','HUD','Loss-Mit','2026-01-15','ACCEPTED'),
('REDS0007','L0009','OCC','FC-Initiation','2026-04-16','SUBMITTED'),
('REDS0008','L0009','STATE_AG','State-Notice','2026-04-18','SUBMITTED'),
('REDS0009','L0007','FHFA','Investor-Report','2026-03-15','ACCEPTED'),
('REDS0010','L0010','CFPB','HMDA-LAR','2026-03-31','SUBMITTED');

-- =============================================================================
-- DONE.  6 schemas, 23 tables, 230 sample rows.
-- =============================================================================
