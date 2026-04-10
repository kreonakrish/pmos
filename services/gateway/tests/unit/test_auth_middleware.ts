/**
 * Unit tests for auth middleware.
 * No real network calls. JWT secrets are ephemeral test values.
 */

import { Request, Response, NextFunction } from 'express';
import jwt from 'jsonwebtoken';

// ─── Environment setup (before any config import) ────────────────────────────
const TEST_SECRET = 'test-secret-at-least-32-characters-long!!';
const TEST_API_KEY = 'test-api-key-value-1234';

process.env['JWT_SECRET'] = TEST_SECRET;
process.env['API_KEY'] = TEST_API_KEY;
process.env['ORCHESTRATOR_URL'] = 'http://localhost:8000';
process.env['AGENT_MGMT_URL'] = 'http://localhost:4001';
process.env['RAG_SERVICE_URL'] = 'http://localhost:8002';

// Import AFTER env vars are set
import { authMiddleware, JwtPayload } from '../../app/middleware/auth';

// ─── Helpers ─────────────────────────────────────────────────────────────────

function makeReq(overrides: Partial<Request> = {}): Request & { id?: string } {
  return {
    id: 'trace-123',
    headers: {},
    path: '/v1/chat',
    ...overrides,
  } as unknown as Request & { id?: string };
}

function makeRes() {
  const res: Partial<Response> & { _status?: number; _body?: unknown } = {
    _status: undefined,
    _body: undefined,
  };
  res.status = function (code: number) {
    res._status = code;
    return res as Response;
  };
  res.json = function (body: unknown) {
    res._body = body;
    return res as Response;
  };
  return res as Response & { _status?: number; _body?: unknown };
}

function makeNext(): jest.Mock {
  return jest.fn() as jest.Mock;
}

function signToken(payload: object, secret = TEST_SECRET, options: jwt.SignOptions = {}): string {
  return jwt.sign(payload, secret, { expiresIn: '1h', ...options });
}

// ─── Tests ───────────────────────────────────────────────────────────────────

describe('authMiddleware', () => {
  describe('public routes', () => {
    it('skips auth for GET /health', () => {
      const req = makeReq({ path: '/health', headers: {} });
      const res = makeRes();
      const next = makeNext();

      authMiddleware(req, res, next as NextFunction);

      expect(next).toHaveBeenCalledTimes(1);
      expect(res._status).toBeUndefined();
    });

    it('skips auth for GET /metrics', () => {
      const req = makeReq({ path: '/metrics', headers: {} });
      const res = makeRes();
      const next = makeNext();

      authMiddleware(req, res, next as NextFunction);

      expect(next).toHaveBeenCalledTimes(1);
    });
  });

  describe('JWT Bearer token', () => {
    it('passes a valid JWT and attaches user to req', () => {
      const token = signToken({ sub: 'user-42', role: 'admin' });
      const req = makeReq({
        headers: { authorization: `Bearer ${token}` },
      });
      const res = makeRes();
      const next = makeNext();

      authMiddleware(req, res, next as NextFunction);

      expect(next).toHaveBeenCalledTimes(1);
      expect((req as unknown as { user: JwtPayload }).user.sub).toBe('user-42');
    });

    it('returns 401 for an expired JWT', () => {
      // Sign a token that is already expired
      const token = jwt.sign({ sub: 'user-1' }, TEST_SECRET, { expiresIn: -1 });
      const req = makeReq({ headers: { authorization: `Bearer ${token}` } });
      const res = makeRes();
      const next = makeNext();

      authMiddleware(req, res, next as NextFunction);

      expect(next).not.toHaveBeenCalled();
      expect(res._status).toBe(401);
      expect((res._body as { code: string }).code).toBe('AUTH_FAILED');
    });

    it('returns 401 when Authorization header is missing', () => {
      const req = makeReq({ headers: {} });
      const res = makeRes();
      const next = makeNext();

      authMiddleware(req, res, next as NextFunction);

      expect(next).not.toHaveBeenCalled();
      expect(res._status).toBe(401);
      expect((res._body as { code: string }).code).toBe('AUTH_FAILED');
    });

    it('returns 401 for a JWT signed with the wrong secret', () => {
      const token = signToken({ sub: 'attacker' }, 'totally-different-secret-32chars!!');
      const req = makeReq({ headers: { authorization: `Bearer ${token}` } });
      const res = makeRes();
      const next = makeNext();

      authMiddleware(req, res, next as NextFunction);

      expect(next).not.toHaveBeenCalled();
      expect(res._status).toBe(401);
    });

    it('returns 401 for a malformed token string', () => {
      const req = makeReq({ headers: { authorization: 'Bearer not.a.valid.token' } });
      const res = makeRes();
      const next = makeNext();

      authMiddleware(req, res, next as NextFunction);

      expect(next).not.toHaveBeenCalled();
      expect(res._status).toBe(401);
    });
  });

  describe('API key', () => {
    it('passes a valid x-api-key', () => {
      const req = makeReq({ headers: { 'x-api-key': TEST_API_KEY } });
      const res = makeRes();
      const next = makeNext();

      authMiddleware(req, res, next as NextFunction);

      expect(next).toHaveBeenCalledTimes(1);
      const user = (req as unknown as { user: JwtPayload }).user;
      expect(user.sub).toContain('apikey:');
    });

    it('returns 401 for a wrong API key', () => {
      const req = makeReq({ headers: { 'x-api-key': 'wrong-key' } });
      const res = makeRes();
      const next = makeNext();

      authMiddleware(req, res, next as NextFunction);

      expect(next).not.toHaveBeenCalled();
      expect(res._status).toBe(401);
      expect((res._body as { code: string }).code).toBe('AUTH_FAILED');
    });
  });
});
