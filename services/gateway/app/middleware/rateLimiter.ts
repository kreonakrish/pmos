import { Request, Response, NextFunction } from 'express';
import Redis from 'ioredis';
import { config } from '../config';
import { logger } from '../utils/logger';
import { JwtPayload } from './auth';

let redisClient: Redis | null = null;

/** Lazy-initialise the Redis client (allows injection in tests). */
export function getRedisClient(): Redis {
  if (!redisClient) {
    redisClient = new Redis(config.REDIS_URL, {
      lazyConnect: true,
      enableOfflineQueue: false,
      maxRetriesPerRequest: 1,
    });
    redisClient.on('error', (err: Error) => {
      logger.error('redis_error', { layer: 'adapter', error: err.message });
    });
  }
  return redisClient;
}

/** Override the Redis client (used in tests to inject a mock). */
export function setRedisClient(client: Redis): void {
  redisClient = client;
}

/**
 * Token bucket rate limiter backed by Redis.
 *
 * Algorithm:
 *   - Key: `gateway:rate:{user_id}`
 *   - On each request:
 *       1. GET current count.
 *       2. If count >= RPM → 429.
 *       3. Otherwise INCR; if count was 0, SET TTL = 60 s.
 *
 * This is an approximate sliding-window counter (fixed 60-second window reset).
 * For a strict token bucket with sub-second granularity a Lua script is used.
 */

const LUA_RATE_LIMIT = `
local key     = KEYS[1]
local limit   = tonumber(ARGV[1])
local ttl_sec = tonumber(ARGV[2])

local current = redis.call('GET', key)
if current == false then
  redis.call('SET', key, 1, 'EX', ttl_sec)
  return {1, ttl_sec}
end

current = tonumber(current)
if current >= limit then
  local remaining_ttl = redis.call('TTL', key)
  return {current, remaining_ttl}
end

redis.call('INCR', key)
local remaining_ttl = redis.call('TTL', key)
return {current + 1, remaining_ttl}
`;

function extractUserId(req: Request): string {
  // Prefer JWT sub claim
  const user = (req as Request & { user?: JwtPayload }).user;
  if (user?.sub) return user.sub;

  // Fall back to API key prefix
  const apiKey = req.headers['x-api-key'] as string | undefined;
  if (apiKey) return `apikey:${apiKey.slice(0, 16)}`;

  // Unauthenticated fallback (should not reach here after auth middleware)
  return req.ip ?? 'unknown';
}

export function rateLimiter(req: Request, res: Response, next: NextFunction): void {
  // Skip rate limiting for public routes
  if (req.path === '/health' || req.path === '/metrics') {
    next();
    return;
  }

  const userId = extractUserId(req);
  const redisKey = `gateway:rate:${userId}`;
  const rpm = config.RATE_LIMIT_RPM;
  const windowSec = 60;
  const traceId = (req as Request & { id?: string }).id;

  const redis = getRedisClient();

  redis
    .eval(LUA_RATE_LIMIT, 1, redisKey, String(rpm), String(windowSec))
    .then((result) => {
      const [current, ttl] = result as [number, number];

      res.setHeader('X-RateLimit-Limit', rpm);
      res.setHeader('X-RateLimit-Remaining', Math.max(0, rpm - current));
      res.setHeader('X-RateLimit-Reset', ttl);

      if (current > rpm) {
        logger.warn('rate_limit_exceeded', {
          layer: 'middleware',
          trace_id: traceId,
          user_id: userId,
          current,
          limit: rpm,
          retry_after: ttl,
        });
        res.setHeader('Retry-After', ttl);
        res.status(429).json({
          error: `Rate limit exceeded. Max ${rpm} requests per minute.`,
          code: 'RATE_LIMITED',
          trace_id: traceId,
          retry_after_sec: ttl,
        });
        return;
      }

      next();
    })
    .catch((err: Error) => {
      // If Redis is unavailable, fail open (allow the request) and log
      logger.error('rate_limiter_redis_failure', {
        layer: 'middleware',
        trace_id: traceId,
        error: err.message,
      });
      next();
    });
}
