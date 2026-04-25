import express, { Request, Response } from 'express';
import { createServer } from 'http';
import { Registry, collectDefaultMetrics, Counter, Histogram } from 'prom-client';
import { config } from './config';
import { logger } from './utils/logger';
import { requestId } from './middleware/requestId';
import { authMiddleware } from './middleware/auth';
import { enforceRegistry } from './middleware/rbac';
import { rateLimiter } from './middleware/rateLimiter';
import { errorHandler } from './middleware/errorHandler';
import healthRouter from './routes/health';
import orchestratorRouter from './routes/orchestrator';
import agentMgmtRouter from './routes/agentMgmt';
import ragRouter from './routes/rag';
import scoringRouter from './routes/scoring';
import memoryRouter from './routes/memory';
import translatorRouter from './routes/translator';
import authRouter from './routes/auth';
import usersRouter from './routes/users';
import logsRouter from './routes/logs';
import { attachWebSocketServer } from './websocket/streamHandler';
import { seedBootstrapUsers } from './services/authService';

// ─── Prometheus registry ──────────────────────────────────────────────────────
const registry = new Registry();
collectDefaultMetrics({ register: registry });

const requestTotal = new Counter({
  name: 'request_total',
  help: 'Total HTTP requests',
  labelNames: ['method', 'path', 'status'],
  registers: [registry],
});

const requestDuration = new Histogram({
  name: 'request_duration_seconds',
  help: 'HTTP request duration in seconds',
  labelNames: ['method', 'path'],
  buckets: [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5],
  registers: [registry],
});

// ─── Express app ─────────────────────────────────────────────────────────────
const app = express();

// Parse JSON bodies
app.use(express.json({ limit: '10mb' }));
app.use(express.urlencoded({ extended: true }));

// 1. Inject request ID first so all subsequent logs carry it
app.use(requestId);

// 2. Prometheus instrumentation (before auth so /metrics is measured)
app.use((req: Request, res: Response, next) => {
  const start = process.hrtime.bigint();
  const path = req.path;
  const method = req.method;

  res.on('finish', () => {
    const durationNs = process.hrtime.bigint() - start;
    const durationSec = Number(durationNs) / 1e9;
    const status = String(res.statusCode);

    requestTotal.labels(method, path, status).inc();
    requestDuration.labels(method, path).observe(durationSec);
  });

  next();
});

// 3. Public routes — no auth, no rate limit
app.use('/health', healthRouter);

app.get('/metrics', async (_req: Request, res: Response): Promise<void> => {
  res.setHeader('Content-Type', registry.contentType);
  res.send(await registry.metrics());
});

// 4. Auth routes (public — before auth middleware)
app.use('/v1', authRouter);

// 5. Auth + rate limiter on all /v1 routes
app.use('/v1', authMiddleware);
app.use('/v1', rateLimiter);

// 5b. Server-side RBAC enforcement against MySQL (DB-backed; the JWT's
//     embedded permissions are advisory only). Mounted AFTER authMiddleware
//     so req.user is populated. Skips /v1/auth/* internally.
app.use('/v1', enforceRegistry);

// 6. Versioned API routes
app.use('/v1', usersRouter);
app.use('/v1', orchestratorRouter);
app.use('/v1', agentMgmtRouter);
app.use('/v1', ragRouter);
app.use('/v1', scoringRouter);
app.use('/v1', memoryRouter);
app.use('/v1', translatorRouter);
app.use('/v1', logsRouter);

// 7. Global error handler (must be last)
app.use(errorHandler);

// ─── HTTP + WebSocket server ─────────────────────────────────────────────────
const httpServer = createServer(app);
attachWebSocketServer(httpServer);

// ─── Graceful startup ────────────────────────────────────────────────────────
const server = httpServer.listen(config.GATEWAY_PORT, () => {
  logger.info('gateway_started', {
    layer: 'service',
    port: config.GATEWAY_PORT,
    env: config.NODE_ENV,
  });
  // Seed bootstrap users (idempotent; only creates if missing)
  seedBootstrapUsers().catch((err: unknown) => {
    const msg = err instanceof Error ? err.message : String(err);
    logger.error('seed_bootstrap_users_failed', { reason: msg });
  });
});

// ─── Graceful shutdown ───────────────────────────────────────────────────────
function shutdown(signal: string): void {
  logger.info('gateway_shutdown', { layer: 'service', signal });
  server.close(() => {
    logger.info('gateway_shutdown_complete', { layer: 'service' });
    process.exit(0);
  });

  // Force exit if graceful drain takes too long
  setTimeout(() => {
    logger.error('gateway_shutdown_timeout', { layer: 'service' });
    process.exit(1);
  }, 10_000);
}

process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));

export { app, httpServer };
