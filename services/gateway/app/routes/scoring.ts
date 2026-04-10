import { Router, Request, Response } from 'express';
import { config } from '../config';
import { proxyRequest } from '../utils/httpProxy';
import { logger } from '../utils/logger';

const router = Router();

/**
 * POST /v1/scoring/evaluate
 */
router.post('/scoring/evaluate', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  logger.info('proxy_scoring_evaluate', { layer: 'router', trace_id: traceId });
  await proxyRequest(req, res, { targetUrl: `${config.SCORING_SERVICE_URL}/v1/scoring/evaluate` });
});

/**
 * POST /v1/scoring/band
 */
router.post('/scoring/band', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  logger.info('proxy_scoring_band', { layer: 'router', trace_id: traceId });
  await proxyRequest(req, res, { targetUrl: `${config.SCORING_SERVICE_URL}/v1/scoring/band` });
});

/**
 * POST /v1/scoring/feedback
 */
router.post('/scoring/feedback', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  logger.info('proxy_scoring_feedback', { layer: 'router', trace_id: traceId });
  await proxyRequest(req, res, { targetUrl: `${config.SCORING_SERVICE_URL}/v1/scoring/feedback` });
});

/**
 * GET /v1/scoring/weights/:agentId
 */
router.get('/scoring/weights/:agentId', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { agentId } = req.params;
  logger.info('proxy_scoring_weights', { layer: 'router', trace_id: traceId, agent_id: agentId });
  await proxyRequest(req, res, { targetUrl: `${config.SCORING_SERVICE_URL}/v1/scoring/weights/${agentId}` });
});

/**
 * GET /v1/scoring/history/:agentId
 */
router.get('/scoring/history/:agentId', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { agentId } = req.params;
  logger.info('proxy_scoring_history', { layer: 'router', trace_id: traceId, agent_id: agentId });
  await proxyRequest(req, res, { targetUrl: `${config.SCORING_SERVICE_URL}/v1/scoring/history/${agentId}` });
});

export default router;
