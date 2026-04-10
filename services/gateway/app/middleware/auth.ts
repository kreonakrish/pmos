import { Request, Response, NextFunction } from 'express';
import jwt from 'jsonwebtoken';
import { config } from '../config';
import { logger } from '../utils/logger';

export interface JwtPayload {
  sub: string;
  iat?: number;
  exp?: number;
  [key: string]: unknown;
}

/** Routes that bypass authentication entirely. */
const PUBLIC_PATHS = new Set(['/health', '/metrics']);

/**
 * Authenticates requests via:
 *   1. Bearer JWT token in the Authorization header
 *   2. x-api-key header compared to API_KEY env var
 *
 * On success, sets req.user = decoded JWT payload (or synthetic object for API key).
 * On failure, responds with 401.
 */
export function authMiddleware(req: Request, res: Response, next: NextFunction): void {
  const traceId = (req as Request & { id?: string }).id;

  // Skip auth for public routes
  if (PUBLIC_PATHS.has(req.path)) {
    next();
    return;
  }

  const authHeader = req.headers['authorization'];
  const apiKeyHeader = req.headers['x-api-key'] as string | undefined;

  // --- API key path ---
  if (apiKeyHeader) {
    const validApiKey = config.API_KEY;
    if (!validApiKey) {
      logger.warn('api_key_auth_disabled', { layer: 'middleware', trace_id: traceId });
      res.status(401).json({
        error: 'API key authentication is not configured on this gateway',
        code: 'AUTH_FAILED',
        trace_id: traceId,
      });
      return;
    }
    if (apiKeyHeader !== validApiKey) {
      logger.warn('api_key_invalid', { layer: 'middleware', trace_id: traceId });
      res.status(401).json({
        error: 'Invalid API key',
        code: 'AUTH_FAILED',
        trace_id: traceId,
      });
      return;
    }
    // Attach synthetic user object so downstream middleware can extract user_id
    (req as Request & { user: JwtPayload }).user = { sub: `apikey:${apiKeyHeader.slice(0, 8)}` };
    next();
    return;
  }

  // --- JWT Bearer path ---
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    logger.warn('auth_header_missing', { layer: 'middleware', trace_id: traceId });
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
    (req as Request & { user: JwtPayload }).user = decoded;
    logger.debug('auth_success', { layer: 'middleware', trace_id: traceId, sub: decoded.sub });
    next();
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Token verification failed';
    logger.warn('auth_failed', { layer: 'middleware', trace_id: traceId, reason: message });
    res.status(401).json({
      error: `Authentication failed: ${message}`,
      code: 'AUTH_FAILED',
      trace_id: traceId,
    });
  }
}
