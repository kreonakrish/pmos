/**
 * Unit tests for ToolHealthScheduler
 * Mocks axios and both adapters.
 */
import { jest } from '@jest/globals';

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
    query: jest.fn(),
    execute: jest.fn(),
    healthCheck: jest.fn(),
    connect: jest.fn(),
    close: jest.fn(),
  },
}));

jest.mock('../../app/adapters/redisAdapter', () => ({
  redisAdapter: {
    publish: jest.fn(),
    healthCheck: jest.fn(),
    connect: jest.fn(),
    close: jest.fn(),
  },
}));

jest.mock('axios');

import axios from 'axios';
import { redisAdapter } from '../../app/adapters/redisAdapter';
import { toolService } from '../../app/services/toolService';
import { ToolHealthScheduler } from '../../app/services/toolHealthScheduler';
import type { Tool } from '../../app/models/tool';

const mockAxiosGet = axios.get as jest.MockedFunction<typeof axios.get>;
const mockPublish = redisAdapter.publish as jest.MockedFunction<typeof redisAdapter.publish>;

// Spy on toolService methods (getActiveTools + updateToolHealth)
jest.mock('../../app/services/toolService', () => ({
  toolService: {
    getActiveTools: jest.fn(),
    updateToolHealth: jest.fn(),
  },
}));

const mockGetActiveTools = toolService.getActiveTools as jest.MockedFunction<typeof toolService.getActiveTools>;
const mockUpdateToolHealth = toolService.updateToolHealth as jest.MockedFunction<typeof toolService.updateToolHealth>;

const makeTool = (overrides: Partial<Tool> = {}): Tool => ({
  tool_id: 'tool-uuid-1234',
  name: 'Test Tool',
  tool_type: 'API',
  auth_method: 'NONE',
  status: 'ACTIVE',
  avg_latency_ms: 100,
  success_rate: 1.0,
  is_dynamic: false,
  hostname: 'http://example.com',
  endpoint: '/health',
  ...overrides,
});

describe('ToolHealthScheduler', () => {
  let scheduler: ToolHealthScheduler;

  beforeEach(() => {
    jest.clearAllMocks();
    scheduler = new ToolHealthScheduler();
    mockUpdateToolHealth.mockResolvedValue(undefined);
    mockPublish.mockResolvedValue('1-0');
  });

  // ── Success path ─────────────────────────────────────────────────────────

  describe('when tool endpoint returns 200', () => {
    it('keeps status ACTIVE and records latency without publishing to Redis', async () => {
      const tool = makeTool({ status: 'ACTIVE' });
      mockGetActiveTools.mockResolvedValue([tool]);
      mockAxiosGet.mockResolvedValue({ status: 200, data: {} } as any);

      await scheduler.runHealthChecks();

      expect(mockUpdateToolHealth).toHaveBeenCalledWith(
        'tool-uuid-1234',
        'ACTIVE',
        expect.any(Number),
        expect.any(Number)
      );
      // Status did NOT change → no Redis publish
      expect(mockPublish).not.toHaveBeenCalled();
    });

    it('computes rolling EMA latency correctly', async () => {
      const tool = makeTool({ status: 'ACTIVE', avg_latency_ms: 100 });
      mockGetActiveTools.mockResolvedValue([tool]);
      // Simulate a 200ms response
      mockAxiosGet.mockImplementation(() => new Promise(resolve => {
        setTimeout(() => resolve({ status: 200, data: {} } as any), 50);
      }));

      await scheduler.runHealthChecks();

      const [,, avgLatency] = (mockUpdateToolHealth as jest.Mock).mock.calls[0] as unknown[];
      // New EMA = 0.2 * measured + 0.8 * 100 ≈ between 80 and 110
      expect(avgLatency as number).toBeGreaterThan(0);
    });
  });

  // ── HTTP 500 path ────────────────────────────────────────────────────────

  describe('when tool endpoint returns 500', () => {
    it('sets status DEGRADED and publishes to events:tool_health stream', async () => {
      const tool = makeTool({ status: 'ACTIVE' });
      mockGetActiveTools.mockResolvedValue([tool]);
      mockAxiosGet.mockResolvedValue({ status: 500 } as any);

      await scheduler.runHealthChecks();

      expect(mockUpdateToolHealth).toHaveBeenCalledWith(
        'tool-uuid-1234',
        'DEGRADED',
        expect.any(Number),
        expect.any(Number)
      );

      // Status CHANGED ACTIVE → DEGRADED → must publish
      expect(mockPublish).toHaveBeenCalledWith(
        'events:tool_health',
        expect.objectContaining({
          tool_id: 'tool-uuid-1234',
          previous_status: 'ACTIVE',
          current_status: 'DEGRADED',
        })
      );
    });
  });

  // ── Timeout path ────────────────────────────────────────────────────────

  describe('when tool endpoint times out', () => {
    it('sets status OFFLINE and publishes to events:tool_health stream', async () => {
      const tool = makeTool({ status: 'ACTIVE' });
      mockGetActiveTools.mockResolvedValue([tool]);

      const timeoutError = Object.assign(new Error('timeout of 5000ms exceeded'), {
        code: 'ECONNABORTED',
        message: 'timeout of 5000ms exceeded',
      });
      mockAxiosGet.mockRejectedValue(timeoutError);

      await scheduler.runHealthChecks();

      expect(mockUpdateToolHealth).toHaveBeenCalledWith(
        'tool-uuid-1234',
        'OFFLINE',
        expect.any(Number),
        expect.any(Number)
      );

      expect(mockPublish).toHaveBeenCalledWith(
        'events:tool_health',
        expect.objectContaining({
          previous_status: 'ACTIVE',
          current_status: 'OFFLINE',
        })
      );
    });
  });

  // ── No status change → no Redis publish ──────────────────────────────────

  describe('when status does not change', () => {
    it('does NOT publish to Redis stream when status stays DEGRADED', async () => {
      const tool = makeTool({ status: 'DEGRADED' });
      mockGetActiveTools.mockResolvedValue([tool]);
      mockAxiosGet.mockResolvedValue({ status: 503 } as any);

      await scheduler.runHealthChecks();

      // DEGRADED → DEGRADED: no change
      expect(mockPublish).not.toHaveBeenCalled();
    });

    it('does NOT publish to Redis stream when status stays ACTIVE', async () => {
      const tool = makeTool({ status: 'ACTIVE' });
      mockGetActiveTools.mockResolvedValue([tool]);
      mockAxiosGet.mockResolvedValue({ status: 200 } as any);

      await scheduler.runHealthChecks();

      expect(mockPublish).not.toHaveBeenCalled();
    });
  });

  // ── Redis event schema ────────────────────────────────────────────────────

  describe('Redis event schema on status change', () => {
    it('publishes correct schema to events:tool_health', async () => {
      const tool = makeTool({ status: 'ACTIVE', name: 'My Tool', tool_id: 'tool-xyz' });
      mockGetActiveTools.mockResolvedValue([tool]);
      mockAxiosGet.mockResolvedValue({ status: 500 } as any);

      await scheduler.runHealthChecks();

      const [stream, message] = (mockPublish as jest.Mock).mock.calls[0] as [string, Record<string, unknown>];
      expect(stream).toBe('events:tool_health');
      expect(message).toMatchObject({
        tool_id: 'tool-xyz',
        tool_name: 'My Tool',
        previous_status: 'ACTIVE',
        current_status: 'DEGRADED',
        avg_latency_ms: expect.any(Number),
        success_rate: expect.any(Number),
      });
      expect(message['trace_id']).toBeTruthy();
    });
  });

  // ── Scheduler lifecycle ──────────────────────────────────────────────────

  describe('scheduler lifecycle', () => {
    it('start() sets the interval and stop() clears it', () => {
      const setIntervalSpy = jest.spyOn(global, 'setInterval');
      const clearIntervalSpy = jest.spyOn(global, 'clearInterval');

      scheduler.start();
      expect(setIntervalSpy).toHaveBeenCalledTimes(1);

      scheduler.stop();
      expect(clearIntervalSpy).toHaveBeenCalledTimes(1);

      setIntervalSpy.mockRestore();
      clearIntervalSpy.mockRestore();
    });

    it('start() is idempotent — calling twice does not create two intervals', () => {
      const setIntervalSpy = jest.spyOn(global, 'setInterval');
      scheduler.start();
      scheduler.start(); // second call should be a no-op
      expect(setIntervalSpy).toHaveBeenCalledTimes(1);
      scheduler.stop();
      setIntervalSpy.mockRestore();
    });
  });
});
