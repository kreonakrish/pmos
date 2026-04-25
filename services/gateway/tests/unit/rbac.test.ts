/**
 * Unit tests for the server-side RBAC middleware.
 *
 * Hermetic: the MySQL pool is mocked so no DB is required.
 */

// Env shims used by the gateway config loader. Set BEFORE the rbac module
// resolves its imports.
process.env['JWT_SECRET'] = 'test-secret-at-least-32-characters-long!!';
process.env['API_KEY'] = 'test-api-key-value-1234';
process.env['ORCHESTRATOR_URL'] = 'http://localhost:8000';
process.env['AGENT_MGMT_URL'] = 'http://localhost:4001';
process.env['RAG_SERVICE_URL'] = 'http://localhost:8002';

// Mock the MySQL pool used inside the rbac middleware.
const queryMock = jest.fn();
jest.mock('../../app/db/mysqlPool', () => ({
  getPool: () => ({ query: queryMock }),
}));

// eslint-disable-next-line @typescript-eslint/no-require-imports
const rbac = require('../../app/middleware/rbac');
const requirePermission = rbac.requirePermission;
const requireAnyPermission = rbac.requireAnyPermission;
const _clearRbacCache = rbac._clearRbacCache;

interface ReqUser {
  uid?: number;
  sub?: string;
}

function makeReq(opts: { user?: ReqUser; method?: string; path?: string } = {}): any {
  return {
    id: 'trace-rbac-1',
    headers: {},
    method: opts.method ?? 'POST',
    path: opts.path ?? '/v1/agents',
    user: opts.user,
  };
}

function makeRes() {
  const res: any = {};
  res.status = function (code: number) {
    res._status = code;
    return res;
  };
  res.json = function (body: unknown) {
    res._body = body;
    return res;
  };
  return res;
}

function makeNext(): jest.Mock {
  return jest.fn();
}

beforeEach(() => {
  _clearRbacCache();
  queryMock.mockReset();
});

describe('requirePermission', () => {
  it('returns 401 when no user is attached to the request', async () => {
    const req = makeReq({ user: undefined });
    const res = makeRes();
    const next = makeNext();

    await requirePermission('agents.write')(req, res, next);

    expect(next).not.toHaveBeenCalled();
    expect(res._status).toBe(401);
    expect(res._body.code).toBe('AUTH_FAILED');
  });

  it('returns 403 when the user lacks the required permission', async () => {
    queryMock.mockResolvedValueOnce([[{ name: 'agents.read' }]]);

    const req = makeReq({ user: { uid: 7, sub: 'alice' } });
    const res = makeRes();
    const next = makeNext();

    await requirePermission('agents.write')(req, res, next);

    expect(next).not.toHaveBeenCalled();
    expect(res._status).toBe(403);
    expect(res._body.code).toBe('FORBIDDEN');
    expect(res._body.missing).toEqual(['agents.write']);
  });

  it('calls next() when the user holds the required permission', async () => {
    queryMock.mockResolvedValueOnce([[
      { name: 'agents.read' },
      { name: 'agents.write' },
    ]]);

    const req = makeReq({ user: { uid: 42, sub: 'bob' } });
    const res = makeRes();
    const next = makeNext();

    await requirePermission('agents.write')(req, res, next);

    expect(next).toHaveBeenCalledTimes(1);
    expect(res._status).toBeUndefined();
  });

  it('fails closed (403) on DB error for a mutating route', async () => {
    queryMock.mockRejectedValueOnce(new Error('mysql connection refused'));

    const req = makeReq({
      user: { uid: 9, sub: 'carol' },
      method: 'POST',
      path: '/v1/agents',
    });
    const res = makeRes();
    const next = makeNext();

    await requirePermission('agents.write')(req, res, next);

    expect(next).not.toHaveBeenCalled();
    expect(res._status).toBe(403);
  });

  it('fails open on DB error for a read route', async () => {
    queryMock.mockRejectedValueOnce(new Error('mysql connection refused'));

    const req = makeReq({
      user: { uid: 9, sub: 'carol' },
      method: 'GET',
      path: '/v1/catalog/crawlers',
    });
    const res = makeRes();
    const next = makeNext();

    await requirePermission('catalog.read')(req, res, next);

    expect(next).toHaveBeenCalledTimes(1);
    expect(res._status).toBeUndefined();
  });

  it('bypasses RBAC for API-key requests', async () => {
    const req = makeReq({ user: { sub: 'apikey:abcd1234' } });
    const res = makeRes();
    const next = makeNext();

    await requirePermission('agents.write')(req, res, next);

    expect(next).toHaveBeenCalledTimes(1);
    expect(queryMock).not.toHaveBeenCalled();
  });

  it('caches permissions across calls within the TTL', async () => {
    queryMock.mockResolvedValue([[{ name: 'agents.write' }]]);

    const req1 = makeReq({ user: { uid: 5, sub: 'dan' } });
    const req2 = makeReq({ user: { uid: 5, sub: 'dan' } });

    await requirePermission('agents.write')(req1, makeRes(), makeNext());
    await requirePermission('agents.write')(req2, makeRes(), makeNext());

    expect(queryMock).toHaveBeenCalledTimes(1);
  });
});

describe('requireAnyPermission', () => {
  it('passes when the user has at least one of the listed permissions', async () => {
    queryMock.mockResolvedValueOnce([[{ name: 'ml_insights.read' }]]);

    const req = makeReq({
      user: { uid: 11, sub: 'eve' },
      method: 'GET',
      path: '/v1/governance/traces',
    });
    const res = makeRes();
    const next = makeNext();

    await requireAnyPermission('models.read', 'ml_insights.read')(req, res, next);

    expect(next).toHaveBeenCalledTimes(1);
  });

  it('returns 403 when the user has none of the listed permissions', async () => {
    queryMock.mockResolvedValueOnce([[{ name: 'agents.read' }]]);

    const req = makeReq({
      user: { uid: 12, sub: 'frank' },
      method: 'GET',
      path: '/v1/governance/traces',
    });
    const res = makeRes();
    const next = makeNext();

    await requireAnyPermission('models.read', 'ml_insights.read')(req, res, next);

    expect(next).not.toHaveBeenCalled();
    expect(res._status).toBe(403);
  });
});
