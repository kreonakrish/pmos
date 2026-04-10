/**
 * Integration tests for route proxying.
 * Uses nock to mock downstream services.
 * Starts the actual Express app (no real Redis / DB).
 */

import request from 'supertest';
import nock from 'nock';
import jwt from 'jsonwebtoken';
import EventEmitter from 'events';

// ─── Environment setup ────────────────────────────────────────────────────────
const TEST_SECRET = 'integration-test-secret-32-chars!!';
const TEST_API_KEY = 'integration-api-key-1234';

process.env['JWT_SECRET'] = TEST_SECRET;
process.env['API_KEY'] = TEST_API_KEY;
process.env['ORCHESTRATOR_URL'] = 'http://mock-orchestrator:8000';
process.env['AGENT_MGMT_URL'] = 'http://mock-agent-mgmt:4001';
process.env['RAG_SERVICE_URL'] = 'http://mock-rag:8002';
process.env['REDIS_URL'] = 'redis://localhost:6379';
process.env['RATE_LIMIT_RPM'] = '1000'; // high so we don't hit it in tests

// ─── Mock Redis so rate limiter doesn't need a real Redis ─────────────────────
jest.mock('ioredis', () => {
  return jest.fn().mockImplementation(() => {
    const emitter = new EventEmitter();
    return {
      eval: jest.fn().mockResolvedValue([1, 60]),
      disconnect: jest.fn(),
      on: emitter.on.bind(emitter),
    };
  });
});

// Import AFTER mocks are in place
import { app } from '../../app/main';

// ─── Helper ───────────────────────────────────────────────────────────────────
function validToken(sub = 'user-test-1'): string {
  return jwt.sign({ sub }, TEST_SECRET, { expiresIn: '1h' });
}

// ─── Tests ────────────────────────────────────────────────────────────────────

beforeAll(() => {
  nock.disableNetConnect();
  nock.enableNetConnect('127.0.0.1');
});

afterAll(() => {
  nock.cleanAll();
  nock.enableNetConnect();
});

afterEach(() => {
  nock.cleanAll();
});

describe('GET /health', () => {
  it('returns 200 with aggregated status even when all services are down', async () => {
    // nock returns ECONNREFUSED for all downstream /health calls
    nock('http://mock-orchestrator:8000').get('/health').replyWithError('ECONNREFUSED');
    nock('http://mock-agent-mgmt:4001').get('/health').replyWithError('ECONNREFUSED');
    nock('http://mock-rag:8002').get('/health').replyWithError('ECONNREFUSED');
    nock('http://localhost:8003').get('/health').replyWithError('ECONNREFUSED');
    nock('http://localhost:8001').get('/health').replyWithError('ECONNREFUSED');
    nock('http://localhost:8004').get('/health').replyWithError('ECONNREFUSED');

    const res = await request(app).get('/health').expect(200);

    expect(res.body.status).toBe('down');
    expect(res.body.services).toBeDefined();
    expect(res.body.timestamp).toBeDefined();
  });

  it('returns overall ok when all services respond 200', async () => {
    nock('http://mock-orchestrator:8000').get('/health').reply(200, { status: 'ok' });
    nock('http://mock-agent-mgmt:4001').get('/health').reply(200, { status: 'ok' });
    nock('http://mock-rag:8002').get('/health').reply(200, { status: 'ok' });
    nock('http://localhost:8003').get('/health').reply(200, { status: 'ok' });
    nock('http://localhost:8001').get('/health').reply(200, { status: 'ok' });
    nock('http://localhost:8004').get('/health').reply(200, { status: 'ok' });

    const res = await request(app).get('/health').expect(200);

    expect(res.body.status).toBe('ok');
    expect(res.body.services['orchestrator'].status).toBe('ok');
    expect(res.body.services['agent-mgmt'].status).toBe('ok');
  });

  it('does not require authentication', async () => {
    nock('http://mock-orchestrator:8000').get('/health').replyWithError('ECONNREFUSED');
    nock('http://mock-agent-mgmt:4001').get('/health').replyWithError('ECONNREFUSED');
    nock('http://mock-rag:8002').get('/health').replyWithError('ECONNREFUSED');
    nock('http://localhost:8003').get('/health').replyWithError('ECONNREFUSED');
    nock('http://localhost:8001').get('/health').replyWithError('ECONNREFUSED');
    nock('http://localhost:8004').get('/health').replyWithError('ECONNREFUSED');

    // No Authorization header
    await request(app).get('/health').expect(200);
  });
});

describe('POST /v1/chat', () => {
  it('proxies to orchestrator with x-request-id forwarded', async () => {
    const traceId = 'test-trace-id-abc-123';

    nock('http://mock-orchestrator:8000')
      .post('/v1/orchestrator/chat')
      .matchHeader('x-request-id', traceId)
      .reply(200, { task_id: 'task-001', status: 'processing' });

    const res = await request(app)
      .post('/v1/chat')
      .set('Authorization', `Bearer ${validToken()}`)
      .set('x-request-id', traceId)
      .send({ message: 'Hello world' })
      .expect(200);

    expect(res.body.task_id).toBe('task-001');
  });

  it('returns 401 without an auth token', async () => {
    const res = await request(app)
      .post('/v1/chat')
      .send({ message: 'Hello' })
      .expect(401);

    expect(res.body.code).toBe('AUTH_FAILED');
  });

  it('auto-generates x-request-id if not provided', async () => {
    nock('http://mock-orchestrator:8000')
      .post('/v1/orchestrator/chat')
      .reply(200, { task_id: 'task-002' });

    const res = await request(app)
      .post('/v1/chat')
      .set('Authorization', `Bearer ${validToken()}`)
      .send({ message: 'Test' })
      .expect(200);

    // The response should have the x-request-id header set
    expect(res.headers['x-request-id']).toBeDefined();
    expect(res.headers['x-request-id'].length).toBeGreaterThan(0);
  });
});

describe('GET /v1/agents', () => {
  it('proxies to agent-mgmt service', async () => {
    nock('http://mock-agent-mgmt:4001')
      .get('/v1/agents')
      .reply(200, { agents: [{ id: 1, name: 'Agent Alpha' }] });

    const res = await request(app)
      .get('/v1/agents')
      .set('Authorization', `Bearer ${validToken()}`)
      .expect(200);

    expect(res.body.agents).toHaveLength(1);
    expect(res.body.agents[0].name).toBe('Agent Alpha');
  });

  it('returns 401 without auth', async () => {
    await request(app).get('/v1/agents').expect(401);
  });
});

describe('POST /v1/rag/query', () => {
  it('proxies to RAG service', async () => {
    nock('http://mock-rag:8002')
      .post('/v1/rag/query')
      .reply(200, { results: [], sources_queried: ['faiss'], latency_ms: 5 });

    const res = await request(app)
      .post('/v1/rag/query')
      .set('Authorization', `Bearer ${validToken()}`)
      .send({ query: 'What is PMOS?', agent_id: 1, top_k: 5 })
      .expect(200);

    expect(res.body.sources_queried).toContain('faiss');
  });
});

describe('GET /metrics', () => {
  it('returns Prometheus metrics without auth', async () => {
    const res = await request(app).get('/metrics').expect(200);
    expect(res.text).toContain('request_total');
    expect(res.text).toContain('request_duration_seconds');
  });
});
