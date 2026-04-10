/**
 * Integration tests for POST /v1/capabilities
 * Uses supertest + mock MySQL + mock Redis.
 * No real DB or Redis connections are made.
 */
import { jest } from '@jest/globals';
import request from 'supertest';

// ── Mocks must be defined before any imports ────────────────────────────────

jest.mock('../../app/config', () => ({
  config: {
    AGENT_MGMT_PORT: 4001,
    MYSQL_HOST: 'localhost',
    MYSQL_PORT: 3306,
    MYSQL_DB: 'pmos',
    MYSQL_USER: 'root',
    MYSQL_PASSWORD: 'test',
    MYSQL_POOL_SIZE: 5,
    REDIS_URL: 'redis://localhost:6379',
    TOOL_HEALTH_INTERVAL_SEC: 60,
    LOG_LEVEL: 'INFO',
    NODE_ENV: 'test',
  },
}));

jest.mock('../../app/utils/logger', () => ({
  logger: { debug: jest.fn(), info: jest.fn(), warn: jest.fn(), error: jest.fn() },
}));

jest.mock('../../app/adapters/mysqlAdapter', () => ({
  mysqlAdapter: {
    query: jest.fn<() => Promise<unknown>>(),
    execute: jest.fn<() => Promise<unknown>>(),
    healthCheck: jest.fn<() => Promise<boolean>>().mockResolvedValue(true),
    connect: jest.fn<() => Promise<void>>(),
    close: jest.fn<() => Promise<void>>(),
  },
}));

jest.mock('../../app/adapters/redisAdapter', () => ({
  redisAdapter: {
    publish: jest.fn<() => Promise<string>>(),
    healthCheck: jest.fn<() => Promise<boolean>>().mockResolvedValue(true),
    connect: jest.fn<() => Promise<void>>(),
    close: jest.fn<() => Promise<void>>(),
  },
}));

// Prevent tool health scheduler from actually starting in tests
jest.mock('../../app/services/toolHealthScheduler', () => ({
  toolHealthScheduler: { start: jest.fn(), stop: jest.fn() },
}));

// ── Imports after mocks ─────────────────────────────────────────────────────

import { mysqlAdapter } from '../../app/adapters/mysqlAdapter';
import { redisAdapter } from '../../app/adapters/redisAdapter';

// Import app after mocks
import express, { Request, Response, NextFunction } from 'express';
import { v4 as uuidv4 } from 'uuid';
import capabilityRoutes from '../../app/routes/capabilities';
import healthRoutes, { metricsRouter } from '../../app/routes/health';

const mockExecute = mysqlAdapter.execute as jest.MockedFunction<typeof mysqlAdapter.execute>;
const mockQuery = mysqlAdapter.query as jest.MockedFunction<typeof mysqlAdapter.query>;
const mockPublish = redisAdapter.publish as jest.MockedFunction<typeof redisAdapter.publish>;

// Build a minimal Express app for integration testing
function buildTestApp() {
  const app = express();
  app.use(express.json());
  app.use((req: Request, _res: Response, next: NextFunction) => {
    if (!req.headers['x-request-id']) req.headers['x-request-id'] = uuidv4();
    next();
  });
  app.use('/v1/capabilities', capabilityRoutes);
  app.use('/health', healthRoutes);
  app.use('/metrics', metricsRouter);
  return app;
}

const app = buildTestApp();

const VALID_CAPABILITY_BODY = {
  capability_type: 'TOOL',
  capability_id: 'cap-tool-001',
  name: 'SQL Query Tool',
  description: 'Executes parameterized SQL queries',
  spec_json: { language: 'python', imports: ['sqlalchemy'] },
  gap_id: 'gap-42',
  validation_score: 0.91,
};

const REGISTERED_CAPABILITY_ROW = {
  id: 1,
  capability_type: 'TOOL',
  capability_id: 'cap-tool-001',
  name: 'SQL Query Tool',
  description: 'Executes parameterized SQL queries',
  spec_json: JSON.stringify({ language: 'python', imports: ['sqlalchemy'] }),
  source: 'DYNAMIC',
  gap_id: 'gap-42',
  validation_score: 0.91,
  is_active: 1,
  usage_count: 0,
  last_used: null,
  created_at: '2026-01-01T00:00:00.000Z',
};

describe('POST /v1/capabilities — capability registration', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockExecute.mockResolvedValue([{ affectedRows: 1 } as any, []]);
    mockQuery.mockResolvedValue([REGISTERED_CAPABILITY_ROW] as any);
    mockPublish.mockResolvedValue('1-0');
  });

  // ── Happy path ────────────────────────────────────────────────────────────

  it('returns 201 with registered capability when body is valid', async () => {
    const res = await request(app)
      .post('/v1/capabilities')
      .set('x-request-id', 'trace-abc-123')
      .send(VALID_CAPABILITY_BODY);

    expect(res.status).toBe(201);
    expect(res.body.capability).toBeDefined();
    expect(res.body.capability.capability_id).toBe('cap-tool-001');
    expect(res.body.capability.capability_type).toBe('TOOL');
    expect(res.body.trace_id).toBe('trace-abc-123');
  });

  it('creates a capability_registry row in MySQL', async () => {
    await request(app)
      .post('/v1/capabilities')
      .send(VALID_CAPABILITY_BODY);

    expect(mockExecute).toHaveBeenCalledTimes(1);
    const [sql, params] = (mockExecute as jest.Mock).mock.calls[0] as [string, unknown[]];
    expect(sql).toContain('INSERT INTO capability_registry');
    expect(params).toContain('TOOL');
    expect(params).toContain('cap-tool-001');
    expect(params).toContain('SQL Query Tool');
  });

  it('publishes to events:capability_added Redis stream', async () => {
    await request(app)
      .post('/v1/capabilities')
      .set('x-request-id', 'trace-xyz')
      .send(VALID_CAPABILITY_BODY);

    expect(mockPublish).toHaveBeenCalledTimes(1);
    const [stream, message] = (mockPublish as jest.Mock).mock.calls[0] as [string, Record<string, unknown>];
    expect(stream).toBe('events:capability_added');
    expect(message).toMatchObject({
      capability_type: 'TOOL',
      capability_id: 'cap-tool-001',
      name: 'SQL Query Tool',
      gap_id: 'gap-42',
      validation_score: 0.91,
    });
  });

  it('includes trace_id from x-request-id header in Redis message', async () => {
    await request(app)
      .post('/v1/capabilities')
      .set('x-request-id', 'my-trace-id')
      .send(VALID_CAPABILITY_BODY);

    const [, message] = (mockPublish as jest.Mock).mock.calls[0] as [string, Record<string, unknown>];
    expect(message['trace_id']).toBe('my-trace-id');
  });

  // ── Validation errors ─────────────────────────────────────────────────────

  it('returns 400 when capability_type is missing', async () => {
    const body = { ...VALID_CAPABILITY_BODY };
    delete (body as Partial<typeof VALID_CAPABILITY_BODY>).capability_type;

    const res = await request(app)
      .post('/v1/capabilities')
      .send(body);

    expect(res.status).toBe(400);
    expect(res.body.code).toBe('VALIDATION_ERROR');
    expect(mockExecute).not.toHaveBeenCalled();
    expect(mockPublish).not.toHaveBeenCalled();
  });

  it('returns 400 when capability_type is invalid enum value', async () => {
    const res = await request(app)
      .post('/v1/capabilities')
      .send({ ...VALID_CAPABILITY_BODY, capability_type: 'INVALID' });

    expect(res.status).toBe(400);
    expect(res.body.code).toBe('VALIDATION_ERROR');
  });

  it('returns 400 when name is empty string', async () => {
    const res = await request(app)
      .post('/v1/capabilities')
      .send({ ...VALID_CAPABILITY_BODY, name: '' });

    expect(res.status).toBe(400);
    expect(res.body.code).toBe('VALIDATION_ERROR');
  });

  it('returns 400 when validation_score is out of range', async () => {
    const res = await request(app)
      .post('/v1/capabilities')
      .send({ ...VALID_CAPABILITY_BODY, validation_score: 1.5 });

    expect(res.status).toBe(400);
    expect(res.body.code).toBe('VALIDATION_ERROR');
  });

  // ── Optional fields ───────────────────────────────────────────────────────

  it('succeeds without optional fields (description, spec_json, gap_id)', async () => {
    const res = await request(app)
      .post('/v1/capabilities')
      .send({
        capability_type: 'SKILL',
        capability_id: 'skill-001',
        name: 'Minimal Skill',
      });

    expect(res.status).toBe(201);
    expect(mockExecute).toHaveBeenCalledTimes(1);
  });

  // ── DB error handling ─────────────────────────────────────────────────────

  it('returns 500 when MySQL insert throws', async () => {
    mockExecute.mockRejectedValue(new Error('DB connection lost'));

    const res = await request(app)
      .post('/v1/capabilities')
      .send(VALID_CAPABILITY_BODY);

    expect(res.status).toBe(500);
    expect(res.body.code).toBe('INTERNAL_ERROR');
  });

  // ── GET /v1/capabilities (list) ───────────────────────────────────────────

  it('GET /v1/capabilities returns list from DB', async () => {
    mockQuery.mockResolvedValue([REGISTERED_CAPABILITY_ROW] as any);

    const res = await request(app).get('/v1/capabilities');

    expect(res.status).toBe(200);
    expect(Array.isArray(res.body.capabilities)).toBe(true);
    expect(res.body.count).toBe(1);
  });
});
