import { Router, Request, Response } from 'express';
import jwt from 'jsonwebtoken';
import { v4 as uuidv4 } from 'uuid';
import { config } from '../config';
import { logger } from '../utils/logger';
import { JwtPayload } from '../middleware/auth';

const router = Router();

interface LoginRequest {
  username: string;
  password: string;
}

interface LoginResponse {
  token: string;
  user: { sub: string; role: string };
  expires_in: number;
}

/**
 * POST /auth/login
 * Authenticates a user with username + password and returns a signed JWT.
 */
router.post('/auth/login', (req: Request, res: Response): void => {
  const traceId = (req as Request & { id?: string }).id ?? uuidv4();
  const start = Date.now();

  const { username, password } = req.body as LoginRequest;

  if (!username || typeof username !== 'string' || username.trim().length === 0) {
    logger.warn('login_invalid_username', { layer: 'router', trace_id: traceId });
    res.status(400).json({
      error: 'username is required and must be a non-empty string',
      code: 'VALIDATION_ERROR',
      trace_id: traceId,
    });
    return;
  }

  if (!password || typeof password !== 'string') {
    logger.warn('login_missing_password', { layer: 'router', trace_id: traceId });
    res.status(400).json({
      error: 'password is required',
      code: 'VALIDATION_ERROR',
      trace_id: traceId,
    });
    return;
  }

  if (password !== config.AUTH_PASSWORD) {
    logger.warn('login_bad_credentials', {
      layer: 'router',
      trace_id: traceId,
      username: username.trim(),
    });
    res.status(401).json({
      error: 'Invalid credentials',
      code: 'AUTH_FAILED',
      trace_id: traceId,
    });
    return;
  }

  const expiresIn = config.JWT_EXPIRY_SEC;
  const payload = { sub: username.trim(), role: 'admin' };
  const token = jwt.sign(payload, config.JWT_SECRET, { expiresIn });

  const body: LoginResponse = {
    token,
    user: payload,
    expires_in: expiresIn,
  };

  logger.info('login_success', {
    layer: 'router',
    trace_id: traceId,
    sub: payload.sub,
    duration_ms: Date.now() - start,
  });

  res.status(200).json(body);
});

/**
 * POST /auth/refresh
 * Accepts a valid Bearer token and returns a fresh token with a new expiry.
 */
router.post('/auth/refresh', (req: Request, res: Response): void => {
  const traceId = (req as Request & { id?: string }).id ?? uuidv4();
  const start = Date.now();

  const authHeader = req.headers['authorization'];
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    logger.warn('refresh_missing_token', { layer: 'router', trace_id: traceId });
    res.status(401).json({
      error: 'Authorization header missing or malformed. Expected: Bearer <token>',
      code: 'AUTH_FAILED',
      trace_id: traceId,
    });
    return;
  }

  const token = authHeader.slice('Bearer '.length);

  try {
    const decoded = jwt.verify(token, config.JWT_SECRET) as JwtPayload;

    const expiresIn = config.JWT_EXPIRY_SEC;
    const payload = { sub: decoded.sub, role: (decoded.role as string) ?? 'admin' };
    const newToken = jwt.sign(payload, config.JWT_SECRET, { expiresIn });

    logger.info('refresh_success', {
      layer: 'router',
      trace_id: traceId,
      sub: decoded.sub,
      duration_ms: Date.now() - start,
    });

    res.status(200).json({
      token: newToken,
      user: payload,
      expires_in: expiresIn,
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Token verification failed';
    logger.warn('refresh_failed', { layer: 'router', trace_id: traceId, reason: message });
    res.status(401).json({
      error: `Token refresh failed: ${message}`,
      code: 'AUTH_FAILED',
      trace_id: traceId,
    });
  }
});

export default router;
