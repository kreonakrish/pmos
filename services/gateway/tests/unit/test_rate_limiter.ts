/**
 * Unit tests for the token-bucket rate limiter.
 * Redis is mocked so no real Redis connection is required.
 */

import { Request, Response, NextFunction } from 'express';
import EventEmitter from 'events';

// ─── Environment setup ────────────────────────────────────────────────────────
const TEST_SECRET = 'test-secret-at-least-32-characters-long!!';

process.env['JWT_SECRET'] = TEST_SECRET;
process.env['ORCHESTRATOR_URL'] = 'http://localhost:8000';
process.env['AGENT_MGMT_URL'] = 'http://localhost:4001';
process.env['RAG_SERVICE_URL'] = 'http://localhost:8002';
process.env['RATE_LIMIT_RPM'] = '5'; // low limit for easy testing

// ─── Redis mock factory ───────────────────────────────────────────────────────

interface MockRedis extends EventEmitter {
  eval: jest.Mock;
  disconnect: jest.Mock;
  on: (event: string, cb: (...args: unknown[]) => void) => this;
}

function makeMockRedis(): MockRedis {
  const emitter = new EventEmitter() as MockRedis;
  emitter.eval = jest.fn();
  emitter.disconnect = jest.fn();
  return emitter;
}

// Import AFTER env vars
import { rateLimiter, setRedisClient } from '../../app/middleware/rateLimiter';

// ─── Helpers ──────────────────────────────────────────────────────────────────

type ExtReq = Request & { id?: string; user?: { sub: string } };

function makeReq(userId = 'user-1', path = '/v1/chat'): ExtReq {
  return {
    path,
    headers: {},
    ip: '127.0.0.1',
    id: 'trace-abc',
    user: { sub: userId },
    method: 'POST',
    query: {},
  } as unknown as ExtReq;
}

function makeRes() {
  const headers: Record<string, string | number> = {};
  const res: Partial<Response> & { _status?: number; _body?: unknown; _headers: typeof headers } =
    {
      _status: undefined,
      _body: undefined,
      _headers: headers,
    };
  res.status = function (code: number) {
    res._status = code;
    return res as Response;
  };
  res.json = function (body: unknown) {
    res._body = body;
    return res as Response;
  };
  res.setHeader = function (name: string, value: string | number) {
    headers[name.toLowerCase()] = value;
    return res as Response;
  };
  return res as Response & { _status?: number; _body?: unknown; _headers: typeof headers };
}

function makeNext(): jest.Mock {
  return jest.fn();
}

// ─── Tests ────────────────────────────────────────────────────────────────────

describe('rateLimiter', () => {
  let mockRedis: MockRedis;

  beforeEach(() => {
    mockRedis = makeMockRedis();
    // Inject the mock so the middleware uses it
    setRedisClient(mockRedis as unknown as import('ioredis').default);
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  describe('public routes bypass', () => {
    it('skips rate limiting for /health', async () => {
      const req = makeReq('user-1', '/health');
      const res = makeRes();
      const next = makeNext();

      rateLimiter(req as Request, res as Response, next as NextFunction);

      expect(next).toHaveBeenCalledTimes(1);
      expect(mockRedis.eval).not.toHaveBeenCalled();
    });

    it('skips rate limiting for /metrics', async () => {
      const req = makeReq('user-1', '/metrics');
      const res = makeRes();
      const next = makeNext();

      rateLimiter(req as Request, res as Response, next as NextFunction);

      expect(next).toHaveBeenCalledTimes(1);
      expect(mockRedis.eval).not.toHaveBeenCalled();
    });
  });

  describe('within limit', () => {
    it('passes the request when count is below RPM', async () => {
      // Simulate count=3, TTL=55 — under the limit of 5
      mockRedis.eval.mockResolvedValue([3, 55]);

      const req = makeReq('user-1');
      const res = makeRes();
      const next = makeNext();

      await new Promise<void>((resolve) => {
        (next as jest.Mock).mockImplementation(() => resolve());
        rateLimiter(req as Request, res as Response, next as NextFunction);
      });

      expect(next).toHaveBeenCalledTimes(1);
      expect(res._status).toBeUndefined();
    });

    it('sets rate limit headers on allowed requests', async () => {
      mockRedis.eval.mockResolvedValue([2, 58]);

      const req = makeReq('user-1');
      const res = makeRes();
      const next = makeNext();

      await new Promise<void>((resolve) => {
        (next as jest.Mock).mockImplementation(() => resolve());
        rateLimiter(req as Request, res as Response, next as NextFunction);
      });

      expect(res._headers['x-ratelimit-limit']).toBe(5);
      expect(res._headers['x-ratelimit-remaining']).toBe(3); // limit - current
    });
  });

  describe('over limit', () => {
    it('returns 429 when count exceeds RPM', async () => {
      // Simulate count=6 which is > limit=5
      mockRedis.eval.mockResolvedValue([6, 30]);

      const req = makeReq('user-1');
      const res = makeRes();
      const next = makeNext();

      await new Promise<void>((resolve) => {
        res.json = function (body: unknown) {
          (res as { _body?: unknown })._body = body;
          resolve();
          return res as Response;
        };
        rateLimiter(req as Request, res as Response, next as NextFunction);
      });

      expect(next).not.toHaveBeenCalled();
      expect(res._status).toBe(429);
      expect((res._body as { code: string }).code).toBe('RATE_LIMITED');
      expect(res._headers['retry-after']).toBe(30);
    });
  });

  describe('bucket isolation', () => {
    it('uses separate Redis keys for different user_ids', async () => {
      mockRedis.eval.mockResolvedValue([1, 60]);

      const reqA = makeReq('user-A');
      const reqB = makeReq('user-B');
      const next = makeNext();

      await new Promise<void>((resolve) => {
        let calls = 0;
        (next as jest.Mock).mockImplementation(() => {
          calls++;
          if (calls === 2) resolve();
        });
        rateLimiter(reqA as Request, makeRes() as Response, next as NextFunction);
        rateLimiter(reqB as Request, makeRes() as Response, next as NextFunction);
      });

      // Two separate eval calls, one per user
      expect(mockRedis.eval).toHaveBeenCalledTimes(2);
      const firstKey = (mockRedis.eval.mock.calls[0] as unknown[])[2] as string;
      const secondKey = (mockRedis.eval.mock.calls[1] as unknown[])[2] as string;
      expect(firstKey).toContain('user-A');
      expect(secondKey).toContain('user-B');
      expect(firstKey).not.toBe(secondKey);
    });

    it('throttles user-A but not user-B', async () => {
      // user-A is over limit, user-B is under
      mockRedis.eval
        .mockResolvedValueOnce([6, 30]) // user-A: over limit
        .mockResolvedValueOnce([2, 55]); // user-B: under limit

      const resA = makeRes();
      const resB = makeRes();
      const nextA = makeNext();
      const nextB = makeNext();

      await Promise.all([
        new Promise<void>((resolve) => {
          resA.json = function (body: unknown) {
            (resA as { _body?: unknown })._body = body;
            resolve();
            return resA as Response;
          };
          rateLimiter(makeReq('user-A') as Request, resA as Response, nextA as NextFunction);
        }),
        new Promise<void>((resolve) => {
          (nextB as jest.Mock).mockImplementation(() => resolve());
          rateLimiter(makeReq('user-B') as Request, resB as Response, nextB as NextFunction);
        }),
      ]);

      expect(resA._status).toBe(429);
      expect(nextA).not.toHaveBeenCalled();
      expect(nextB).toHaveBeenCalledTimes(1);
      expect(resB._status).toBeUndefined();
    });
  });

  describe('bucket refill', () => {
    it('allows requests again after TTL expires (simulated by count returning to 1)', async () => {
      // First call: over limit
      mockRedis.eval.mockResolvedValueOnce([6, 5]);
      // Second call (simulating post-expiry): count reset to 1
      mockRedis.eval.mockResolvedValueOnce([1, 60]);

      const req1 = makeReq('user-1');
      const req2 = makeReq('user-1');
      const next1 = makeNext();
      const next2 = makeNext();
      const res1 = makeRes();
      const res2 = makeRes();

      await new Promise<void>((resolve) => {
        res1.json = function (body: unknown) {
          (res1 as { _body?: unknown })._body = body;
          resolve();
          return res1 as Response;
        };
        rateLimiter(req1 as Request, res1 as Response, next1 as NextFunction);
      });

      await new Promise<void>((resolve) => {
        (next2 as jest.Mock).mockImplementation(() => resolve());
        rateLimiter(req2 as Request, res2 as Response, next2 as NextFunction);
      });

      expect(res1._status).toBe(429);
      expect(next2).toHaveBeenCalledTimes(1);
    });
  });

  describe('Redis failure', () => {
    it('fails open if Redis is unavailable', async () => {
      mockRedis.eval.mockRejectedValue(new Error('ECONNREFUSED'));

      const req = makeReq('user-1');
      const res = makeRes();
      const next = makeNext();

      await new Promise<void>((resolve) => {
        (next as jest.Mock).mockImplementation(() => resolve());
        rateLimiter(req as Request, res as Response, next as NextFunction);
      });

      // Should pass through (fail open)
      expect(next).toHaveBeenCalledTimes(1);
      expect(res._status).toBeUndefined();
    });
  });
});
