import type { RowDataPacket } from 'mysql2';
import { mysqlAdapter } from '../adapters/mysqlAdapter';
import { redisAdapter } from '../adapters/redisAdapter';
import { logger } from '../utils/logger';
import { v4 as uuidv4 } from 'uuid';

export interface RegisterCapabilityRequest {
  capability_type: 'TOOL' | 'SKILL' | 'AGENT';
  capability_id: string;
  name: string;
  description?: string;
  spec_json?: Record<string, unknown>;
  gap_id?: string;
  validation_score?: number;
  trace_id?: string;
}

export interface Capability {
  id?: number;
  capability_type: string;
  capability_id: string;
  name: string;
  description?: string;
  spec_json?: Record<string, unknown> | null;
  source: string;
  gap_id?: string;
  validation_score?: number;
  is_active: boolean;
  usage_count: number;
  last_used?: string | null;
  created_at?: string;
}

interface CapabilityRow extends RowDataPacket, Capability {}

const STREAM_CAPABILITY_ADDED = 'events:capability_added';

export class CapabilityService {
  async registerCapability(req: RegisterCapabilityRequest): Promise<Capability> {
    const traceId = req.trace_id || uuidv4();

    const sql = `
      INSERT INTO capability_registry
        (capability_type, capability_id, name, description,
         spec_json, source, gap_id, validation_score)
      VALUES (?, ?, ?, ?, ?, 'DYNAMIC', ?, ?)
      ON DUPLICATE KEY UPDATE
        name = VALUES(name),
        description = VALUES(description),
        spec_json = VALUES(spec_json),
        validation_score = VALUES(validation_score),
        is_active = TRUE
    `;

    await mysqlAdapter.execute(sql, [
      req.capability_type,
      req.capability_id,
      req.name,
      req.description ?? null,
      req.spec_json ? JSON.stringify(req.spec_json) : null,
      req.gap_id ?? null,
      req.validation_score ?? null,
    ]);

    logger.info('Capability registered in MySQL', 'service', {
      capability_type: req.capability_type,
      capability_id: req.capability_id,
      trace_id: traceId,
    });

    // Publish to Redis stream events:capability_added
    await redisAdapter.publish(STREAM_CAPABILITY_ADDED, {
      trace_id: traceId,
      capability_type: req.capability_type,
      capability_id: req.capability_id,
      name: req.name,
      gap_id: req.gap_id ?? null,
      validation_score: req.validation_score ?? null,
    });

    logger.info('Capability event published', 'service', {
      stream: STREAM_CAPABILITY_ADDED,
      capability_id: req.capability_id,
      trace_id: traceId,
    });

    const cap = await this.getCapability(req.capability_type, req.capability_id);
    if (!cap) throw new Error('Failed to retrieve capability after registration');
    return cap;
  }

  async getCapability(
    capabilityType: string,
    capabilityId: string
  ): Promise<Capability | null> {
    const rows = await mysqlAdapter.query<CapabilityRow>(
      'SELECT * FROM capability_registry WHERE capability_type = ? AND capability_id = ?',
      [capabilityType, capabilityId]
    );
    if (rows.length === 0) return null;
    return this.mapRow(rows[0]);
  }

  async listCapabilities(): Promise<Capability[]> {
    const rows = await mysqlAdapter.query<CapabilityRow>(
      'SELECT * FROM capability_registry WHERE is_active = TRUE ORDER BY created_at DESC'
    );
    return rows.map(this.mapRow);
  }

  private mapRow(row: CapabilityRow): Capability {
    let specJson: Record<string, unknown> | null = null;
    if (row.spec_json) {
      try {
        specJson = typeof row.spec_json === 'string'
          ? JSON.parse(row.spec_json)
          : row.spec_json;
      } catch {
        specJson = null;
      }
    }
    return {
      id: row.id,
      capability_type: row.capability_type,
      capability_id: row.capability_id,
      name: row.name,
      description: row.description,
      spec_json: specJson,
      source: row.source,
      gap_id: row.gap_id,
      validation_score: row.validation_score,
      is_active: Boolean(row.is_active),
      usage_count: row.usage_count,
      last_used: row.last_used,
      created_at: row.created_at,
    };
  }
}

export const capabilityService = new CapabilityService();
