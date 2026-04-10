import { Router, Request, Response } from 'express';
import { config } from '../config';
import { proxyRequest } from '../utils/httpProxy';
import { logger } from '../utils/logger';

const router = Router();

/**
 * POST /v1/chat
 * Proxies to orchestrator /v1/orchestrator/chat
 */
router.post('/chat', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  logger.info('proxy_chat', { layer: 'router', trace_id: traceId });

  await proxyRequest(req, res, {
    targetUrl: `${config.ORCHESTRATOR_URL}/v1/orchestrator/chat`,
    timeout: 300_000,
  });
});

/**
 * GET /v1/jobs — list pipeline executions
 */
router.get('/jobs', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  logger.info('proxy_jobs_list', { layer: 'router', trace_id: traceId });
  await proxyRequest(req, res, { targetUrl: `${config.ORCHESTRATOR_URL}/v1/orchestrator/jobs` });
});

/**
 * GET /v1/jobs/:graphId — job detail
 */
router.get('/jobs/:graphId', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { graphId } = req.params;
  logger.info('proxy_job_detail', { layer: 'router', trace_id: traceId, graph_id: graphId });
  await proxyRequest(req, res, { targetUrl: `${config.ORCHESTRATOR_URL}/v1/orchestrator/jobs/${graphId}` });
});

/**
 * POST /v1/jobs/:graphId/resume — resume interrupted pipeline
 */
router.post('/jobs/:graphId/resume', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { graphId } = req.params;
  logger.info('proxy_job_resume', { layer: 'router', trace_id: traceId, graph_id: graphId });
  await proxyRequest(req, res, {
    targetUrl: `${config.ORCHESTRATOR_URL}/v1/orchestrator/jobs/${graphId}/resume`,
    timeout: 300000,
  });
});

/**
 * GET /v1/tasks
 * Proxies to orchestrator /v1/orchestrator/tasks
 */
router.get('/tasks', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  logger.info('proxy_tasks_list', { layer: 'router', trace_id: traceId });

  await proxyRequest(req, res, {
    targetUrl: `${config.ORCHESTRATOR_URL}/v1/orchestrator/tasks`,
  });
});

/**
 * GET /v1/tasks/:taskId
 * Proxies to orchestrator /v1/orchestrator/tasks/:taskId
 */
router.get('/tasks/:taskId', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { taskId } = req.params;
  logger.info('proxy_task_get', { layer: 'router', trace_id: traceId, task_id: taskId });

  await proxyRequest(req, res, {
    targetUrl: `${config.ORCHESTRATOR_URL}/v1/orchestrator/tasks/${taskId}`,
  });
});

// ─── Conversation routes ────────────────────────────────────────────────────

/**
 * GET /v1/conversations
 */
router.get('/conversations', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  logger.info('proxy_conversations_list', { layer: 'router', trace_id: traceId });
  await proxyRequest(req, res, {
    targetUrl: `${config.ORCHESTRATOR_URL}/v1/orchestrator/conversations`,
  });
});

/**
 * POST /v1/conversations
 */
router.post('/conversations', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  logger.info('proxy_conversations_create', { layer: 'router', trace_id: traceId });
  await proxyRequest(req, res, {
    targetUrl: `${config.ORCHESTRATOR_URL}/v1/orchestrator/conversations`,
  });
});

/**
 * GET /v1/conversations/:id
 */
router.get('/conversations/:id', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { id } = req.params;
  logger.info('proxy_conversation_get', { layer: 'router', trace_id: traceId, conversation_id: id });
  await proxyRequest(req, res, {
    targetUrl: `${config.ORCHESTRATOR_URL}/v1/orchestrator/conversations/${id}`,
  });
});

/**
 * PATCH /v1/conversations/:id
 */
router.patch('/conversations/:id', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { id } = req.params;
  logger.info('proxy_conversation_update', { layer: 'router', trace_id: traceId, conversation_id: id });
  await proxyRequest(req, res, {
    targetUrl: `${config.ORCHESTRATOR_URL}/v1/orchestrator/conversations/${id}`,
  });
});

/**
 * DELETE /v1/conversations/:id
 */
router.delete('/conversations/:id', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { id } = req.params;
  logger.info('proxy_conversation_delete', { layer: 'router', trace_id: traceId, conversation_id: id });
  await proxyRequest(req, res, {
    targetUrl: `${config.ORCHESTRATOR_URL}/v1/orchestrator/conversations/${id}`,
  });
});

/**
 * GET /v1/conversations/:id/messages
 */
router.get('/conversations/:id/messages', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { id } = req.params;
  logger.info('proxy_conversation_messages_list', { layer: 'router', trace_id: traceId, conversation_id: id });
  await proxyRequest(req, res, {
    targetUrl: `${config.ORCHESTRATOR_URL}/v1/orchestrator/conversations/${id}/messages`,
  });
});

/**
 * POST /v1/conversations/:id/messages
 */
router.post('/conversations/:id/messages', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { id } = req.params;
  logger.info('proxy_conversation_messages_create', { layer: 'router', trace_id: traceId, conversation_id: id });
  await proxyRequest(req, res, {
    targetUrl: `${config.ORCHESTRATOR_URL}/v1/orchestrator/conversations/${id}/messages`,
    timeout: 300000,
  });
});

/**
 * GET /v1/conversations/:id/decomposition
 */
router.get('/conversations/:id/decomposition', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { id } = req.params;
  logger.info('proxy_conversation_decomposition', { layer: 'router', trace_id: traceId, conversation_id: id });
  await proxyRequest(req, res, {
    targetUrl: `${config.ORCHESTRATOR_URL}/v1/orchestrator/conversations/${id}/decomposition`,
  });
});

/**
 * GET /v1/conversations/:id/tasks/:taskId
 */
router.get('/conversations/:id/tasks/:taskId', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { id, taskId } = req.params;
  logger.info('proxy_conversation_task_get', { layer: 'router', trace_id: traceId, conversation_id: id, task_id: taskId });
  await proxyRequest(req, res, {
    targetUrl: `${config.ORCHESTRATOR_URL}/v1/orchestrator/conversations/${id}/tasks/${taskId}`,
  });
});

/**
 * GET /v1/conversations/:id/interactions
 */
router.get('/conversations/:id/interactions', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { id } = req.params;
  logger.info('proxy_conversation_interactions', { layer: 'router', trace_id: traceId, conversation_id: id });
  await proxyRequest(req, res, {
    targetUrl: `${config.ORCHESTRATOR_URL}/v1/orchestrator/conversations/${id}/interactions`,
  });
});

/**
 * POST /v1/conversations/:id/feedback
 * Proxies to orchestrator /v1/orchestrator/conversations/:id/feedback
 */
router.post('/conversations/:id/feedback', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { id } = req.params;
  logger.info('proxy_conversation_feedback', { layer: 'router', trace_id: traceId, conversation_id: id });
  await proxyRequest(req, res, {
    targetUrl: `${config.ORCHESTRATOR_URL}/v1/orchestrator/conversations/${id}/feedback`,
  });
});

// ─── Jobs / Graphs endpoints ────────────────────────────────────────────────

/**
 * GET /v1/jobs
 * Proxies to orchestrator /v1/orchestrator/jobs
 */
router.get('/jobs', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  logger.info('proxy_jobs_list', { layer: 'router', trace_id: traceId });

  await proxyRequest(req, res, {
    targetUrl: `${config.ORCHESTRATOR_URL}/v1/orchestrator/jobs`,
  });
});

/**
 * GET /v1/jobs/:graphId
 * Proxies to orchestrator /v1/orchestrator/jobs/:graphId
 */
router.get('/jobs/:graphId', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { graphId } = req.params;
  logger.info('proxy_job_get', { layer: 'router', trace_id: traceId, graph_id: graphId });

  await proxyRequest(req, res, {
    targetUrl: `${config.ORCHESTRATOR_URL}/v1/orchestrator/jobs/${graphId}`,
  });
});

/**
 * POST /v1/jobs/:graphId/resume
 * Proxies to orchestrator /v1/orchestrator/jobs/:graphId/resume
 */
router.post('/jobs/:graphId/resume', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { graphId } = req.params;
  logger.info('proxy_job_resume', { layer: 'router', trace_id: traceId, graph_id: graphId });

  await proxyRequest(req, res, {
    targetUrl: `${config.ORCHESTRATOR_URL}/v1/orchestrator/jobs/${graphId}/resume`,
    timeout: 300_000,
  });
});

// ─── Graph routes ───────────────────────────────────────────────────────────

/**
 * GET /v1/graph/tasks
 */
router.get('/graph/tasks', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  logger.info('proxy_graph_tasks', { layer: 'router', trace_id: traceId });
  await proxyRequest(req, res, {
    targetUrl: `${config.ORCHESTRATOR_URL}/v1/orchestrator/graph/tasks`,
  });
});

export default router;
