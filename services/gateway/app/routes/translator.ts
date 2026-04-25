import { Router, Request, Response } from 'express';
import { config } from '../config';
import { proxyRequest } from '../utils/httpProxy';
import { logger } from '../utils/logger';

const router = Router();

/**
 * POST /v1/translate
 * Proxies to translator /v1/translate
 */
router.post('/translate', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  logger.info('proxy_translate', { layer: 'router', trace_id: traceId });
  await proxyRequest(req, res, {
    targetUrl: `${config.TRANSLATOR_URL}/v1/translate`,
    timeout: 60_000,
  });
});

/**
 * POST /v1/translator/examples
 * Proxies to translator /v1/translator/examples (promote translation example).
 */
router.post('/translator/examples', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  logger.info('proxy_translator_examples_create', { layer: 'router', trace_id: traceId });
  await proxyRequest(req, res, {
    targetUrl: `${config.TRANSLATOR_URL}/v1/translator/examples`,
    timeout: 30_000,
  });
});

/**
 * Generic GET proxy for any future /v1/translator/* read endpoints.
 * Express 5 / path-to-regexp 8 requires named splat params (`*rest`).
 */
router.get('/translator/*rest', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const subPath = req.path; // e.g. /translator/examples
  const qs = req.url.includes('?') ? req.url.substring(req.url.indexOf('?')) : '';
  logger.info('proxy_translator_get', { layer: 'router', trace_id: traceId, sub_path: subPath });
  await proxyRequest(req, res, {
    targetUrl: `${config.TRANSLATOR_URL}/v1${subPath}${qs}`,
  });
});

export default router;
