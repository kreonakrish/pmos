-- =============================================================================
-- PMOS Auth / RBAC Schema
-- Applied by bootstrap.sh after the main schema.sql. Users are seeded by the
-- gateway on startup from env vars (SUPER_ADMIN_PASSWORD, KRISH_INITIAL_PASSWORD)
-- so plaintext passwords never appear in SQL.
-- =============================================================================

USE pmos;

CREATE TABLE IF NOT EXISTS users (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    username        VARCHAR(64)  NOT NULL,
    email           VARCHAR(255) NOT NULL,
    full_name       VARCHAR(255) NULL,
    password_hash   VARCHAR(255) NOT NULL,
    status          ENUM('active','disabled','locked') NOT NULL DEFAULT 'active',
    is_system       TINYINT(1)   NOT NULL DEFAULT 0,
    must_change_password TINYINT(1) NOT NULL DEFAULT 0,
    last_login_at   DATETIME NULL,
    failed_login_attempts INT UNSIGNED NOT NULL DEFAULT 0,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_users_username (username),
    UNIQUE KEY uq_users_email    (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS roles (
    id          INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(64)  NOT NULL,
    description VARCHAR(255) NOT NULL,
    is_system   TINYINT(1)   NOT NULL DEFAULT 0,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_roles_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS permissions (
    id          INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(96)  NOT NULL,        -- e.g. 'agents.write'
    resource    VARCHAR(48)  NOT NULL,        -- e.g. 'agents'
    action      VARCHAR(32)  NOT NULL,        -- e.g. 'write'
    description VARCHAR(255) NOT NULL,
    UNIQUE KEY uq_perm_name (name),
    KEY ix_perm_resource (resource)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS user_roles (
    user_id     BIGINT UNSIGNED NOT NULL,
    role_id     INT UNSIGNED NOT NULL,
    granted_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    granted_by  BIGINT UNSIGNED NULL,
    PRIMARY KEY (user_id, role_id),
    CONSTRAINT fk_ur_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_ur_role FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS role_permissions (
    role_id         INT UNSIGNED NOT NULL,
    permission_id   INT UNSIGNED NOT NULL,
    PRIMARY KEY (role_id, permission_id),
    CONSTRAINT fk_rp_role FOREIGN KEY (role_id)       REFERENCES roles(id)       ON DELETE CASCADE,
    CONSTRAINT fk_rp_perm FOREIGN KEY (permission_id) REFERENCES permissions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- Seed permissions (resource.action)
-- -----------------------------------------------------------------------------
INSERT IGNORE INTO permissions (name, resource, action, description) VALUES
  -- Auth / identity
  ('users.read',           'users',         'read',   'View users'),
  ('users.write',          'users',         'write',  'Create or update users'),
  ('users.delete',         'users',         'delete', 'Delete users'),
  ('roles.read',           'roles',         'read',   'View roles and their permissions'),
  ('roles.write',          'roles',         'write',  'Create, edit, or delete non-system roles'),
  ('roles.assign',         'roles',         'assign', 'Assign or unassign roles to users'),
  ('permissions.read',     'permissions',   'read',   'View all permissions'),
  -- Conversations / chat
  ('conversations.read',   'conversations', 'read',   'View conversations'),
  ('conversations.write',  'conversations', 'write',  'Create and update conversations'),
  -- Agents
  ('agents.read',          'agents',        'read',   'View agents'),
  ('agents.write',         'agents',        'write',  'Create or update agents'),
  ('agents.delete',        'agents',        'delete', 'Delete agents'),
  -- Tools
  ('tools.read',           'tools',         'read',   'View tools'),
  ('tools.write',          'tools',         'write',  'Create or update tools'),
  ('tools.delete',         'tools',         'delete', 'Delete tools'),
  -- Teams
  ('teams.read',           'teams',         'read',   'View teams'),
  ('teams.write',          'teams',         'write',  'Create or update teams'),
  ('teams.delete',         'teams',         'delete', 'Delete teams'),
  -- Memory
  ('memory.read',          'memory',        'read',   'View memory entries'),
  ('memory.write',         'memory',        'write',  'Create or update memory entries'),
  -- Documents / RAG
  ('documents.read',       'documents',     'read',   'View documents'),
  ('documents.write',      'documents',     'write',  'Upload or update documents'),
  ('documents.delete',     'documents',     'delete', 'Delete documents'),
  -- Jobs / pipelines
  ('jobs.read',            'jobs',          'read',   'View pipeline jobs'),
  ('jobs.write',           'jobs',          'write',  'Start, stop, or retry jobs'),
  -- Graph
  ('graph.read',           'graph',         'read',   'View the task execution graph'),
  -- Scoring / RL
  ('scoring.read',         'scoring',       'read',   'View scoring history and bands'),
  ('scoring.write',        'scoring',       'write',  'Adjust scoring config'),
  -- Model governance / ML
  ('models.read',          'models',        'read',   'View model governance config'),
  ('models.write',         'models',        'write',  'Edit model governance policies'),
  ('models.deploy',        'models',        'deploy', 'Deploy or rollback models'),
  ('ml_insights.read',     'ml_insights',   'read',   'View ML insights dashboards'),
  -- Data catalog
  ('catalog.read',         'catalog',       'read',   'View the data catalog'),
  ('catalog.write',        'catalog',       'write',  'Edit catalog entries and ontology'),
  -- Settings
  ('settings.read',        'settings',      'read',   'View system settings'),
  ('settings.write',       'settings',      'write',  'Modify system settings'),
  -- SRE / operational
  ('system.admin',         'system',        'admin',  'Operational control: restarts, breakers, health'),
  -- Observability
  ('logs.read',            'logs',          'read',   'View service logs');

-- -----------------------------------------------------------------------------
-- Seed roles
-- -----------------------------------------------------------------------------
INSERT IGNORE INTO roles (name, description, is_system) VALUES
  ('super_admin',     'Full system access; can modify system roles',                    1),
  ('admin',           'Tenant admin: manage users, assign roles, all business perms',   1),
  ('agent_engineer',  'Create and manage agents and their prompts/memory',              1),
  ('tool_engineer',   'Create and manage tools',                                        1),
  ('team_engineer',   'Create and manage teams and agent compositions',                 1),
  ('sre',             'Site reliability / operational engineer',                        1),
  ('catalog_steward', 'Data catalog and business ontology steward',                     1),
  ('ml_engineer',     'Model governance and ML insights',                               1),
  ('viewer',          'Read-only access across the application',                        1),
  ('user',            'Standard user: chat with agents, view own conversations',        1);

-- -----------------------------------------------------------------------------
-- Role → permission grants
-- Helper: grant a whole resource wildcard via multiple explicit inserts
-- (MySQL has no wildcard in the join, so we enumerate).
-- -----------------------------------------------------------------------------

-- super_admin: every permission
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p WHERE r.name = 'super_admin';

-- admin: everything except system.admin (operational-only) and roles.write (system-role editing reserved)
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
WHERE r.name = 'admin'
  AND p.name NOT IN ('system.admin', 'roles.write');

-- agent_engineer
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
WHERE r.name = 'agent_engineer'
  AND p.name IN (
    'agents.read','agents.write','agents.delete',
    'tools.read','teams.read',
    'memory.read','memory.write',
    'conversations.read','conversations.write',
    'graph.read','scoring.read','documents.read','jobs.read'
  );

-- tool_engineer
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
WHERE r.name = 'tool_engineer'
  AND p.name IN (
    'tools.read','tools.write','tools.delete',
    'agents.read','teams.read',
    'conversations.read','conversations.write',
    'graph.read','jobs.read'
  );

-- team_engineer
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
WHERE r.name = 'team_engineer'
  AND p.name IN (
    'teams.read','teams.write','teams.delete',
    'agents.read','tools.read',
    'conversations.read','conversations.write',
    'graph.read','jobs.read'
  );

-- sre
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
WHERE r.name = 'sre'
  AND p.name IN (
    'system.admin',
    'jobs.read','jobs.write',
    'graph.read',
    'settings.read','settings.write',
    'scoring.read',
    'ml_insights.read',
    'agents.read','tools.read','teams.read',
    'memory.read','documents.read','catalog.read',
    'conversations.read','users.read','roles.read',
    'logs.read'
  );

-- catalog_steward
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
WHERE r.name = 'catalog_steward'
  AND p.name IN (
    'catalog.read','catalog.write',
    'documents.read','documents.write',
    'conversations.read','graph.read'
  );

-- ml_engineer
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
WHERE r.name = 'ml_engineer'
  AND p.name IN (
    'models.read','models.write','models.deploy',
    'ml_insights.read',
    'scoring.read','scoring.write',
    'graph.read','agents.read',
    'conversations.read','documents.read'
  );

-- viewer: every *.read plus graph.read / ml_insights.read
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
WHERE r.name = 'viewer'
  AND p.action = 'read';

-- user (default): chat-only
INSERT IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
WHERE r.name = 'user'
  AND p.name IN ('conversations.read','conversations.write','graph.read');
