/**
 * Unit tests for AgentService — all DB calls are mocked
 */
import { jest } from '@jest/globals';

// Mock the mysqlAdapter before importing agentService
jest.mock('../../app/adapters/mysqlAdapter', () => ({
  mysqlAdapter: {
    query: jest.fn(),
    execute: jest.fn(),
    healthCheck: jest.fn(),
    connect: jest.fn(),
    close: jest.fn(),
  },
}));

jest.mock('../../app/utils/logger', () => ({
  logger: {
    debug: jest.fn(),
    info: jest.fn(),
    warn: jest.fn(),
    error: jest.fn(),
  },
}));

// Stub config so config.ts doesn't throw on missing MYSQL_PASSWORD
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

import { mysqlAdapter } from '../../app/adapters/mysqlAdapter';
import { AgentService } from '../../app/services/agentService';

const mockQuery = mysqlAdapter.query as jest.MockedFunction<typeof mysqlAdapter.query>;
const mockExecute = mysqlAdapter.execute as jest.MockedFunction<typeof mysqlAdapter.execute>;

const makeAgent = (overrides = {}) => ({
  id: 1,
  agent_id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
  name: 'Test Agent',
  description: 'A test agent',
  foundation_model: 'gpt-4o',
  status: 'IDLE',
  accuracy_rate: 0.0,
  success_rate: 0.0,
  total_executions: 0,
  health_score: 1.0,
  meta_capable: 0,
  is_primary: 0,
  degraded_at: null,
  created_at: '2026-01-01T00:00:00.000Z',
  updated_at: '2026-01-01T00:00:00.000Z',
  ...overrides,
});

describe('AgentService', () => {
  let service: AgentService;

  beforeEach(() => {
    jest.clearAllMocks();
    service = new AgentService();
  });

  // ── createAgent ─────────────────────────────────────────────────────────

  describe('createAgent', () => {
    it('inserts a row and returns agent with generated UUID', async () => {
      const agentRow = makeAgent();
      mockExecute.mockResolvedValue([{ affectedRows: 1, insertId: 1 } as any, []]);
      mockQuery.mockResolvedValue([agentRow] as any);

      const result = await service.createAgent({
        name: 'Test Agent',
        description: 'A test agent',
      });

      expect(mockExecute).toHaveBeenCalledTimes(1);
      // Verify INSERT call
      const [sql, params] = (mockExecute as jest.Mock).mock.calls[0] as [string, unknown[]];
      expect(sql).toContain('INSERT INTO agents');
      expect(params[1]).toBe('Test Agent');

      expect(result.name).toBe('Test Agent');
      expect(result.agent_id).toBeTruthy();
    });

    it('sets default foundation_model to gpt-4o when not provided', async () => {
      const agentRow = makeAgent();
      mockExecute.mockResolvedValue([{ affectedRows: 1 } as any, []]);
      mockQuery.mockResolvedValue([agentRow] as any);

      await service.createAgent({ name: 'Agent X' });

      const [, params] = (mockExecute as jest.Mock).mock.calls[0] as [string, unknown[]];
      expect(params[3]).toBe('gpt-4o');
    });

    it('throws if DB returns no row after creation', async () => {
      mockExecute.mockResolvedValue([{ affectedRows: 1 } as any, []]);
      mockQuery.mockResolvedValue([] as any); // getAgent returns empty

      await expect(service.createAgent({ name: 'Ghost' })).rejects.toThrow(
        'Failed to retrieve agent after creation'
      );
    });
  });

  // ── getAgent ────────────────────────────────────────────────────────────

  describe('getAgent', () => {
    it('returns agent when found', async () => {
      const agentRow = makeAgent({ name: 'Found Agent' });
      mockQuery.mockResolvedValue([agentRow] as any);

      const result = await service.getAgent('aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee');

      expect(result).not.toBeNull();
      expect(result!.name).toBe('Found Agent');
    });

    it('returns null when agent does not exist', async () => {
      mockQuery.mockResolvedValue([] as any);

      const result = await service.getAgent('non-existent-id');

      expect(result).toBeNull();
    });

    it('maps boolean fields correctly from MySQL TINYINT', async () => {
      const agentRow = makeAgent({ meta_capable: 1, is_primary: 0 });
      mockQuery.mockResolvedValue([agentRow] as any);

      const result = await service.getAgent('test-id');

      expect(result!.meta_capable).toBe(true);
      expect(result!.is_primary).toBe(false);
    });
  });

  // ── updateAgent ─────────────────────────────────────────────────────────

  describe('updateAgent', () => {
    it('updates the specified fields and returns updated agent', async () => {
      const updatedRow = makeAgent({ name: 'Renamed Agent', status: 'ACTIVE' });
      mockExecute.mockResolvedValue([{ affectedRows: 1 } as any, []]);
      mockQuery.mockResolvedValue([updatedRow] as any);

      const result = await service.updateAgent('aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', {
        name: 'Renamed Agent',
        status: 'ACTIVE',
      });

      expect(mockExecute).toHaveBeenCalledTimes(1);
      const [sql] = (mockExecute as jest.Mock).mock.calls[0] as [string, unknown[]];
      expect(sql).toContain('UPDATE agents SET');
      expect(result!.name).toBe('Renamed Agent');
    });

    it('adds degraded_at = NOW() when status set to DEGRADED', async () => {
      const updatedRow = makeAgent({ status: 'DEGRADED' });
      mockExecute.mockResolvedValue([{ affectedRows: 1 } as any, []]);
      mockQuery.mockResolvedValue([updatedRow] as any);

      await service.updateAgent('test-id', { status: 'DEGRADED' });

      const [sql] = (mockExecute as jest.Mock).mock.calls[0] as [string, unknown[]];
      expect(sql).toContain('degraded_at = NOW()');
    });

    it('returns current agent without DB call when no fields provided', async () => {
      const agentRow = makeAgent();
      mockQuery.mockResolvedValue([agentRow] as any);

      const result = await service.updateAgent('test-id', {});

      expect(mockExecute).not.toHaveBeenCalled();
      expect(result).not.toBeNull();
    });
  });

  // ── deleteAgent ─────────────────────────────────────────────────────────

  describe('deleteAgent', () => {
    it('sets status=DEPRECATED (soft delete) and returns true', async () => {
      mockExecute.mockResolvedValue([{ affectedRows: 1 } as any, []]);

      const result = await service.deleteAgent('aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee');

      expect(result).toBe(true);
      const [sql] = (mockExecute as jest.Mock).mock.calls[0] as [string, unknown[]];
      expect(sql).toContain("status = 'DEPRECATED'");
    });

    it('returns false when agent not found', async () => {
      mockExecute.mockResolvedValue([{ affectedRows: 0 } as any, []]);

      const result = await service.deleteAgent('non-existent');

      expect(result).toBe(false);
    });
  });

  // ── listAgents ──────────────────────────────────────────────────────────

  describe('listAgents', () => {
    it('returns array of agents without filter', async () => {
      const rows = [makeAgent({ name: 'A1' }), makeAgent({ name: 'A2', agent_id: 'id-2' })];
      mockQuery.mockResolvedValue(rows as any);

      const result = await service.listAgents();

      expect(result).toHaveLength(2);
      expect(result[0].name).toBe('A1');
    });

    it('applies status filter in WHERE clause', async () => {
      mockQuery.mockResolvedValue([] as any);

      await service.listAgents({ status: 'ACTIVE' });

      const [sql, params] = (mockQuery as jest.Mock).mock.calls[0] as [string, unknown[]];
      expect(sql).toContain('WHERE');
      expect(sql).toContain('status = ?');
      expect(params).toContain('ACTIVE');
    });

    it('applies meta_capable filter in WHERE clause', async () => {
      mockQuery.mockResolvedValue([] as any);

      await service.listAgents({ meta_capable: true });

      const [sql, params] = (mockQuery as jest.Mock).mock.calls[0] as [string, unknown[]];
      expect(sql).toContain('meta_capable = ?');
      expect(params).toContain(1);
    });

    it('applies combined filters with AND', async () => {
      mockQuery.mockResolvedValue([] as any);

      await service.listAgents({ status: 'IDLE', meta_capable: false });

      const [sql] = (mockQuery as jest.Mock).mock.calls[0] as [string, unknown[]];
      expect(sql).toContain('AND');
    });
  });
});
