/**
 * PMOS Auth Service
 * ----------------------------------------------------------------------------
 * Real user authentication and RBAC backed by MySQL.
 * Uses bcryptjs for password hashing (OWASP-recommended rounds via config).
 */
import bcrypt from 'bcryptjs';
import type { RowDataPacket, ResultSetHeader } from 'mysql2';
import { getPool } from '../db/mysqlPool';
import { config } from '../config';
import { logger } from '../utils/logger';

export interface User {
  id: number;
  username: string;
  email: string;
  full_name: string | null;
  status: 'active' | 'disabled' | 'locked';
  is_system: boolean;
  must_change_password: boolean;
  last_login_at: Date | null;
  created_at: Date;
  updated_at: Date;
}

export interface Role {
  id: number;
  name: string;
  description: string;
  is_system: boolean;
}

export interface Permission {
  id: number;
  name: string;
  resource: string;
  action: string;
  description: string;
}

export interface UserWithAccess extends User {
  roles: Role[];
  permissions: string[]; // flat list of permission names (e.g. "agents.write")
}

// -------------------------------------------------------------------- hashing
export async function hashPassword(plain: string): Promise<string> {
  return bcrypt.hash(plain, config.BCRYPT_ROUNDS);
}
export async function verifyPassword(plain: string, hash: string): Promise<boolean> {
  return bcrypt.compare(plain, hash);
}

// -------------------------------------------------------------------- queries
export async function findUserByUsername(username: string): Promise<(User & { password_hash: string }) | null> {
  const [rows] = await getPool().query<RowDataPacket[]>(
    'SELECT * FROM users WHERE username = ? LIMIT 1',
    [username],
  );
  return rows[0] ? (rows[0] as User & { password_hash: string }) : null;
}

export async function findUserById(id: number): Promise<User | null> {
  const [rows] = await getPool().query<RowDataPacket[]>(
    'SELECT id, username, email, full_name, status, is_system, must_change_password, last_login_at, created_at, updated_at FROM users WHERE id = ? LIMIT 1',
    [id],
  );
  return rows[0] ? (rows[0] as User) : null;
}

export async function listUsers(): Promise<UserWithAccess[]> {
  const [users] = await getPool().query<RowDataPacket[]>(
    `SELECT id, username, email, full_name, status, is_system, must_change_password,
            last_login_at, created_at, updated_at
     FROM users ORDER BY id ASC`,
  );
  const result: UserWithAccess[] = [];
  for (const u of users) {
    const access = await getUserAccess((u as User).id);
    result.push({ ...(u as User), ...access });
  }
  return result;
}

export async function getUserRoles(userId: number): Promise<Role[]> {
  const [rows] = await getPool().query<RowDataPacket[]>(
    `SELECT r.id, r.name, r.description, r.is_system
       FROM roles r JOIN user_roles ur ON ur.role_id = r.id
      WHERE ur.user_id = ? ORDER BY r.name`,
    [userId],
  );
  return rows as Role[];
}

export async function getUserPermissions(userId: number): Promise<string[]> {
  const [rows] = await getPool().query<RowDataPacket[]>(
    `SELECT DISTINCT p.name
       FROM permissions p
       JOIN role_permissions rp ON rp.permission_id = p.id
       JOIN user_roles ur        ON ur.role_id = rp.role_id
      WHERE ur.user_id = ?`,
    [userId],
  );
  return rows.map((r) => (r as { name: string }).name).sort();
}

export async function getUserAccess(userId: number): Promise<{ roles: Role[]; permissions: string[] }> {
  const [roles, permissions] = await Promise.all([
    getUserRoles(userId),
    getUserPermissions(userId),
  ]);
  return { roles, permissions };
}

export async function listRoles(): Promise<(Role & { permissions: string[] })[]> {
  const [roles] = await getPool().query<RowDataPacket[]>(
    'SELECT id, name, description, is_system FROM roles ORDER BY name',
  );
  const result: (Role & { permissions: string[] })[] = [];
  for (const r of roles) {
    const [perms] = await getPool().query<RowDataPacket[]>(
      `SELECT p.name FROM permissions p
         JOIN role_permissions rp ON rp.permission_id = p.id
        WHERE rp.role_id = ? ORDER BY p.name`,
      [(r as Role).id],
    );
    result.push({
      ...(r as Role),
      permissions: perms.map((p) => (p as { name: string }).name),
    });
  }
  return result;
}

export async function listPermissions(): Promise<Permission[]> {
  const [rows] = await getPool().query<RowDataPacket[]>(
    'SELECT id, name, resource, action, description FROM permissions ORDER BY resource, action',
  );
  return rows as Permission[];
}

// -------------------------------------------------------------------- mutations
export async function createUser(opts: {
  username: string;
  email: string;
  fullName?: string | null;
  password: string;
  mustChangePassword?: boolean;
  roles?: string[];
  isSystem?: boolean;
  grantedBy?: number | null;
}): Promise<User> {
  const hash = await hashPassword(opts.password);
  const [result] = await getPool().query<ResultSetHeader>(
    `INSERT INTO users (username, email, full_name, password_hash, status, is_system, must_change_password)
     VALUES (?, ?, ?, ?, 'active', ?, ?)`,
    [opts.username, opts.email, opts.fullName ?? null, hash, opts.isSystem ? 1 : 0, opts.mustChangePassword ? 1 : 0],
  );
  const userId = result.insertId;
  if (opts.roles && opts.roles.length > 0) {
    await assignRoles(userId, opts.roles, opts.grantedBy ?? null);
  }
  const u = await findUserById(userId);
  if (!u) throw new Error('Failed to load newly-created user');
  return u;
}

export async function updateUser(id: number, opts: {
  email?: string;
  fullName?: string | null;
  status?: 'active' | 'disabled' | 'locked';
}): Promise<void> {
  const sets: string[] = [];
  const vals: unknown[] = [];
  if (opts.email !== undefined)    { sets.push('email = ?');     vals.push(opts.email); }
  if (opts.fullName !== undefined) { sets.push('full_name = ?'); vals.push(opts.fullName); }
  if (opts.status !== undefined)   { sets.push('status = ?');    vals.push(opts.status); }
  if (sets.length === 0) return;
  vals.push(id);
  await getPool().query(`UPDATE users SET ${sets.join(', ')} WHERE id = ?`, vals);
}

export async function deleteUser(id: number): Promise<void> {
  await getPool().query('DELETE FROM users WHERE id = ? AND is_system = 0', [id]);
}

export async function setPassword(userId: number, newPassword: string, mustChange = false): Promise<void> {
  const hash = await hashPassword(newPassword);
  await getPool().query(
    'UPDATE users SET password_hash = ?, must_change_password = ? WHERE id = ?',
    [hash, mustChange ? 1 : 0, userId],
  );
}

export async function touchLogin(userId: number): Promise<void> {
  await getPool().query(
    'UPDATE users SET last_login_at = CURRENT_TIMESTAMP, failed_login_attempts = 0 WHERE id = ?',
    [userId],
  );
}

export async function assignRoles(userId: number, roleNames: string[], grantedBy: number | null = null): Promise<void> {
  if (roleNames.length === 0) return;
  const [roles] = await getPool().query<RowDataPacket[]>(
    `SELECT id, name FROM roles WHERE name IN (${roleNames.map(() => '?').join(',')})`,
    roleNames,
  );
  if (roles.length === 0) return;
  const values = roles.map((r) => [userId, (r as Role).id, grantedBy]);
  await getPool().query(
    'INSERT IGNORE INTO user_roles (user_id, role_id, granted_by) VALUES ?',
    [values],
  );
}

export async function setUserRoles(userId: number, roleNames: string[], grantedBy: number | null = null): Promise<void> {
  await getPool().query('DELETE FROM user_roles WHERE user_id = ?', [userId]);
  await assignRoles(userId, roleNames, grantedBy);
}

// -------------------------------------------------------------------- seeding
/**
 * Idempotently seed the two bootstrap users (superadmin, krish) from env vars.
 * Only creates them if they do not exist; never overwrites an existing password.
 */
export async function seedBootstrapUsers(): Promise<void> {
  const seeds = [
    {
      username: config.SUPER_ADMIN_USERNAME,
      email:    config.SUPER_ADMIN_EMAIL,
      password: config.SUPER_ADMIN_PASSWORD,
      roles:    ['super_admin'],
      isSystem: true,
      mustChange: false,
      fullName: 'Super Administrator',
    },
    {
      username: config.KRISH_USERNAME,
      email:    config.KRISH_EMAIL,
      password: config.KRISH_INITIAL_PASSWORD,
      roles:    ['super_admin'],
      isSystem: false,
      mustChange: true,
      fullName: 'Krishna (Owner)',
    },
  ];

  for (const s of seeds) {
    const existing = await findUserByUsername(s.username);
    if (existing) {
      logger.info('seed_user_exists', { username: s.username });
      continue;
    }
    await createUser({
      username: s.username,
      email: s.email,
      fullName: s.fullName,
      password: s.password,
      mustChangePassword: s.mustChange,
      roles: s.roles,
      isSystem: s.isSystem,
    });
    logger.info('seed_user_created', { username: s.username, roles: s.roles });
  }
}
