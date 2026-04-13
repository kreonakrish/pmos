import { Router, Request, Response } from 'express';
import jwt from 'jsonwebtoken';
import { v4 as uuidv4 } from 'uuid';
import { config } from '../config';
import { logger } from '../utils/logger';
import { JwtPayload, authMiddleware } from '../middleware/auth';
import {
  findUserByUsername,
  findUserById,
  verifyPassword,
  getUserAccess,
  touchLogin,
  setPassword,
} from '../services/authService';

const router = Router();

interface LoginRequest {
  username: string;
  password: string;
}

async function issueToken(userId: number, username: string): Promise<{ token: string; user: JwtPayload; expires_in: number }> {
  const user = await findUserById(userId);
  if (!user) throw new Error('user_not_found');
  const { roles, permissions } = await getUserAccess(userId);
  const expiresIn = config.JWT_EXPIRY_SEC;
  const payload: JwtPayload = {
    sub: username,
    uid: userId,
    roles: roles.map((r) => r.name),
    permissions,
    must_change_password: !!user.must_change_password,
  };
  const token = jwt.sign(payload, config.JWT_SECRET, { expiresIn });
  return { token, user: payload, expires_in: expiresIn };
}

/**
 * POST /auth/login
 */
router.post('/auth/login', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id ?? uuidv4();
  const start = Date.now();
  const { username, password } = (req.body ?? {}) as LoginRequest;

  if (!username || typeof username !== 'string' || !username.trim()) {
    res.status(400).json({ error: 'username is required', code: 'VALIDATION_ERROR', trace_id: traceId });
    return;
  }
  if (!password || typeof password !== 'string') {
    res.status(400).json({ error: 'password is required', code: 'VALIDATION_ERROR', trace_id: traceId });
    return;
  }

  try {
    const user = await findUserByUsername(username.trim());
    if (!user) {
      // same wording as bad password to avoid user enumeration
      logger.warn('login_unknown_user', { trace_id: traceId, username: username.trim() });
      res.status(401).json({ error: 'Invalid credentials', code: 'AUTH_FAILED', trace_id: traceId });
      return;
    }
    if (user.status !== 'active') {
      logger.warn('login_account_not_active', { trace_id: traceId, username: user.username, status: user.status });
      res.status(403).json({ error: `Account ${user.status}`, code: 'ACCOUNT_NOT_ACTIVE', trace_id: traceId });
      return;
    }
    const ok = await verifyPassword(password, user.password_hash);
    if (!ok) {
      logger.warn('login_bad_password', { trace_id: traceId, username: user.username });
      res.status(401).json({ error: 'Invalid credentials', code: 'AUTH_FAILED', trace_id: traceId });
      return;
    }
    await touchLogin(user.id);
    const result = await issueToken(user.id, user.username);
    logger.info('login_success', { trace_id: traceId, sub: user.username, duration_ms: Date.now() - start });
    res.status(200).json(result);
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'login_error';
    logger.error('login_error', { trace_id: traceId, reason: message });
    res.status(500).json({ error: 'Login failed', code: 'INTERNAL', trace_id: traceId });
  }
});

/**
 * POST /auth/refresh
 */
router.post('/auth/refresh', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id ?? uuidv4();
  const authHeader = req.headers['authorization'];
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    res.status(401).json({ error: 'Authorization header missing', code: 'AUTH_FAILED', trace_id: traceId });
    return;
  }
  const token = authHeader.slice('Bearer '.length);
  try {
    const decoded = jwt.verify(token, config.JWT_SECRET) as JwtPayload;
    if (!decoded.uid) {
      res.status(401).json({ error: 'Legacy token; please log in again', code: 'AUTH_FAILED', trace_id: traceId });
      return;
    }
    const user = await findUserById(decoded.uid);
    if (!user || user.status !== 'active') {
      res.status(401).json({ error: 'Account inactive or missing', code: 'AUTH_FAILED', trace_id: traceId });
      return;
    }
    const result = await issueToken(user.id, user.username);
    res.status(200).json(result);
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'token error';
    res.status(401).json({ error: `Token refresh failed: ${message}`, code: 'AUTH_FAILED', trace_id: traceId });
  }
});

/**
 * GET /auth/me — return the authenticated user plus roles & permissions.
 */
router.get('/auth/me', authMiddleware, async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id ?? uuidv4();
  const jwtUser = (req as Request & { user?: JwtPayload }).user;
  if (!jwtUser?.uid) {
    res.status(401).json({ error: 'Not authenticated', code: 'AUTH_FAILED', trace_id: traceId });
    return;
  }
  const user = await findUserById(jwtUser.uid);
  if (!user) {
    res.status(404).json({ error: 'User not found', code: 'NOT_FOUND', trace_id: traceId });
    return;
  }
  const access = await getUserAccess(user.id);
  res.status(200).json({ user, roles: access.roles, permissions: access.permissions });
});

/**
 * POST /auth/change-password  { current_password, new_password }
 */
router.post('/auth/change-password', authMiddleware, async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id ?? uuidv4();
  const jwtUser = (req as Request & { user?: JwtPayload }).user;
  if (!jwtUser?.uid) {
    res.status(401).json({ error: 'Not authenticated', code: 'AUTH_FAILED', trace_id: traceId });
    return;
  }
  const { current_password, new_password } = (req.body ?? {}) as {
    current_password?: string; new_password?: string;
  };
  if (!current_password || !new_password || new_password.length < 8) {
    res.status(400).json({ error: 'current_password and new_password (min 8 chars) required', code: 'VALIDATION_ERROR', trace_id: traceId });
    return;
  }
  const user = await findUserByUsername(jwtUser.sub);
  if (!user) {
    res.status(404).json({ error: 'User not found', code: 'NOT_FOUND', trace_id: traceId });
    return;
  }
  const ok = await verifyPassword(current_password, user.password_hash);
  if (!ok) {
    res.status(401).json({ error: 'Current password is incorrect', code: 'AUTH_FAILED', trace_id: traceId });
    return;
  }
  await setPassword(user.id, new_password, false);
  logger.info('password_changed', { trace_id: traceId, sub: user.username });
  res.status(204).send();
});

export default router;
