import { Router, Request, Response } from 'express';
import { config } from '../config';
import { proxyRequest } from '../utils/httpProxy';
import { logger } from '../utils/logger';

const router = Router();

/**
 * GET /v1/agents
 * List all agents.
 */
router.get('/agents', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  logger.info('proxy_agents_list', { layer: 'router', trace_id: traceId });
  await proxyRequest(req, res, { targetUrl: `${config.AGENT_MGMT_URL}/v1/agents` });
});

/**
 * POST /v1/agents
 * Create a new agent.
 */
router.post('/agents', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  logger.info('proxy_agents_create', { layer: 'router', trace_id: traceId });
  await proxyRequest(req, res, { targetUrl: `${config.AGENT_MGMT_URL}/v1/agents` });
});

/**
 * GET /v1/agents/:agentId/tools
 */
router.get('/agents/:agentId/tools', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { agentId } = req.params;
  logger.info('proxy_agent_tools_list', { layer: 'router', trace_id: traceId, agent_id: agentId });
  await proxyRequest(req, res, { targetUrl: `${config.AGENT_MGMT_URL}/v1/agents/${agentId}/tools` });
});

/**
 * POST /v1/agents/:agentId/tools
 */
router.post('/agents/:agentId/tools', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { agentId } = req.params;
  logger.info('proxy_agent_tool_assign', { layer: 'router', trace_id: traceId, agent_id: agentId });
  await proxyRequest(req, res, { targetUrl: `${config.AGENT_MGMT_URL}/v1/agents/${agentId}/tools` });
});

/**
 * PUT /v1/agents/:agentId/tools — bulk sync tool assignments
 */
router.put('/agents/:agentId/tools', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { agentId } = req.params;
  logger.info('proxy_agent_tools_sync', { layer: 'router', trace_id: traceId, agent_id: agentId });
  await proxyRequest(req, res, { targetUrl: `${config.AGENT_MGMT_URL}/v1/agents/${agentId}/tools` });
});

/**
 * DELETE /v1/agents/:agentId/tools/:toolId — remove a single tool assignment
 */
router.delete('/agents/:agentId/tools/:toolId', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { agentId, toolId } = req.params;
  logger.info('proxy_agent_tool_remove', { layer: 'router', trace_id: traceId, agent_id: agentId, tool_id: toolId });
  await proxyRequest(req, res, { targetUrl: `${config.AGENT_MGMT_URL}/v1/agents/${agentId}/tools/${toolId}` });
});

/**
 * POST /v1/agents/:agentId/test — test agent with a prompt via LLM (60s timeout)
 */
router.post('/agents/:agentId/test', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { agentId } = req.params;
  logger.info('proxy_agent_test', { layer: 'router', trace_id: traceId, agent_id: agentId });
  await proxyRequest(req, res, {
    targetUrl: `${config.AGENT_MGMT_URL}/v1/agents/${agentId}/test`,
    timeout: 60000,
  });
});

/**
 * GET /v1/agents/:agentId/executions — get agent execution history
 */
router.get('/agents/:agentId/executions', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { agentId } = req.params;
  logger.info('proxy_agent_executions', { layer: 'router', trace_id: traceId, agent_id: agentId });
  await proxyRequest(req, res, { targetUrl: `${config.AGENT_MGMT_URL}/v1/agents/${agentId}/executions` });
});

/**
 * GET /v1/agents/:agentId
 */
router.get('/agents/:agentId', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { agentId } = req.params;
  logger.info('proxy_agent_get', { layer: 'router', trace_id: traceId, agent_id: agentId });
  await proxyRequest(req, res, { targetUrl: `${config.AGENT_MGMT_URL}/v1/agents/${agentId}` });
});

/**
 * PUT /v1/agents/:agentId
 */
router.put('/agents/:agentId', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { agentId } = req.params;
  logger.info('proxy_agent_update', { layer: 'router', trace_id: traceId, agent_id: agentId });
  await proxyRequest(req, res, { targetUrl: `${config.AGENT_MGMT_URL}/v1/agents/${agentId}` });
});

/**
 * DELETE /v1/agents/:agentId
 */
router.delete('/agents/:agentId', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { agentId } = req.params;
  logger.info('proxy_agent_delete', { layer: 'router', trace_id: traceId, agent_id: agentId });
  await proxyRequest(req, res, { targetUrl: `${config.AGENT_MGMT_URL}/v1/agents/${agentId}` });
});

/**
 * GET /v1/tools
 */
router.get('/tools', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  logger.info('proxy_tools_list', { layer: 'router', trace_id: traceId });
  await proxyRequest(req, res, { targetUrl: `${config.AGENT_MGMT_URL}/v1/tools` });
});

/**
 * POST /v1/tools
 */
router.post('/tools', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  logger.info('proxy_tools_create', { layer: 'router', trace_id: traceId });
  await proxyRequest(req, res, { targetUrl: `${config.AGENT_MGMT_URL}/v1/tools` });
});

/**
 * GET /v1/teams
 */
router.get('/teams', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  logger.info('proxy_teams_list', { layer: 'router', trace_id: traceId });
  await proxyRequest(req, res, { targetUrl: `${config.AGENT_MGMT_URL}/v1/teams` });
});

/**
 * POST /v1/teams
 */
router.post('/teams', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  logger.info('proxy_teams_create', { layer: 'router', trace_id: traceId });
  await proxyRequest(req, res, { targetUrl: `${config.AGENT_MGMT_URL}/v1/teams` });
});

/**
 * GET /v1/teams/:teamId
 */
router.get('/teams/:teamId', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { teamId } = req.params;
  logger.info('proxy_team_get', { layer: 'router', trace_id: traceId, team_id: teamId });
  await proxyRequest(req, res, { targetUrl: `${config.AGENT_MGMT_URL}/v1/teams/${teamId}` });
});

/**
 * PATCH /v1/teams/:teamId
 */
router.patch('/teams/:teamId', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { teamId } = req.params;
  logger.info('proxy_team_update', { layer: 'router', trace_id: traceId, team_id: teamId });
  await proxyRequest(req, res, { targetUrl: `${config.AGENT_MGMT_URL}/v1/teams/${teamId}` });
});

/**
 * DELETE /v1/teams/:teamId
 */
router.delete('/teams/:teamId', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { teamId } = req.params;
  logger.info('proxy_team_delete', { layer: 'router', trace_id: traceId, team_id: teamId });
  await proxyRequest(req, res, { targetUrl: `${config.AGENT_MGMT_URL}/v1/teams/${teamId}` });
});

/**
 * PUT /v1/teams/:teamId/hierarchy — sync team agent hierarchy
 */
router.put('/teams/:teamId/hierarchy', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { teamId } = req.params;
  logger.info('proxy_team_hierarchy_sync', { layer: 'router', trace_id: traceId, team_id: teamId });
  await proxyRequest(req, res, { targetUrl: `${config.AGENT_MGMT_URL}/v1/teams/${teamId}/hierarchy` });
});

/**
 * POST /v1/teams/:teamId/agents
 */
router.post('/teams/:teamId/agents', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { teamId } = req.params;
  logger.info('proxy_team_agent_add', { layer: 'router', trace_id: traceId, team_id: teamId });
  await proxyRequest(req, res, { targetUrl: `${config.AGENT_MGMT_URL}/v1/teams/${teamId}/agents` });
});

/**
 * DELETE /v1/teams/:teamId/agents/:agentId
 */
router.delete('/teams/:teamId/agents/:agentId', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { teamId, agentId } = req.params;
  logger.info('proxy_team_agent_remove', { layer: 'router', trace_id: traceId, team_id: teamId, agent_id: agentId });
  await proxyRequest(req, res, { targetUrl: `${config.AGENT_MGMT_URL}/v1/teams/${teamId}/agents/${agentId}` });
});

/**
 * POST /v1/tools/test — proxy tool test execution to agent-mgmt (extended timeout)
 */
router.post('/tools/test', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  logger.info('proxy_tools_test', { layer: 'router', trace_id: traceId });
  await proxyRequest(req, res, {
    targetUrl: `${config.AGENT_MGMT_URL}/v1/tools/test`,
    timeout: 60000,
  });
});

/**
 * GET /v1/tools/:toolId/executions — tool execution history
 */
router.get('/tools/:toolId/executions', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { toolId } = req.params;
  logger.info('proxy_tool_executions', { layer: 'router', trace_id: traceId, tool_id: toolId });
  await proxyRequest(req, res, { targetUrl: `${config.AGENT_MGMT_URL}/v1/tools/${toolId}/executions` });
});

/**
 * GET /v1/tools/:toolId
 */
router.get('/tools/:toolId', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { toolId } = req.params;
  logger.info('proxy_tool_get', { layer: 'router', trace_id: traceId, tool_id: toolId });
  await proxyRequest(req, res, { targetUrl: `${config.AGENT_MGMT_URL}/v1/tools/${toolId}` });
});

/**
 * PUT /v1/tools/:toolId
 */
router.put('/tools/:toolId', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { toolId } = req.params;
  logger.info('proxy_tool_update', { layer: 'router', trace_id: traceId, tool_id: toolId });
  await proxyRequest(req, res, { targetUrl: `${config.AGENT_MGMT_URL}/v1/tools/${toolId}` });
});

/**
 * DELETE /v1/tools/:toolId
 */
router.delete('/tools/:toolId', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { toolId } = req.params;
  logger.info('proxy_tool_delete', { layer: 'router', trace_id: traceId, tool_id: toolId });
  await proxyRequest(req, res, { targetUrl: `${config.AGENT_MGMT_URL}/v1/tools/${toolId}` });
});

/**
 * GET /v1/capabilities
 */
router.get('/capabilities', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  logger.info('proxy_capabilities_list', { layer: 'router', trace_id: traceId });
  await proxyRequest(req, res, { targetUrl: `${config.AGENT_MGMT_URL}/v1/capabilities` });
});

export default router;
