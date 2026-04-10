import { v4 as uuidv4 } from 'uuid';
import type { RowDataPacket } from 'mysql2';
import { mysqlAdapter } from '../adapters/mysqlAdapter';
import {
  Agent,
  AgentFilter,
  AgentTool,
  AssignToolRequest,
  CreateAgentRequest,
  UpdateAgentRequest,
} from '../models/agent';
import { logger } from '../utils/logger';

interface AgentRow extends RowDataPacket, Agent {}
interface AgentToolRow extends RowDataPacket, AgentTool {}

export class AgentService {
  async listAgents(filter: AgentFilter = {}): Promise<Agent[]> {
    const conditions: string[] = [];
    const params: unknown[] = [];

    if (filter.status !== undefined) {
      conditions.push('status = ?');
      params.push(filter.status);
    }
    if (filter.meta_capable !== undefined) {
      conditions.push('meta_capable = ?');
      params.push(filter.meta_capable ? 1 : 0);
    }

    const where = conditions.length > 0 ? `WHERE ${conditions.join(' AND ')}` : '';
    const sql = `SELECT * FROM agents ${where} ORDER BY created_at DESC`;

    const rows = await mysqlAdapter.query<AgentRow>(sql, params);
    return rows.map(this.mapRow);
  }

  async getAgent(agentId: string): Promise<Agent | null> {
    const isNumeric = /^\d+$/.test(agentId);
    const whereClause = isNumeric ? 'id = ?' : 'agent_id = ?';
    const rows = await mysqlAdapter.query<AgentRow>(
      `SELECT * FROM agents WHERE ${whereClause}`,
      [agentId]
    );
    return rows.length > 0 ? this.mapRow(rows[0]) : null;
  }

  async createAgent(req: CreateAgentRequest): Promise<Agent> {
    const agentId = uuidv4();
    const sql = `
      INSERT INTO agents
        (agent_id, name, description, foundation_model, status, meta_capable, is_primary)
      VALUES (?, ?, ?, ?, 'IDLE', ?, ?)
    `;
    await mysqlAdapter.execute(sql, [
      agentId,
      req.name,
      req.description ?? null,
      req.foundation_model ?? 'gpt-4o',
      req.meta_capable ? 1 : 0,
      req.is_primary ? 1 : 0,
    ]);

    const agent = await this.getAgent(agentId);
    if (!agent) throw new Error('Failed to retrieve agent after creation');

    logger.info('Agent created', 'service', { agent_id: agentId, name: req.name });
    return agent;
  }

  async updateAgent(agentId: string, req: UpdateAgentRequest): Promise<Agent | null> {
    const fields: string[] = [];
    const params: unknown[] = [];

    const fieldMap: Record<string, unknown> = {
      name: req.name,
      description: req.description,
      foundation_model: req.foundation_model,
      status: req.status,
      meta_capable: req.meta_capable !== undefined ? (req.meta_capable ? 1 : 0) : undefined,
      is_primary: req.is_primary !== undefined ? (req.is_primary ? 1 : 0) : undefined,
      accuracy_rate: req.accuracy_rate,
      success_rate: req.success_rate,
      health_score: req.health_score,
      memory_seed: req.memory_seed,
      reasoning_seed: req.reasoning_seed,
    };

    for (const [key, value] of Object.entries(fieldMap)) {
      if (value !== undefined) {
        fields.push(`${key} = ?`);
        params.push(value);
      }
    }

    if (req.status === 'DEGRADED') {
      fields.push('degraded_at = NOW()');
    } else if (req.status) {
      fields.push('degraded_at = NULL');
    }

    if (fields.length === 0) return this.getAgent(agentId);

    const isNumeric = /^\d+$/.test(agentId);
    const whereClause = isNumeric ? 'id = ?' : 'agent_id = ?';
    params.push(agentId);
    await mysqlAdapter.execute(
      `UPDATE agents SET ${fields.join(', ')} WHERE ${whereClause}`,
      params
    );

    logger.info('Agent updated', 'service', { agent_id: agentId });
    return this.getAgent(agentId);
  }

  async deleteAgent(agentId: string): Promise<boolean> {
    // Soft delete — set status to DEPRECATED
    const isNumeric = /^\d+$/.test(agentId);
    const whereClause = isNumeric ? 'id = ?' : 'agent_id = ?';
    const [result] = await mysqlAdapter.execute(
      `UPDATE agents SET status = 'DEPRECATED' WHERE ${whereClause}`,
      [agentId]
    );
    const affected = result.affectedRows;
    if (affected > 0) {
      logger.info('Agent soft-deleted (DEPRECATED)', 'service', { agent_id: agentId });
    }
    return affected > 0;
  }

  async listAgentTools(agentId: string): Promise<AgentTool[]> {
    const rows = await mysqlAdapter.query<AgentToolRow>(
      `SELECT at.agent_id, at.tool_id, at.permission_level, at.assigned_at,
              t.name as tool_name, t.description as tool_description,
              t.tool_type, t.status as tool_status,
              t.endpoint as tool_endpoint, t.auth_config as tool_auth_config
       FROM agent_tools at
       JOIN tools t ON t.tool_id = at.tool_id
       WHERE at.agent_id = ?`,
      [agentId]
    );
    return rows;
  }

  async assignTool(agentId: string, req: AssignToolRequest): Promise<void> {
    await mysqlAdapter.execute(
      `INSERT INTO agent_tools (agent_id, tool_id, permission_level)
       VALUES (?, ?, ?)
       ON DUPLICATE KEY UPDATE permission_level = VALUES(permission_level)`,
      [agentId, req.tool_id, req.permission_level ?? 'READ']
    );
    logger.info('Tool assigned to agent', 'service', {
      agent_id: agentId,
      tool_id: req.tool_id,
    });
  }

  async syncTools(agentId: string, toolIds: string[]): Promise<AgentTool[]> {
    // Delete all existing tool assignments for this agent
    await mysqlAdapter.execute(
      'DELETE FROM agent_tools WHERE agent_id = ?',
      [agentId]
    );

    // Insert new assignments
    for (const toolId of toolIds) {
      await mysqlAdapter.execute(
        `INSERT INTO agent_tools (agent_id, tool_id, permission_level)
         VALUES (?, ?, 'READ')`,
        [agentId, toolId]
      );
    }

    logger.info('Agent tools synced', 'service', {
      agent_id: agentId,
      tool_count: toolIds.length,
    });

    return this.listAgentTools(agentId);
  }

  async removeTool(agentId: string, toolId: string): Promise<boolean> {
    const [result] = await mysqlAdapter.execute(
      'DELETE FROM agent_tools WHERE agent_id = ? AND tool_id = ?',
      [agentId, toolId]
    );
    const affected = result.affectedRows;
    if (affected > 0) {
      logger.info('Tool removed from agent', 'service', {
        agent_id: agentId,
        tool_id: toolId,
      });
    }
    return affected > 0;
  }

  private mapRow(row: AgentRow): Agent {
    return {
      id: row.id,
      agent_id: row.agent_id,
      name: row.name,
      description: row.description,
      foundation_model: row.foundation_model,
      status: row.status,
      accuracy_rate: row.accuracy_rate,
      success_rate: row.success_rate,
      total_executions: row.total_executions,
      health_score: row.health_score,
      meta_capable: Boolean(row.meta_capable),
      is_primary: Boolean(row.is_primary),
      memory_seed: row.memory_seed ?? null,
      reasoning_seed: row.reasoning_seed ?? null,
      degraded_at: row.degraded_at,
      created_at: row.created_at,
      updated_at: row.updated_at,
    };
  }
}

export const agentService = new AgentService();
