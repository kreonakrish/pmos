import { Router, Request, Response } from 'express';
import axios from 'axios';
import { config } from '../config';
import { logger } from '../utils/logger';

const router = Router();

interface ServiceHealth {
  status: 'ok' | 'degraded' | 'down';
  latency_ms: number;
  error?: string;
}

interface HealthResponse {
  status: 'ok' | 'degraded' | 'down';
  services: Record<string, ServiceHealth>;
  timestamp: string;
}

const DOWNSTREAM_SERVICES: Record<string, string> = {
  orchestrator: config.ORCHESTRATOR_URL,
  'agent-mgmt': config.AGENT_MGMT_URL,
  rag: config.RAG_SERVICE_URL,
  scoring: config.SCORING_SERVICE_URL,
  memory: config.MEMORY_SERVICE_URL,
  'meta-assembly': config.META_ASSEMBLY_URL,
};

async function checkServiceHealth(name: string, baseUrl: string): Promise<ServiceHealth> {
  const start = Date.now();
  try {
    const resp = await axios.get(`${baseUrl}/health`, {
      timeout: config.DOWNSTREAM_TIMEOUT_MS,
      validateStatus: (s) => s < 500,
    });
    const latency_ms = Date.now() - start;
    if (resp.status === 200) {
      return { status: 'ok', latency_ms };
    }
    return { status: 'degraded', latency_ms, error: `HTTP ${resp.status}` };
  } catch (err: unknown) {
    const latency_ms = Date.now() - start;
    const message = err instanceof Error ? err.message : String(err);
    logger.warn('health_check_failed', {
      layer: 'router',
      service_name: name,
      error: message,
      latency_ms,
    });
    return { status: 'down', latency_ms, error: message };
  }
}

/**
 * GET /health
 * Aggregates health of all downstream services. Returns:
 *   - "ok"       — all services healthy
 *   - "degraded" — at least one service degraded or slow
 *   - "down"     — at least one service unreachable
 */
router.get('/', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const startAll = Date.now();

  const checks = await Promise.all(
    Object.entries(DOWNSTREAM_SERVICES).map(async ([name, url]) => {
      const result = await checkServiceHealth(name, url);
      return [name, result] as [string, ServiceHealth];
    }),
  );

  const services: Record<string, ServiceHealth> = Object.fromEntries(checks);

  const hasDown = checks.some(([, s]) => s.status === 'down');
  const hasDegraded = checks.some(([, s]) => s.status === 'degraded');
  const overallStatus: 'ok' | 'degraded' | 'down' = hasDown
    ? 'down'
    : hasDegraded
      ? 'degraded'
      : 'ok';

  const body: HealthResponse = {
    status: overallStatus,
    services,
    timestamp: new Date().toISOString(),
  };

  logger.info('health_check', {
    layer: 'router',
    trace_id: traceId,
    overall_status: overallStatus,
    duration_ms: Date.now() - startAll,
  });

  // Always return 200 so load-balancers can read the body; status is in body
  res.status(200).json(body);
});

export default router;
