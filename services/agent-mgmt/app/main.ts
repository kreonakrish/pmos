import 'dotenv/config';
import express, { Request, Response, NextFunction } from 'express';
import { v4 as uuidv4 } from 'uuid';
import { config } from './config';
import { mysqlAdapter } from './adapters/mysqlAdapter';
import { redisAdapter } from './adapters/redisAdapter';
import { neo4jAdapter } from './adapters/neo4jAdapter';
import { toolHealthScheduler } from './services/toolHealthScheduler';
import { logger } from './utils/logger';
import { requestTotal, requestDurationSeconds } from './utils/metrics';

import agentRoutes from './routes/agents';
import toolRoutes from './routes/tools';
import teamRoutes from './routes/teams';
import capabilityRoutes from './routes/capabilities';
import healthRoutes, { metricsRouter } from './routes/health';

const app = express();

// ── Middleware ──────────────────────────────────────────────────────────────

app.use(express.json({ limit: '10mb' }));
app.use(express.urlencoded({ extended: true }));

// Inject x-request-id trace ID on every request
app.use((req: Request, _res: Response, next: NextFunction) => {
  if (!req.headers['x-request-id']) {
    req.headers['x-request-id'] = uuidv4();
  }
  next();
});

// Structured request logging
app.use((req: Request, res: Response, next: NextFunction) => {
  const start = Date.now();
  const traceId = req.headers['x-request-id'] as string;

  res.on('finish', () => {
    const duration = Date.now() - start;
    logger.info('HTTP request', 'router', {
      method: req.method,
      path: req.path,
      status: res.statusCode,
      duration_ms: duration,
      trace_id: traceId,
    });
    requestTotal.inc({
      method: req.method,
      path: req.path,
      status: String(res.statusCode),
    });
    requestDurationSeconds.observe(
      { method: req.method, path: req.path },
      duration / 1000
    );
  });

  next();
});

// ── Routes ──────────────────────────────────────────────────────────────────

app.use('/health', healthRoutes);
app.use('/metrics', metricsRouter);
app.use('/v1/agents', agentRoutes);
app.use('/v1/tools', toolRoutes);
app.use('/v1/teams', teamRoutes);
app.use('/v1/capabilities', capabilityRoutes);

// 404 catch-all
app.use((req: Request, res: Response) => {
  const traceId = req.headers['x-request-id'] as string;
  res.status(404).json({
    error: `Route ${req.method} ${req.path} not found`,
    code: 'NOT_FOUND',
    trace_id: traceId,
  });
});

// Global error handler
app.use((err: Error, req: Request, res: Response, _next: NextFunction) => {
  const traceId = req.headers['x-request-id'] as string;
  logger.error('Unhandled error', 'router', {
    error: err.message,
    stack: err.stack,
    trace_id: traceId,
  });
  res.status(500).json({
    error: 'Internal server error',
    code: 'INTERNAL_ERROR',
    trace_id: traceId,
  });
});

// ── Bootstrap ───────────────────────────────────────────────────────────────

async function bootstrap(): Promise<void> {
  try {
    logger.info('Starting agent-mgmt service', 'main', { port: config.AGENT_MGMT_PORT });

    await mysqlAdapter.connect();
    redisAdapter.connect();
    neo4jAdapter.connect();

    toolHealthScheduler.start();

    const server = app.listen(config.AGENT_MGMT_PORT, () => {
      logger.info('agent-mgmt service listening', 'main', {
        port: config.AGENT_MGMT_PORT,
        env: config.NODE_ENV,
      });
    });

    // Graceful shutdown
    const shutdown = async (signal: string) => {
      logger.info(`Received ${signal}, shutting down gracefully`, 'main');
      toolHealthScheduler.stop();

      server.close(async () => {
        await Promise.all([mysqlAdapter.close(), redisAdapter.close(), neo4jAdapter.close()]);
        logger.info('agent-mgmt service stopped', 'main');
        process.exit(0);
      });

      // Force exit after 15 seconds
      setTimeout(() => {
        logger.error('Forced shutdown after timeout', 'main');
        process.exit(1);
      }, 15000);
    };

    process.on('SIGTERM', () => shutdown('SIGTERM'));
    process.on('SIGINT', () => shutdown('SIGINT'));
  } catch (err: unknown) {
    const error = err as Error;
    logger.error('Bootstrap failed', 'main', { error: error.message, stack: error.stack });
    process.exit(1);
  }
}

bootstrap();

export { app };
