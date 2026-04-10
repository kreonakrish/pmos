import { v4 as uuidv4 } from 'uuid';
import type { RowDataPacket } from 'mysql2';
import { mysqlAdapter } from '../adapters/mysqlAdapter';
import {
  Team,
  TeamAgent,
  CreateTeamRequest,
  UpdateTeamRequest,
  AddAgentToTeamRequest,
  TeamAgentHierarchy,
} from '../models/team';
import { logger } from '../utils/logger';

interface TeamRow extends RowDataPacket, Team {}
interface TeamAgentRow extends RowDataPacket, TeamAgent {}

export class TeamService {
  async listTeams(): Promise<Team[]> {
    const rows = await mysqlAdapter.query<TeamRow>(
      'SELECT * FROM teams ORDER BY created_at DESC'
    );
    return rows;
  }

  async getTeam(teamId: string): Promise<Team | null> {
    const isNumeric = /^\d+$/.test(teamId);
    const whereClause = isNumeric ? 'id = ?' : 'team_id = ?';
    const rows = await mysqlAdapter.query<TeamRow>(
      `SELECT * FROM teams WHERE ${whereClause}`,
      [teamId]
    );
    if (rows.length === 0) return null;

    const team = rows[0];
    const agents = await this.getTeamAgents(team.team_id);
    return { ...team, agents };
  }

  async createTeam(req: CreateTeamRequest): Promise<Team> {
    const teamId = uuidv4();
    const sql = `
      INSERT INTO teams
        (team_id, name, description, use_smart_workflow,
         accuracy_threshold, max_retries, retry_strategy)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `;
    await mysqlAdapter.execute(sql, [
      teamId,
      req.name,
      req.description ?? null,
      req.use_smart_workflow !== undefined ? (req.use_smart_workflow ? 1 : 0) : 1,
      req.accuracy_threshold ?? 0.7,
      req.max_retries ?? 3,
      req.retry_strategy ?? 'EXPONENTIAL',
    ]);

    const team = await this.getTeam(teamId);
    if (!team) throw new Error('Failed to retrieve team after creation');

    logger.info('Team created', 'service', { team_id: teamId, name: req.name });
    return team;
  }

  async updateTeam(teamId: string, req: UpdateTeamRequest): Promise<Team | null> {
    const fields: string[] = [];
    const params: unknown[] = [];

    const fieldMap: Record<string, unknown> = {
      name: req.name,
      description: req.description,
      use_smart_workflow: req.use_smart_workflow !== undefined
        ? (req.use_smart_workflow ? 1 : 0)
        : undefined,
      accuracy_threshold: req.accuracy_threshold,
      max_retries: req.max_retries,
      retry_strategy: req.retry_strategy,
    };

    for (const [key, value] of Object.entries(fieldMap)) {
      if (value !== undefined) {
        fields.push(`${key} = ?`);
        params.push(value);
      }
    }

    if (fields.length === 0) return this.getTeam(teamId);

    const isNumeric = /^\d+$/.test(teamId);
    const whereClause = isNumeric ? 'id = ?' : 'team_id = ?';
    params.push(teamId);
    await mysqlAdapter.execute(
      `UPDATE teams SET ${fields.join(', ')} WHERE ${whereClause}`,
      params
    );

    logger.info('Team updated', 'service', { team_id: teamId });
    return this.getTeam(teamId);
  }

  async addAgentToTeam(teamId: string, req: AddAgentToTeamRequest): Promise<void> {
    await mysqlAdapter.execute(
      `INSERT INTO team_agents (team_id, agent_id, priority, role, parent_agent_id, execution_mode, criticality, timeout_seconds, fallback_agent_id)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
       ON DUPLICATE KEY UPDATE priority = VALUES(priority), role = VALUES(role),
         parent_agent_id = VALUES(parent_agent_id), execution_mode = VALUES(execution_mode),
         criticality = VALUES(criticality), timeout_seconds = VALUES(timeout_seconds),
         fallback_agent_id = VALUES(fallback_agent_id)`,
      [
        teamId,
        req.agent_id,
        req.priority ?? 0,
        req.role ?? null,
        req.parent_agent_id ?? null,
        req.execution_mode ?? 'sequential',
        req.criticality ?? 'MEDIUM',
        req.timeout_seconds ?? 30,
        req.fallback_agent_id ?? null,
      ]
    );
    logger.info('Agent added to team', 'service', {
      team_id: teamId,
      agent_id: req.agent_id,
    });
  }

  async syncTeamHierarchy(teamId: string, agents: TeamAgentHierarchy[]): Promise<void> {
    // Delete all existing team_agents for this team, then insert the new set
    await mysqlAdapter.execute(
      'DELETE FROM team_agents WHERE team_id = ?',
      [teamId]
    );

    for (const agent of agents) {
      await mysqlAdapter.execute(
        `INSERT INTO team_agents (team_id, agent_id, priority, role, parent_agent_id, execution_mode, criticality, timeout_seconds, fallback_agent_id)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
        [
          teamId,
          agent.agent_id,
          agent.priority,
          agent.role ?? null,
          agent.parent_agent_id ?? null,
          agent.execution_mode ?? 'sequential',
          agent.criticality ?? 'MEDIUM',
          agent.timeout_seconds ?? 30,
          agent.fallback_agent_id ?? null,
        ]
      );
    }

    logger.info('Team hierarchy synced', 'service', {
      team_id: teamId,
      agent_count: agents.length,
    });
  }

  async deleteTeam(teamId: string): Promise<boolean> {
    const isNumeric = /^\d+$/.test(teamId);
    const whereClause = isNumeric ? 'id = ?' : 'team_id = ?';

    // Delete associated team_agents first
    if (isNumeric) {
      // Look up the UUID team_id for the join table
      const rows = await mysqlAdapter.query<TeamRow>(
        `SELECT team_id FROM teams WHERE id = ?`,
        [teamId]
      );
      if (rows.length > 0) {
        await mysqlAdapter.execute(
          'DELETE FROM team_agents WHERE team_id = ?',
          [rows[0].team_id]
        );
      }
    } else {
      await mysqlAdapter.execute(
        'DELETE FROM team_agents WHERE team_id = ?',
        [teamId]
      );
    }

    const [result] = await mysqlAdapter.execute(
      `DELETE FROM teams WHERE ${whereClause}`,
      [teamId]
    );
    const affected = result.affectedRows;
    if (affected > 0) {
      logger.info('Team deleted', 'service', { team_id: teamId });
    }
    return affected > 0;
  }

  async removeAgentFromTeam(teamId: string, agentId: string): Promise<boolean> {
    const [result] = await mysqlAdapter.execute(
      'DELETE FROM team_agents WHERE team_id = ? AND agent_id = ?',
      [teamId, agentId]
    );
    const affected = result.affectedRows;
    if (affected > 0) {
      logger.info('Agent removed from team', 'service', {
        team_id: teamId,
        agent_id: agentId,
      });
    }
    return affected > 0;
  }

  private async getTeamAgents(teamId: string): Promise<TeamAgent[]> {
    const rows = await mysqlAdapter.query<TeamAgentRow>(
      `SELECT ta.team_id, ta.agent_id, ta.priority, ta.role, ta.accuracy, ta.success_rate,
              ta.assigned_at, ta.parent_agent_id, ta.execution_mode, ta.criticality,
              ta.timeout_seconds, ta.fallback_agent_id,
              a.name as agent_name, a.status as agent_status, a.foundation_model
       FROM team_agents ta
       JOIN agents a ON a.agent_id = ta.agent_id
       WHERE ta.team_id = ?
       ORDER BY ta.priority ASC`,
      [teamId]
    );
    return rows;
  }
}

export const teamService = new TeamService();
