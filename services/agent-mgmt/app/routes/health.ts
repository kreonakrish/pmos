import { Router, Request, Response } from 'express';
import { mysqlAdapter } from '../adapters/mysqlAdapter';
import { redisAdapter } from '../adapters/redisAdapter';
import { registry } from '../utils/metrics';
import { logger } from '../utils/logger';

// ── /health router ──────────────────────────────────────────────────────────

const router = Router();

// GET /health
router.get('/', async (req: Request, res: Response) => {
  const traceId = (req.headers['x-request-id'] as string) || '';

  const [mysqlOk, redisOk] = await Promise.all([
    mysqlAdapter.healthCheck(),
    redisAdapter.healthCheck(),
  ]);

  const status = mysqlOk && redisOk ? 'healthy' : 'degraded';
  const httpStatus = status === 'healthy' ? 200 : 503;

  const body = {
    status,
    service: 'agent-mgmt',
    timestamp: new Date().toISOString(),
    trace_id: traceId,
    checks: {
      mysql: mysqlOk ? 'ok' : 'fail',
      redis: redisOk ? 'ok' : 'fail',
    },
  };

  if (status !== 'healthy') {
    logger.warn('Health check degraded', 'router', {
      mysql: mysqlOk,
      redis: redisOk,
      trace_id: traceId,
    });
  }

  return res.status(httpStatus).json(body);
});

export default router;

// ── /metrics router ─────────────────────────────────────────────────────────

export const metricsRouter = Router();

// GET /metrics
metricsRouter.get('/', async (_req: Request, res: Response) => {
  try {
    const metrics = await registry.metrics();
    res.set('Content-Type', registry.contentType);
    return res.send(metrics);
  } catch (err: unknown) {
    const error = err as Error;
    logger.error('Metrics endpoint failed', 'router', { error: error.message });
    return res.status(500).send('Metrics unavailable');
  }
});
