import { v4 as uuidv4 } from 'uuid';
import type { RowDataPacket } from 'mysql2';
import { mysqlAdapter } from '../adapters/mysqlAdapter';
import { Tool, CreateToolRequest, UpdateToolRequest } from '../models/tool';
import { logger } from '../utils/logger';

interface ToolRow extends RowDataPacket, Tool {}

export class ToolService {
  async listTools(): Promise<Tool[]> {
    const rows = await mysqlAdapter.query<ToolRow>(
      'SELECT * FROM tools ORDER BY created_at DESC'
    );
    return rows.map(this.mapRow);
  }

  async getTool(toolId: string): Promise<Tool | null> {
    const isNumeric = /^\d+$/.test(toolId);
    const whereClause = isNumeric ? 'id = ?' : 'tool_id = ?';
    const rows = await mysqlAdapter.query<ToolRow>(
      `SELECT * FROM tools WHERE ${whereClause}`,
      [toolId]
    );
    return rows.length > 0 ? this.mapRow(rows[0]) : null;
  }

  async createTool(req: CreateToolRequest): Promise<Tool> {
    const toolId = uuidv4();
    const sql = `
      INSERT INTO tools
        (tool_id, name, description, tool_type, hostname, endpoint,
         auth_method, auth_config, is_dynamic)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    `;
    await mysqlAdapter.execute(sql, [
      toolId,
      req.name,
      req.description ?? null,
      req.tool_type,
      req.hostname ?? null,
      req.endpoint ?? null,
      req.auth_method ?? 'NONE',
      req.auth_config ? JSON.stringify(req.auth_config) : null,
      req.is_dynamic ? 1 : 0,
    ]);

    const tool = await this.getTool(toolId);
    if (!tool) throw new Error('Failed to retrieve tool after creation');

    logger.info('Tool created', 'service', { tool_id: toolId, name: req.name });
    return tool;
  }

  async updateTool(toolId: string, req: UpdateToolRequest): Promise<Tool | null> {
    const fields: string[] = [];
    const params: unknown[] = [];

    const fieldMap: Record<string, unknown> = {
      name: req.name,
      description: req.description,
      tool_type: req.tool_type,
      hostname: req.hostname,
      endpoint: req.endpoint,
      auth_method: req.auth_method,
      auth_config: req.auth_config ? JSON.stringify(req.auth_config) : undefined,
      status: req.status,
      avg_latency_ms: req.avg_latency_ms,
      success_rate: req.success_rate,
    };

    for (const [key, value] of Object.entries(fieldMap)) {
      if (value !== undefined) {
        fields.push(`${key} = ?`);
        params.push(value);
      }
    }

    if (fields.length === 0) return this.getTool(toolId);

    const isNumeric = /^\d+$/.test(toolId);
    const whereClause = isNumeric ? 'id = ?' : 'tool_id = ?';
    params.push(toolId);
    await mysqlAdapter.execute(
      `UPDATE tools SET ${fields.join(', ')} WHERE ${whereClause}`,
      params
    );

    logger.info('Tool updated', 'service', { tool_id: toolId });
    return this.getTool(toolId);
  }

  async deleteTool(toolId: string): Promise<boolean> {
    const isNumeric = /^\d+$/.test(toolId);
    const whereClause = isNumeric ? 'id = ?' : 'tool_id = ?';
    const [result] = await mysqlAdapter.execute(
      `DELETE FROM tools WHERE ${whereClause}`,
      [toolId]
    );
    const affected = result.affectedRows;
    if (affected > 0) {
      logger.info('Tool deleted', 'service', { tool_id: toolId });
    }
    return affected > 0;
  }

  async updateToolHealth(
    toolId: string,
    status: 'ACTIVE' | 'DEGRADED' | 'OFFLINE',
    avgLatencyMs: number,
    successRate: number
  ): Promise<void> {
    await mysqlAdapter.execute(
      `UPDATE tools
       SET status = ?, avg_latency_ms = ?, success_rate = ?, last_health_check = NOW()
       WHERE tool_id = ?`,
      [status, avgLatencyMs, successRate, toolId]
    );
  }

  async getActiveTools(): Promise<Tool[]> {
    const rows = await mysqlAdapter.query<ToolRow>(
      "SELECT * FROM tools WHERE status IN ('ACTIVE', 'DEGRADED') AND endpoint IS NOT NULL"
    );
    return rows.map(this.mapRow);
  }

  private mapRow(row: ToolRow): Tool {
    let authConfig: Record<string, unknown> | null = null;
    if (row.auth_config) {
      try {
        authConfig = typeof row.auth_config === 'string'
          ? JSON.parse(row.auth_config)
          : row.auth_config;
      } catch {
        authConfig = null;
      }
    }
    return {
      id: row.id,
      tool_id: row.tool_id,
      name: row.name,
      description: row.description,
      tool_type: row.tool_type,
      hostname: row.hostname,
      endpoint: row.endpoint,
      auth_method: row.auth_method,
      auth_config: authConfig,
      status: row.status,
      avg_latency_ms: row.avg_latency_ms,
      success_rate: row.success_rate,
      last_health_check: row.last_health_check,
      is_dynamic: Boolean(row.is_dynamic),
      created_at: row.created_at,
      updated_at: row.updated_at,
    };
  }
}

export const toolService = new ToolService();
