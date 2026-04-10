import axios from 'axios';
import { v4 as uuidv4 } from 'uuid';
import { toolService } from './toolService';
import { redisAdapter } from '../adapters/redisAdapter';
import { logger } from '../utils/logger';
import { config } from '../config';
import type { Tool, ToolStatus } from '../models/tool';

const STREAM_TOOL_HEALTH = 'events:tool_health';
const HEALTH_CHECK_TIMEOUT_MS = 5000;
const LATENCY_ROLLING_ALPHA = 0.2; // EMA smoothing factor for latency

interface HealthResult {
  status: ToolStatus;
  latencyMs: number;
  success: boolean;
}

export class ToolHealthScheduler {
  private timer: ReturnType<typeof setInterval> | null = null;
  private running = false;

  start(): void {
    if (this.timer) return;
    const intervalMs = config.TOOL_HEALTH_INTERVAL_SEC * 1000;
    logger.info('Tool health scheduler started', 'scheduler', {
      interval_sec: config.TOOL_HEALTH_INTERVAL_SEC,
    });
    this.timer = setInterval(() => {
      this.runHealthChecks().catch((err: Error) => {
        logger.error('Tool health check cycle failed', 'scheduler', {
          error: err.message,
        });
      });
    }, intervalMs);
  }

  stop(): void {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
      logger.info('Tool health scheduler stopped', 'scheduler');
    }
  }

  async runHealthChecks(): Promise<void> {
    if (this.running) {
      logger.warn('Health check already running, skipping cycle', 'scheduler');
      return;
    }
    this.running = true;

    try {
      const tools = await toolService.getActiveTools();
      logger.info(`Running health checks for ${tools.length} tools`, 'scheduler');

      await Promise.allSettled(tools.map((tool) => this.checkTool(tool)));
    } finally {
      this.running = false;
    }
  }

  private async checkTool(tool: Tool): Promise<void> {
    const traceId = uuidv4();
    const previousStatus = tool.status;
    let result: HealthResult;

    try {
      result = await this.performHealthCheck(tool);
    } catch (err: unknown) {
      const error = err as Error;
      logger.warn('Health check threw exception', 'scheduler', {
        tool_id: tool.tool_id,
        error: error.message,
        trace_id: traceId,
      });
      result = { status: 'OFFLINE', latencyMs: 0, success: false };
    }

    // Compute rolling average latency (EMA)
    const newAvgLatency =
      result.latencyMs > 0
        ? LATENCY_ROLLING_ALPHA * result.latencyMs +
          (1 - LATENCY_ROLLING_ALPHA) * (tool.avg_latency_ms || result.latencyMs)
        : tool.avg_latency_ms;

    // Compute rolling success rate (EMA)
    const newSuccessRate =
      LATENCY_ROLLING_ALPHA * (result.success ? 1 : 0) +
      (1 - LATENCY_ROLLING_ALPHA) * (tool.success_rate || (result.success ? 1 : 0));

    // Update tool health in DB
    await toolService.updateToolHealth(
      tool.tool_id,
      result.status,
      newAvgLatency,
      newSuccessRate
    );

    // Only publish to Redis stream if status CHANGED
    if (previousStatus !== result.status) {
      await redisAdapter.publish(STREAM_TOOL_HEALTH, {
        trace_id: traceId,
        tool_id: tool.tool_id,
        tool_name: tool.name,
        previous_status: previousStatus,
        current_status: result.status,
        avg_latency_ms: newAvgLatency,
        success_rate: newSuccessRate,
      });

      logger.info('Tool status changed, event published', 'scheduler', {
        tool_id: tool.tool_id,
        previous_status: previousStatus,
        current_status: result.status,
        trace_id: traceId,
      });
    }
  }

  private async performHealthCheck(tool: Tool): Promise<HealthResult> {
    if (!tool.hostname && !tool.endpoint) {
      return { status: 'ACTIVE', latencyMs: 0, success: true };
    }

    const endpoint = tool.endpoint ?? '';
    const hostname = tool.hostname ?? '';

    // Non-HTTP tools (database, subprocess, etc.) cannot be health-checked via GET
    // Mark them as ACTIVE if they have a valid endpoint configured
    if (
      endpoint.startsWith('mysql://') ||
      endpoint.startsWith('postgresql://') ||
      endpoint.startsWith('mongodb://') ||
      endpoint.startsWith('redis://') ||
      endpoint.startsWith('subprocess://') ||
      tool.tool_type === 'PYTHON' ||
      tool.tool_type === 'DATABASE' ||
      tool.tool_type === 'GRAPH' ||
      endpoint.startsWith('neo4j://') ||
      endpoint.startsWith('neo4j+s://') ||
      endpoint.startsWith('bolt://')
    ) {
      return { status: 'ACTIVE', latencyMs: 0, success: true };
    }

    // For HTTP-based tools, attempt a GET request
    let url = endpoint;
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
      // Try constructing from hostname + endpoint
      if (hostname.startsWith('http://') || hostname.startsWith('https://')) {
        url = hostname;
      } else if (hostname) {
        url = `https://${hostname}`;
      } else {
        // No valid HTTP URL to check
        return { status: 'ACTIVE', latencyMs: 0, success: true };
      }
    }

    const startTime = Date.now();

    try {
      const response = await axios.get(url, {
        timeout: HEALTH_CHECK_TIMEOUT_MS,
        validateStatus: null, // Don't throw on any status code
      });
      const latencyMs = Date.now() - startTime;

      if (response.status >= 200 && response.status < 500) {
        return { status: 'ACTIVE', latencyMs, success: true };
      } else {
        return { status: 'DEGRADED', latencyMs, success: false };
      }
    } catch (err: unknown) {
      const error = err as NodeJS.ErrnoException & { code?: string };
      const latencyMs = Date.now() - startTime;

      if (
        error.code === 'ECONNABORTED' ||
        error.code === 'ETIMEDOUT' ||
        error.message?.includes('timeout')
      ) {
        return { status: 'OFFLINE', latencyMs, success: false };
      }
      return { status: 'DEGRADED', latencyMs, success: false };
    }
  }
}

export const toolHealthScheduler = new ToolHealthScheduler();
