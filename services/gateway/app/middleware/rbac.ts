/**
 * Server-side RBAC enforcement (gateway).
 * ----------------------------------------------------------------------------
 * Mirrors the frontend's authStore.has(perm) check, but on the SERVER and
 * against MySQL — so the server never trusts the client's claimed
 * permissions.
 *
 * Design:
 *   - Identity is taken from req.user (set by the existing authMiddleware
 *     from the JWT). We use only the `uid` claim as a key into MySQL.
 *   - Permissions are looked up live from `users → user_roles →
 *     role_permissions → permissions` with a 30-second in-process LRU.
 *   - `requirePermission(perm)` and `requireAnyPermission(...perms)` return
 *     Express middlewares that 403 on missing perms, 401 on missing auth.
 *   - On MySQL outage we fail CLOSED for mutating routes (deny) and OPEN
 *     for read-only routes (allow with a warning). Mutating routes are
 *     identified by HTTP method.
 *
 * The middleware that auto-applies the registry is also exported as
 * `enforceRegistry` and is wired up in main.ts AFTER authMiddleware.
 */

import { Request, Response, NextFunction } from 'express';
import { match as pathToRegexpMatch } from 'path-to-regexp';
import { getPool } from '../db/mysqlPool';
import { logger } from '../utils/logger';
import { JwtPayload } from './auth';
import {
  PERMISSION_REQUIREMENTS_WRITE,
  PERMISSION_REQUIREMENTS_READ,
  RouteRule,
} from './permissions';

// ─── Tiny LRU cache (no external dependency) ─────────────────────────────────

interface CacheEntry {
  perms: Set<string>;
  expires: number;
}

const PERMISSION_CACHE_TTL_MS = 30_000; // 30s — short enough that role
                                        // changes propagate quickly
const PERMISSION_CACHE_MAX = 500;       // cap per-process memory
const cache = new Map<number, CacheEntry>();

function cacheGet(uid: number): Set<string> | undefined {
  const hit = cache.get(uid);
  if (!hit) return undefined;
  if (hit.expires < Date.now()) {
    cache.delete(uid);
    return undefined;
  }
  // touch for LRU semantics
  cache.delete(uid);
  cache.set(uid, hit);
  return hit.perms;
}

function cacheSet(uid: number, perms: Set<string>): void {
  if (cache.size >= PERMISSION_CACHE_MAX) {
    const first = cache.keys().next().value;
    if (first !== undefined) cache.delete(first);
  }
  cache.set(uid, { perms, expires: Date.now() + PERMISSION_CACHE_TTL_MS });
}

/** Test hook: reset the cache between tests. */
export function _clearRbacCache(): void {
  cache.clear();
}

// ─── DB lookup ───────────────────────────────────────────────────────────────

/**
 * Load the permission set for `uid` from MySQL, with LRU caching. Throws on
 * DB error; the caller decides whether to fail open or closed.
 */
export async function loadPermissionsForUser(uid: number): Promise<Set<string>> {
  const cached = cacheGet(uid);
  if (cached) return cached;

  const [rows] = await getPool().query(
    `SELECT DISTINCT p.name
       FROM permissions p
       JOIN role_permissions rp ON rp.permission_id = p.id
       JOIN user_roles ur        ON ur.role_id = rp.role_id
      WHERE ur.user_id = ?`,
    [uid],
  );
  // mysql2 typing: rows is RowDataPacket[]; cast for our narrow shape.
  const perms = new Set<string>(
    (rows as unknown as Array<{ name: string }>).map((r) => r.name),
  );
  cacheSet(uid, perms);
  return perms;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

interface ReqWithUser extends Request {
  user?: JwtPayload;
  id?: string;
}

function getIdentity(req: ReqWithUser): { uid: number | null; sub: string | null } {
  const u = req.user;
  if (!u) return { uid: null, sub: null };
  // API-key requests synthesize a user with sub like "apikey:..." but no uid;
  // we treat them as super-user for RBAC because they already authenticated
  // out-of-band. (Same posture as authMiddleware.)
  if (typeof u.sub === 'string' && u.sub.startsWith('apikey:')) {
    return { uid: -1, sub: u.sub }; // sentinel: -1 means "skip RBAC"
  }
  return {
    uid: typeof u.uid === 'number' ? u.uid : null,
    sub: typeof u.sub === 'string' ? u.sub : null,
  };
}

function deny(
  res: Response,
  status: 401 | 403,
  message: string,
  traceId: string | undefined,
  missing?: string[],
): void {
  res.status(status).json({
    error: message,
    code: status === 401 ? 'AUTH_FAILED' : 'FORBIDDEN',
    missing,
    trace_id: traceId,
  });
}

const MUTATING_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

// ─── Public API: per-route factories ────────────────────────────────────────

/**
 * Require the user to hold ALL of the named permissions. Use this for
 * obvious single-permission gates: requirePermission('agents.write').
 */
export function requirePermission(...needed: string[]) {
  return async function rbacRequirePermission(
    req: ReqWithUser,
    res: Response,
    next: NextFunction,
  ): Promise<void> {
    const traceId = req.id;
    const { uid, sub } = getIdentity(req);

    if (uid === null && sub === null) {
      deny(res, 401, 'Not authenticated', traceId);
      return;
    }
    if (uid === -1) {
      // API-key — already authenticated, bypass RBAC
      next();
      return;
    }
    if (uid === null) {
      // JWT without uid (legacy) — treat as auth failure
      deny(res, 401, 'Token missing user identifier', traceId);
      return;
    }

    let perms: Set<string>;
    try {
      perms = await loadPermissionsForUser(uid);
    } catch (err) {
      const reason = err instanceof Error ? err.message : String(err);
      logger.error('rbac_db_unavailable', {
        layer: 'middleware',
        trace_id: traceId,
        sub,
        reason,
        method: req.method,
        path: req.path,
      });
      // Mutating route → fail closed; read route → fail open
      if (MUTATING_METHODS.has(req.method.toUpperCase())) {
        deny(res, 403, 'RBAC unavailable; denying mutation', traceId);
        return;
      }
      logger.warn('rbac_fail_open_read', {
        layer: 'middleware',
        trace_id: traceId,
        sub,
        method: req.method,
        path: req.path,
      });
      next();
      return;
    }

    const missing = needed.filter((p) => !perms.has(p));
    if (missing.length > 0) {
      logger.warn('rbac_denied', {
        layer: 'middleware',
        trace_id: traceId,
        sub,
        missing,
        method: req.method,
        path: req.path,
      });
      deny(res, 403, `Access denied — missing permission: ${missing.join(', ')}`, traceId, missing);
      return;
    }
    next();
  };
}

/**
 * Require AT LEAST ONE of the named permissions. Useful for read-paths
 * shared across multiple roles (e.g. governance.read OR ml_insights.read).
 */
export function requireAnyPermission(...needed: string[]) {
  return async function rbacRequireAnyPermission(
    req: ReqWithUser,
    res: Response,
    next: NextFunction,
  ): Promise<void> {
    const traceId = req.id;
    const { uid, sub } = getIdentity(req);

    if (uid === null && sub === null) {
      deny(res, 401, 'Not authenticated', traceId);
      return;
    }
    if (uid === -1) {
      next();
      return;
    }
    if (uid === null) {
      deny(res, 401, 'Token missing user identifier', traceId);
      return;
    }

    let perms: Set<string>;
    try {
      perms = await loadPermissionsForUser(uid);
    } catch (err) {
      const reason = err instanceof Error ? err.message : String(err);
      logger.error('rbac_db_unavailable', {
        layer: 'middleware',
        trace_id: traceId,
        sub,
        reason,
        method: req.method,
        path: req.path,
      });
      if (MUTATING_METHODS.has(req.method.toUpperCase())) {
        deny(res, 403, 'RBAC unavailable; denying mutation', traceId);
        return;
      }
      logger.warn('rbac_fail_open_read', {
        layer: 'middleware',
        trace_id: traceId,
        sub,
        method: req.method,
        path: req.path,
      });
      next();
      return;
    }

    if (!needed.some((p) => perms.has(p))) {
      logger.warn('rbac_denied_any', {
        layer: 'middleware',
        trace_id: traceId,
        sub,
        anyOf: needed,
        method: req.method,
        path: req.path,
      });
      deny(res, 403, `Access denied — requires one of: ${needed.join(', ')}`, traceId, needed);
      return;
    }
    next();
  };
}

// ─── Registry-based auto-enforcement ─────────────────────────────────────────

interface CompiledRule extends RouteRule {
  matcher: ReturnType<typeof pathToRegexpMatch>;
}

function compile(rules: ReadonlyArray<RouteRule>): CompiledRule[] {
  return rules.map((r) => ({
    ...r,
    matcher: pathToRegexpMatch(r.path),
  }));
}

const COMPILED_WRITE = compile(PERMISSION_REQUIREMENTS_WRITE);
const COMPILED_READ = compile(PERMISSION_REQUIREMENTS_READ);

function findRule(method: string, path: string): RouteRule | undefined {
  const upper = method.toUpperCase() as RouteRule['methods'][number];
  for (const r of [...COMPILED_WRITE, ...COMPILED_READ]) {
    if (r.methods.length === 0 || r.methods.includes(upper)) {
      if (r.matcher(path)) return r;
    }
  }
  return undefined;
}

/**
 * Express middleware: looks at req.method + req.path against the central
 * registry and enforces the matching rule. Mount this AFTER authMiddleware
 * but BEFORE the per-resource routers.
 *
 * If no rule matches, the request is allowed through — explicit gating only.
 */
export function enforceRegistry(
  req: ReqWithUser,
  res: Response,
  next: NextFunction,
): void {
  // Skip enforcement entirely for the auth flow itself
  if (req.path.startsWith('/auth/')) {
    next();
    return;
  }
  const rule = findRule(req.method, req.path);
  if (!rule) {
    next();
    return;
  }
  // Delegate to the per-permission middleware so logging is consistent
  void requireAnyPermission(...rule.anyOf)(req, res, next);
}
