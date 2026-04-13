import { Router, Request, Response } from 'express';
import { getLogSource, LogLine } from '../services/logs';
import { logger } from '../utils/logger';

const router = Router();

router.get('/logs/services', async (_req: Request, res: Response): Promise<void> => {
  const services = await getLogSource().listServices();
  res.json({ services });
});

/**
 * GET /v1/logs/tail?service=rag&tail=200&follow=1&level=ERROR&trace_id=abc
 * SSE stream of normalized log lines. Falls back to a one-shot JSON array
 * when follow=0.
 */
router.get('/logs/tail', async (req: Request, res: Response): Promise<void> => {
  const service = String(req.query.service ?? '');
  if (!service) {
    res.status(400).json({ error: 'service query param required' });
    return;
  }

  const follow = req.query.follow === '1' || req.query.follow === 'true';
  const tail = Number(req.query.tail ?? 200);
  const level = req.query.level ? String(req.query.level).toUpperCase() : undefined;
  const traceId = req.query.trace_id ? String(req.query.trace_id) : undefined;
  const traceIdLog = (req as Request & { id?: string }).id;

  const controller = new AbortController();
  req.on('close', () => controller.abort());

  try {
    const iter = getLogSource().tail({
      service,
      tail,
      follow,
      level: level as LogLine['level'] | undefined,
      traceId,
      signal: controller.signal,
    });

    if (follow) {
      res.setHeader('Content-Type', 'text/event-stream');
      res.setHeader('Cache-Control', 'no-cache');
      res.setHeader('Connection', 'keep-alive');
      res.flushHeaders();
      for await (const line of iter) {
        res.write(`data: ${JSON.stringify(line)}\n\n`);
      }
      res.end();
    } else {
      const lines: LogLine[] = [];
      for await (const line of iter) lines.push(line);
      res.json({ service, count: lines.length, lines });
    }
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    logger.error('logs_tail_failed', { layer: 'router', trace_id: traceIdLog, target_service: service, error: msg });
    if (!res.headersSent) res.status(500).json({ error: msg });
    else res.end();
  }
});

export default router;
