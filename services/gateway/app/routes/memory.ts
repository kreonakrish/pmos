import { Router, Request, Response } from 'express';
import { config } from '../config';
import { proxyRequest } from '../utils/httpProxy';
import { logger } from '../utils/logger';

const router = Router();

/**
 * POST /v1/memory/write
 */
router.post('/memory/write', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  logger.info('proxy_memory_write', { layer: 'router', trace_id: traceId });
  await proxyRequest(req, res, { targetUrl: `${config.MEMORY_SERVICE_URL}/v1/memory/write` });
});

/**
 * POST /v1/memory/assemble-prompt
 */
router.post('/memory/assemble-prompt', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  logger.info('proxy_memory_assemble_prompt', { layer: 'router', trace_id: traceId });
  await proxyRequest(req, res, { targetUrl: `${config.MEMORY_SERVICE_URL}/v1/memory/assemble-prompt` });
});

/**
 * GET /v1/memory/retrieve
 */
router.get('/memory/retrieve', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  logger.info('proxy_memory_retrieve', { layer: 'router', trace_id: traceId });
  await proxyRequest(req, res, { targetUrl: `${config.MEMORY_SERVICE_URL}/v1/memory/retrieve` });
});

/**
 * GET /v1/memory/entries
 */
router.get('/memory/entries', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  logger.info('proxy_memory_entries', { layer: 'router', trace_id: traceId });
  await proxyRequest(req, res, {
    targetUrl: `${config.MEMORY_SERVICE_URL}/v1/memory/entries`,
  });
});

export default router;
