import { v4 as uuidv4 } from 'uuid';
import { mysqlAdapter } from '../adapters/mysqlAdapter';
import { logger } from '../utils/logger';
import type { ToolTestResult } from './toolExecutor';

export interface ExecutionContext {
  agent_id?: string;
  agent_name?: string;
  team_id?: string;
  team_name?: string;
  conversation_id?: string;
  source?: 'manual' | 'pipeline' | 'health_check';
}

export interface ToolExecution {
  id: number;
  execution_id: string;
  tool_id: string;
  tool_type: string;
  status: 'success' | 'failure';
  inputs: Record<string, unknown> | null;
  output: unknown | null;
  error_message: string | null;
  latency_ms: number;
  trace_id: string | null;
  agent_id: string | null;
  agent_name: string | null;
  team_id: string | null;
  team_name: string | null;
  conversation_id: string | null;
  source: string | null;
  created_at: string;
}

class ToolHistoryService {
  /**
   * Record a tool execution result into the history table.
   */
  async recordExecution(
    toolId: string,
    inputs: Record<string, unknown>,
    result: ToolTestResult,
    context: ExecutionContext = {},
  ): Promise<string> {
    const executionId = uuidv4();
    const status = result.success ? 'success' : 'failure';

    // Truncate large outputs to 64KB to avoid MySQL packet issues
    let outputJson: string | null = null;
    try {
      const raw = JSON.stringify(result.output);
      outputJson = raw.length > 65000 ? JSON.stringify({ truncated: true, preview: raw.slice(0, 2000) }) : raw;
    } catch {
      outputJson = null;
    }

    let inputsJson: string | null = null;
    try {
      const raw = JSON.stringify(inputs);
      inputsJson = raw.length > 65000 ? JSON.stringify({ truncated: true }) : raw;
    } catch {
      inputsJson = null;
    }

    try {
      await mysqlAdapter.execute(
        `INSERT INTO tool_execution_history
          (execution_id, tool_id, tool_type, status, inputs, output, error_message,
           latency_ms, trace_id, agent_id, agent_name, team_id, team_name, conversation_id, source)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
        [
          executionId,
          toolId,
          result.tool_type,
          status,
          inputsJson,
          outputJson,
          result.error || null,
          result.latency_ms,
          result.trace_id || null,
          context.agent_id || null,
          context.agent_name || null,
          context.team_id || null,
          context.team_name || null,
          context.conversation_id || null,
          context.source || 'manual',
        ],
      );

      logger.info('tool_execution_recorded', 'service', {
        execution_id: executionId,
        tool_id: toolId,
        status,
        latency_ms: result.latency_ms,
        trace_id: result.trace_id,
        agent_id: context.agent_id,
        team_id: context.team_id,
        conversation_id: context.conversation_id,
        source: context.source || 'manual',
      });

      return executionId;
    } catch (err: unknown) {
      const error = err as Error;
      logger.error('tool_execution_record_failed', 'service', {
        error: error.message,
        tool_id: toolId,
        trace_id: result.trace_id,
      });
      return executionId;
    }
  }

  /**
   * Get execution history for a specific tool, ordered by most recent first.
   */
  async getHistory(
    toolId: string,
    limit: number = 50,
    offset: number = 0,
  ): Promise<{ executions: ToolExecution[]; total: number }> {
    const countRows = await mysqlAdapter.query(
      'SELECT COUNT(*) as total FROM tool_execution_history WHERE tool_id = ?',
      [toolId],
    );
    const total = (countRows[0] as Record<string, number>)?.total ?? 0;

    const rows = await mysqlAdapter.query(
      `SELECT * FROM tool_execution_history
       WHERE tool_id = ?
       ORDER BY created_at DESC
       LIMIT ? OFFSET ?`,
      [toolId, limit, offset],
    );

    const executions: ToolExecution[] = rows.map(mapRow);
    return { executions, total };
  }

  /**
   * Get a single execution by ID.
   */
  async getExecution(executionId: string): Promise<ToolExecution | null> {
    const rows = await mysqlAdapter.query(
      'SELECT * FROM tool_execution_history WHERE execution_id = ? LIMIT 1',
      [executionId],
    );
    if (rows.length === 0) return null;
    return mapRow(rows[0] as Record<string, unknown>);
  }
}

function mapRow(row: Record<string, unknown>): ToolExecution {
  return {
    id: row.id as number,
    execution_id: row.execution_id as string,
    tool_id: row.tool_id as string,
    tool_type: row.tool_type as string,
    status: row.status as 'success' | 'failure',
    inputs: parseJson(row.inputs),
    output: parseJson(row.output),
    error_message: (row.error_message as string) || null,
    latency_ms: row.latency_ms as number,
    trace_id: (row.trace_id as string) || null,
    agent_id: (row.agent_id as string) || null,
    agent_name: (row.agent_name as string) || null,
    team_id: (row.team_id as string) || null,
    team_name: (row.team_name as string) || null,
    conversation_id: (row.conversation_id as string) || null,
    source: (row.source as string) || null,
    created_at: row.created_at ? new Date(row.created_at as string).toISOString() : '',
  };
}

function parseJson(val: unknown): Record<string, unknown> | null {
  if (val === null || val === undefined) return null;
  if (typeof val === 'object') return val as Record<string, unknown>;
  if (typeof val === 'string') {
    try {
      return JSON.parse(val);
    } catch {
      return null;
    }
  }
  return null;
}

export const toolHistoryService = new ToolHistoryService();
