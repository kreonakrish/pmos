import { v4 as uuidv4 } from 'uuid';
import { mysqlAdapter } from '../adapters/mysqlAdapter';
import { logger } from '../utils/logger';

export interface AgentExecution {
  id: number;
  execution_id: string;
  agent_id: string;
  agent_name: string;
  prompt: string;
  response: string;
  model: string;
  temperature: number | null;
  latency_ms: number;
  tokens_used: number | null;
  status: 'success' | 'failure';
  error_message: string | null;
  tool_calls: string | null;
  team_id: string | null;
  team_name: string | null;
  conversation_id: string | null;
  source: string | null;
  trace_id: string | null;
  score: number | null;
  created_at: string;
}

export interface RecordExecutionInput {
  prompt: string;
  system_prompt?: string;
  response: string;
  model: string;
  temperature?: number;
  latency_ms: number;
  tokens_used: number | null;
  status: 'success' | 'failure';
  error_message: string | null;
  trace_id?: string;
  source?: 'manual' | 'pipeline' | 'health_check';
  tool_calls?: unknown;
  team_id?: string;
  team_name?: string;
  conversation_id?: string;
  score?: number;
}

class AgentHistoryService {
  /**
   * Record an agent execution result into the history table.
   */
  async recordExecution(
    agentId: string,
    agentName: string,
    input: RecordExecutionInput,
  ): Promise<string> {
    const executionId = uuidv4();

    // Truncate large fields to 64KB to avoid MySQL packet issues
    let responseStr: string | null = null;
    try {
      responseStr = input.response.length > 65000
        ? input.response.slice(0, 65000) + '...[truncated]'
        : input.response;
    } catch {
      responseStr = null;
    }

    let promptStr: string | null = null;
    try {
      promptStr = input.prompt.length > 65000
        ? input.prompt.slice(0, 65000) + '...[truncated]'
        : input.prompt;
    } catch {
      promptStr = null;
    }

    try {
      await mysqlAdapter.execute(
        `INSERT INTO agent_execution_history
          (execution_id, agent_id, agent_name, prompt, response, model, temperature,
           latency_ms, tokens_used, status, error_message, tool_calls,
           team_id, team_name, conversation_id, source, trace_id, score)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
        [
          executionId,
          agentId,
          agentName,
          promptStr,
          responseStr,
          input.model || null,
          input.temperature ?? null,
          input.latency_ms,
          input.tokens_used || null,
          input.status,
          input.error_message || null,
          input.tool_calls ? JSON.stringify(input.tool_calls) : null,
          input.team_id || null,
          input.team_name || null,
          input.conversation_id || null,
          input.source || 'manual',
          input.trace_id || null,
          input.score ?? null,
        ],
      );

      logger.info('agent_execution_recorded', 'service', {
        execution_id: executionId,
        agent_id: agentId,
        agent_name: agentName,
        status: input.status,
        latency_ms: input.latency_ms,
        trace_id: input.trace_id,
        source: input.source || 'manual',
      });

      return executionId;
    } catch (err: unknown) {
      const error = err as Error;
      logger.error('agent_execution_record_failed', 'service', {
        error: error.message,
        agent_id: agentId,
        trace_id: input.trace_id,
      });
      return executionId;
    }
  }

  /**
   * Get execution history for a specific agent, ordered by most recent first.
   */
  async getHistory(
    agentId: string,
    limit: number = 50,
    offset: number = 0,
  ): Promise<{ executions: AgentExecution[]; total: number }> {
    const countRows = await mysqlAdapter.query(
      'SELECT COUNT(*) as total FROM agent_execution_history WHERE agent_id = ?',
      [agentId],
    );
    const total = (countRows[0] as Record<string, number>)?.total ?? 0;

    const rows = await mysqlAdapter.query(
      `SELECT * FROM agent_execution_history
       WHERE agent_id = ?
       ORDER BY created_at DESC
       LIMIT ? OFFSET ?`,
      [agentId, limit, offset],
    );

    const executions: AgentExecution[] = rows.map(mapRow);
    return { executions, total };
  }

  /**
   * Get a single execution by ID.
   */
  async getExecution(executionId: string): Promise<AgentExecution | null> {
    const rows = await mysqlAdapter.query(
      'SELECT * FROM agent_execution_history WHERE execution_id = ? LIMIT 1',
      [executionId],
    );
    if (rows.length === 0) return null;
    return mapRow(rows[0] as Record<string, unknown>);
  }
}

function mapRow(row: Record<string, unknown>): AgentExecution {
  return {
    id: row.id as number,
    execution_id: row.execution_id as string,
    agent_id: row.agent_id as string,
    agent_name: row.agent_name as string,
    prompt: (row.prompt as string) || '',
    response: (row.response as string) || '',
    model: (row.model as string) || '',
    temperature: row.temperature as number | null,
    latency_ms: row.latency_ms as number,
    tokens_used: row.tokens_used as number | null,
    status: row.status as 'success' | 'failure',
    error_message: (row.error_message as string) || null,
    tool_calls: (row.tool_calls as string) || null,
    team_id: (row.team_id as string) || null,
    team_name: (row.team_name as string) || null,
    conversation_id: (row.conversation_id as string) || null,
    source: (row.source as string) || null,
    trace_id: (row.trace_id as string) || null,
    score: row.score != null ? (row.score as number) : null,
    created_at: row.created_at ? new Date(row.created_at as string).toISOString() : '',
  };
}

export const agentHistoryService = new AgentHistoryService();
