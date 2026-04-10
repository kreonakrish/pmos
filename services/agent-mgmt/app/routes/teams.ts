import { Router, Request, Response } from 'express';
import { z } from 'zod';
import { teamService } from '../services/teamService';
import { logger } from '../utils/logger';
import { requestTotal, requestDurationSeconds } from '../utils/metrics';

const router = Router();

function traceId(req: Request): string {
  return (req.headers['x-request-id'] as string) || '';
}

function errorResponse(res: Response, status: number, message: string, code: string, tid: string) {
  return res.status(status).json({ error: message, code, trace_id: tid });
}

const retryStrategyEnum = z.enum(['LINEAR', 'EXPONENTIAL', 'FIBONACCI']);

const createTeamSchema = z.object({
  name: z.string().min(1),
  description: z.string().optional(),
  use_smart_workflow: z.boolean().optional(),
  accuracy_threshold: z.number().min(0).max(1).optional(),
  max_retries: z.number().int().min(0).optional(),
  retry_strategy: retryStrategyEnum.optional(),
});

const updateTeamSchema = z.object({
  name: z.string().min(1).optional(),
  description: z.string().optional(),
  use_smart_workflow: z.boolean().optional(),
  accuracy_threshold: z.number().min(0).max(1).optional(),
  max_retries: z.number().int().min(0).optional(),
  retry_strategy: retryStrategyEnum.optional(),
});

const executionModeEnum = z.enum(['sequential', 'parallel', 'conditional']);
const criticalityEnum = z.enum(['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']);

const addAgentSchema = z.object({
  agent_id: z.string().uuid(),
  priority: z.number().int().min(0).optional(),
  role: z.string().optional(),
  parent_agent_id: z.string().uuid().nullable().optional(),
  execution_mode: executionModeEnum.optional(),
  criticality: criticalityEnum.optional(),
  timeout_seconds: z.number().int().min(1).optional(),
  fallback_agent_id: z.string().uuid().nullable().optional(),
});

const teamAgentHierarchySchema = z.object({
  agent_id: z.string().uuid(),
  priority: z.number().int().min(0),
  role: z.string().optional(),
  parent_agent_id: z.string().uuid().nullable().optional(),
  execution_mode: executionModeEnum.optional(),
  criticality: criticalityEnum.optional(),
  timeout_seconds: z.number().int().min(1).optional(),
  fallback_agent_id: z.string().uuid().nullable().optional(),
});

const syncHierarchySchema = z.object({
  agents: z.array(teamAgentHierarchySchema).min(1),
});

// GET /v1/teams
router.get('/', async (req: Request, res: Response) => {
  const start = Date.now();
  const tid = traceId(req);
  try {
    const teams = await teamService.listTeams();
    requestTotal.inc({ method: 'GET', path: '/v1/teams', status: '200' });
    return res.json({ teams, count: teams.length, trace_id: tid });
  } catch (err: unknown) {
    const error = err as Error;
    logger.error('listTeams failed', 'router', { error: error.message, trace_id: tid });
    requestTotal.inc({ method: 'GET', path: '/v1/teams', status: '500' });
    return errorResponse(res, 500, 'Internal server error', 'INTERNAL_ERROR', tid);
  } finally {
    requestDurationSeconds.observe({ method: 'GET', path: '/v1/teams' }, (Date.now() - start) / 1000);
  }
});

// POST /v1/teams
router.post('/', async (req: Request, res: Response) => {
  const start = Date.now();
  const tid = traceId(req);
  try {
    const parsed = createTeamSchema.safeParse(req.body);
    if (!parsed.success) {
      requestTotal.inc({ method: 'POST', path: '/v1/teams', status: '400' });
      return errorResponse(res, 400, parsed.error.message, 'VALIDATION_ERROR', tid);
    }
    const team = await teamService.createTeam(parsed.data);
    requestTotal.inc({ method: 'POST', path: '/v1/teams', status: '201' });
    return res.status(201).json({ team, trace_id: tid });
  } catch (err: unknown) {
    const error = err as Error;
    logger.error('createTeam failed', 'router', { error: error.message, trace_id: tid });
    requestTotal.inc({ method: 'POST', path: '/v1/teams', status: '500' });
    return errorResponse(res, 500, 'Internal server error', 'INTERNAL_ERROR', tid);
  } finally {
    requestDurationSeconds.observe({ method: 'POST', path: '/v1/teams' }, (Date.now() - start) / 1000);
  }
});

// GET /v1/teams/:team_id
router.get('/:team_id', async (req: Request, res: Response) => {
  const start = Date.now();
  const tid = traceId(req);
  const team_id = String(req.params.team_id);
  try {
    const team = await teamService.getTeam(team_id);
    if (!team) {
      requestTotal.inc({ method: 'GET', path: '/v1/teams/:id', status: '404' });
      return errorResponse(res, 404, 'Team not found', 'NOT_FOUND', tid);
    }
    requestTotal.inc({ method: 'GET', path: '/v1/teams/:id', status: '200' });
    return res.json({ team, trace_id: tid });
  } catch (err: unknown) {
    const error = err as Error;
    logger.error('getTeam failed', 'router', { error: error.message, team_id, trace_id: tid });
    requestTotal.inc({ method: 'GET', path: '/v1/teams/:id', status: '500' });
    return errorResponse(res, 500, 'Internal server error', 'INTERNAL_ERROR', tid);
  } finally {
    requestDurationSeconds.observe({ method: 'GET', path: '/v1/teams/:id' }, (Date.now() - start) / 1000);
  }
});

// PUT /v1/teams/:team_id
router.put('/:team_id', async (req: Request, res: Response) => {
  const start = Date.now();
  const tid = traceId(req);
  const team_id = String(req.params.team_id);
  try {
    const parsed = updateTeamSchema.safeParse(req.body);
    if (!parsed.success) {
      requestTotal.inc({ method: 'PUT', path: '/v1/teams/:id', status: '400' });
      return errorResponse(res, 400, parsed.error.message, 'VALIDATION_ERROR', tid);
    }
    const team = await teamService.updateTeam(team_id, parsed.data);
    if (!team) {
      requestTotal.inc({ method: 'PUT', path: '/v1/teams/:id', status: '404' });
      return errorResponse(res, 404, 'Team not found', 'NOT_FOUND', tid);
    }
    requestTotal.inc({ method: 'PUT', path: '/v1/teams/:id', status: '200' });
    return res.json({ team, trace_id: tid });
  } catch (err: unknown) {
    const error = err as Error;
    logger.error('updateTeam failed', 'router', { error: error.message, team_id, trace_id: tid });
    requestTotal.inc({ method: 'PUT', path: '/v1/teams/:id', status: '500' });
    return errorResponse(res, 500, 'Internal server error', 'INTERNAL_ERROR', tid);
  } finally {
    requestDurationSeconds.observe({ method: 'PUT', path: '/v1/teams/:id' }, (Date.now() - start) / 1000);
  }
});

// PATCH /v1/teams/:team_id — alias for PUT
router.patch('/:team_id', async (req: Request, res: Response) => {
  const start = Date.now();
  const tid = traceId(req);
  const team_id = String(req.params.team_id);
  try {
    const parsed = updateTeamSchema.safeParse(req.body);
    if (!parsed.success) {
      requestTotal.inc({ method: 'PATCH', path: '/v1/teams/:id', status: '400' });
      return errorResponse(res, 400, parsed.error.message, 'VALIDATION_ERROR', tid);
    }
    const team = await teamService.updateTeam(team_id, parsed.data);
    if (!team) {
      requestTotal.inc({ method: 'PATCH', path: '/v1/teams/:id', status: '404' });
      return errorResponse(res, 404, 'Team not found', 'NOT_FOUND', tid);
    }
    requestTotal.inc({ method: 'PATCH', path: '/v1/teams/:id', status: '200' });
    return res.json({ team, trace_id: tid });
  } catch (err: unknown) {
    const error = err as Error;
    logger.error('updateTeam (PATCH) failed', 'router', { error: error.message, team_id, trace_id: tid });
    requestTotal.inc({ method: 'PATCH', path: '/v1/teams/:id', status: '500' });
    return errorResponse(res, 500, 'Internal server error', 'INTERNAL_ERROR', tid);
  } finally {
    requestDurationSeconds.observe({ method: 'PATCH', path: '/v1/teams/:id' }, (Date.now() - start) / 1000);
  }
});

// DELETE /v1/teams/:team_id
router.delete('/:team_id', async (req: Request, res: Response) => {
  const start = Date.now();
  const tid = traceId(req);
  const team_id = String(req.params.team_id);
  try {
    const deleted = await teamService.deleteTeam(team_id);
    if (!deleted) {
      requestTotal.inc({ method: 'DELETE', path: '/v1/teams/:id', status: '404' });
      return errorResponse(res, 404, 'Team not found', 'NOT_FOUND', tid);
    }
    requestTotal.inc({ method: 'DELETE', path: '/v1/teams/:id', status: '200' });
    return res.json({ message: 'Team deleted', trace_id: tid });
  } catch (err: unknown) {
    const error = err as Error;
    logger.error('deleteTeam failed', 'router', { error: error.message, team_id, trace_id: tid });
    requestTotal.inc({ method: 'DELETE', path: '/v1/teams/:id', status: '500' });
    return errorResponse(res, 500, 'Internal server error', 'INTERNAL_ERROR', tid);
  } finally {
    requestDurationSeconds.observe({ method: 'DELETE', path: '/v1/teams/:id' }, (Date.now() - start) / 1000);
  }
});

// PUT /v1/teams/:team_id/hierarchy
router.put('/:team_id/hierarchy', async (req: Request, res: Response) => {
  const start = Date.now();
  const tid = traceId(req);
  const team_id = String(req.params.team_id);
  try {
    const parsed = syncHierarchySchema.safeParse(req.body);
    if (!parsed.success) {
      requestTotal.inc({ method: 'PUT', path: '/v1/teams/:id/hierarchy', status: '400' });
      return errorResponse(res, 400, parsed.error.message, 'VALIDATION_ERROR', tid);
    }
    // Verify team exists
    const team = await teamService.getTeam(team_id);
    if (!team) {
      requestTotal.inc({ method: 'PUT', path: '/v1/teams/:id/hierarchy', status: '404' });
      return errorResponse(res, 404, 'Team not found', 'NOT_FOUND', tid);
    }
    await teamService.syncTeamHierarchy(team.team_id, parsed.data.agents);
    const updatedTeam = await teamService.getTeam(team_id);
    requestTotal.inc({ method: 'PUT', path: '/v1/teams/:id/hierarchy', status: '200' });
    return res.json({ team: updatedTeam, trace_id: tid });
  } catch (err: unknown) {
    const error = err as Error;
    logger.error('syncTeamHierarchy failed', 'router', { error: error.message, team_id, trace_id: tid });
    requestTotal.inc({ method: 'PUT', path: '/v1/teams/:id/hierarchy', status: '500' });
    return errorResponse(res, 500, 'Internal server error', 'INTERNAL_ERROR', tid);
  } finally {
    requestDurationSeconds.observe({ method: 'PUT', path: '/v1/teams/:id/hierarchy' }, (Date.now() - start) / 1000);
  }
});

// POST /v1/teams/:team_id/agents
router.post('/:team_id/agents', async (req: Request, res: Response) => {
  const start = Date.now();
  const tid = traceId(req);
  const team_id = String(req.params.team_id);
  try {
    const parsed = addAgentSchema.safeParse(req.body);
    if (!parsed.success) {
      requestTotal.inc({ method: 'POST', path: '/v1/teams/:id/agents', status: '400' });
      return errorResponse(res, 400, parsed.error.message, 'VALIDATION_ERROR', tid);
    }
    await teamService.addAgentToTeam(team_id, parsed.data);
    requestTotal.inc({ method: 'POST', path: '/v1/teams/:id/agents', status: '201' });
    return res.status(201).json({ message: 'Agent added to team', trace_id: tid });
  } catch (err: unknown) {
    const error = err as Error;
    logger.error('addAgentToTeam failed', 'router', { error: error.message, team_id, trace_id: tid });
    requestTotal.inc({ method: 'POST', path: '/v1/teams/:id/agents', status: '500' });
    return errorResponse(res, 500, 'Internal server error', 'INTERNAL_ERROR', tid);
  } finally {
    requestDurationSeconds.observe({ method: 'POST', path: '/v1/teams/:id/agents' }, (Date.now() - start) / 1000);
  }
});

// DELETE /v1/teams/:team_id/agents/:agent_id
router.delete('/:team_id/agents/:agent_id', async (req: Request, res: Response) => {
  const start = Date.now();
  const tid = traceId(req);
  const team_id = String(req.params.team_id);
  const agent_id = String(req.params.agent_id);
  try {
    const removed = await teamService.removeAgentFromTeam(team_id, agent_id);
    if (!removed) {
      requestTotal.inc({ method: 'DELETE', path: '/v1/teams/:id/agents/:id', status: '404' });
      return errorResponse(res, 404, 'Team-agent association not found', 'NOT_FOUND', tid);
    }
    requestTotal.inc({ method: 'DELETE', path: '/v1/teams/:id/agents/:id', status: '200' });
    return res.json({ message: 'Agent removed from team', trace_id: tid });
  } catch (err: unknown) {
    const error = err as Error;
    logger.error('removeAgentFromTeam failed', 'router', { error: error.message, team_id, agent_id, trace_id: tid });
    requestTotal.inc({ method: 'DELETE', path: '/v1/teams/:id/agents/:id', status: '500' });
    return errorResponse(res, 500, 'Internal server error', 'INTERNAL_ERROR', tid);
  } finally {
    requestDurationSeconds.observe({ method: 'DELETE', path: '/v1/teams/:id/agents/:id' }, (Date.now() - start) / 1000);
  }
});

export default router;
