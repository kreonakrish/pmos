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

/**
 * GET /v1/conversations/:id/feedback
 * Phase C.3: list prior feedback rows for the UI's "Carrying forward" badge.
 */
router.get('/conversations/:id/feedback', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { id } = req.params;
  logger.info('proxy_conversation_feedback_list', { layer: 'router', trace_id: traceId, conversation_id: id });
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

// ─── Model Governance routes ────────────────────────────────────────────────

/**
 * GET /v1/governance/traces — list recent traces
 */
router.get('/governance/traces', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  logger.info('proxy_governance_list', { layer: 'router', trace_id: traceId });
  const qs = req.url.includes('?') ? req.url.substring(req.url.indexOf('?')) : '';
  await proxyRequest(req, res, {
    targetUrl: `${config.ORCHESTRATOR_URL}/v1/governance/traces${qs}`,
  });
});

/**
 * GET /v1/governance/traces/by-conversation/:cid
 */
router.get('/governance/traces/by-conversation/:cid', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { cid } = req.params;
  logger.info('proxy_governance_by_conv', { layer: 'router', trace_id: traceId, conversation_id: cid });
  await proxyRequest(req, res, {
    targetUrl: `${config.ORCHESTRATOR_URL}/v1/governance/traces/by-conversation/${cid}`,
  });
});

/**
 * GET /v1/governance/traces/:targetTraceId — full reasoning chain
 */
router.get('/governance/traces/:targetTraceId', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { targetTraceId } = req.params;
  logger.info('proxy_governance_trace', {
    layer: 'router',
    trace_id: traceId,
    target_trace_id: targetTraceId,
  });
  await proxyRequest(req, res, {
    targetUrl: `${config.ORCHESTRATOR_URL}/v1/governance/traces/${targetTraceId}`,
  });
});

// ─── ML Insights routes ─────────────────────────────────────────────────────
// Bandit + embedding observability for the learning loop.

function mlProxy(pathname: string) {
  return async (req: Request, res: Response): Promise<void> => {
    const traceId = (req as Request & { id?: string }).id;
    const qs = req.url.includes('?') ? req.url.substring(req.url.indexOf('?')) : '';
    logger.info('proxy_ml', { layer: 'router', trace_id: traceId, path: pathname });
    await proxyRequest(req, res, {
      targetUrl: `${config.ORCHESTRATOR_URL}${pathname}${qs}`,
    });
  };
}

router.get('/ml/bandits/summary',     mlProxy('/v1/ml/bandits/summary'));
router.get('/ml/bandits/state',       mlProxy('/v1/ml/bandits/state'));
router.get('/ml/bandits/decisions',   mlProxy('/v1/ml/bandits/decisions'));
router.get('/ml/bandits/convergence', mlProxy('/v1/ml/bandits/convergence'));
router.get('/ml/embeddings/summary',    mlProxy('/v1/ml/embeddings/summary'));
router.get('/ml/embeddings/projection', mlProxy('/v1/ml/embeddings/projection'));
router.get('/ml/embeddings/similar',    mlProxy('/v1/ml/embeddings/similar'));

// Learned scorer (1B) + SOP discovery (2D)
router.get('/ml/learned-scorer/summary',     mlProxy('/v1/ml/learned-scorer/summary'));
router.get('/ml/learned-scorer/predictions', mlProxy('/v1/ml/learned-scorer/predictions'));
router.get('/ml/sops/proposals',             mlProxy('/v1/ml/sops/proposals'));

router.post('/ml/sops/proposals/:id/promote', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { id } = req.params;
  logger.info('proxy_ml_sop_promote', { layer: 'router', trace_id: traceId, proposal_id: id });
  await proxyRequest(req, res, {
    targetUrl: `${config.ORCHESTRATOR_URL}/v1/ml/sops/proposals/${id}/promote`,
  });
});

router.post('/ml/sops/proposals/:id/reject', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { id } = req.params;
  logger.info('proxy_ml_sop_reject', { layer: 'router', trace_id: traceId, proposal_id: id });
  await proxyRequest(req, res, {
    targetUrl: `${config.ORCHESTRATOR_URL}/v1/ml/sops/proposals/${id}/reject`,
  });
});

// ─── Data Catalog (systems integration) routes ─────────────────────────────
function catalogProxy(pathname: string) {
  return async (req: Request, res: Response): Promise<void> => {
    const traceId = (req as Request & { id?: string }).id;
    const qs = req.url.includes('?') ? req.url.substring(req.url.indexOf('?')) : '';
    logger.info('proxy_catalog', { layer: 'router', trace_id: traceId, path: pathname });
    await proxyRequest(req, res, {
      targetUrl: `${config.ORCHESTRATOR_URL}${pathname}${qs}`,
    });
  };
}

router.get('/catalog/crawlers', catalogProxy('/v1/catalog/crawlers'));
router.post('/catalog/crawlers', catalogProxy('/v1/catalog/crawlers'));
router.get('/catalog/assets', catalogProxy('/v1/catalog/assets'));
router.get('/catalog/ontology', catalogProxy('/v1/catalog/ontology'));
router.get('/catalog/mapping-decisions', catalogProxy('/v1/catalog/mapping-decisions'));
router.get('/catalog/mapping-decisions/summary', catalogProxy('/v1/catalog/mapping-decisions/summary'));
// Ext2 — deterministic Report nodes (Reports tab).
router.get('/catalog/reports', catalogProxy('/v1/catalog/reports'));

router.get('/catalog/crawlers/:id/runs', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { id } = req.params;
  logger.info('proxy_catalog_runs', { layer: 'router', trace_id: traceId, crawler_id: id });
  await proxyRequest(req, res, {
    targetUrl: `${config.ORCHESTRATOR_URL}/v1/catalog/crawlers/${id}/runs`,
  });
});

router.post('/catalog/crawlers/:id/run', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { id } = req.params;
  logger.info('proxy_catalog_run', { layer: 'router', trace_id: traceId, crawler_id: id });
  await proxyRequest(req, res, {
    targetUrl: `${config.ORCHESTRATOR_URL}/v1/catalog/crawlers/${id}/run`,
    timeout: 300_000,
  });
});

router.get('/catalog/assets/:fqName', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const fq = (req.params as Record<string, string>).fqName || '';
  logger.info('proxy_catalog_asset_detail', { layer: 'router', trace_id: traceId, fq });
  await proxyRequest(req, res, {
    targetUrl: `${config.ORCHESTRATOR_URL}/v1/catalog/assets/${encodeURIComponent(fq)}`,
  });
});

router.post('/catalog/mapping-decisions/:id/review', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { id } = req.params;
  logger.info('proxy_catalog_review', { layer: 'router', trace_id: traceId, decision_id: id });
  await proxyRequest(req, res, {
    targetUrl: `${config.ORCHESTRATOR_URL}/v1/catalog/mapping-decisions/${id}/review`,
  });
});

// ─── Phase A5 / B / E4 / F5 / F3 — additional catalog endpoints ─────────────

// Asset ↔ Ontology ↔ Source ↔ CrawlRun ↔ Tool lineage view (Lineage & Runs tab).
router.get('/catalog/lineage', catalogProxy('/v1/catalog/lineage'));

// Per-tool coverage (Tool Studio Coverage tab).
router.get('/catalog/tools/:tool_id/coverage', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const tool_id = String((req.params as Record<string, string>).tool_id || '');
  const qs = req.url.includes('?') ? req.url.substring(req.url.indexOf('?')) : '';
  logger.info('proxy_catalog_tool_coverage', { layer: 'router', trace_id: traceId, tool_id });
  await proxyRequest(req, res, {
    targetUrl: `${config.ORCHESTRATOR_URL}/v1/catalog/tools/${encodeURIComponent(tool_id)}/coverage${qs}`,
  });
});

// Live Neo4j schema visualization (Schema Graph page).
router.get('/catalog/schema-graph', catalogProxy('/v1/catalog/schema-graph'));

// Phase E4 — mapping version history.
router.get('/catalog/mapping-history', catalogProxy('/v1/catalog/mapping-history'));

// Phase F5 — Synonym proposals (Synonym Review tab).
router.get('/catalog/synonym-proposals', catalogProxy('/v1/catalog/synonym-proposals'));
router.get('/catalog/synonym-proposals/:proposal_id', async (req: Request, res: Response): Promise<void> => {
  const proposal_id = String((req.params as Record<string, string>).proposal_id || '');
  await proxyRequest(req, res, {
    targetUrl: `${config.ORCHESTRATOR_URL}/v1/catalog/synonym-proposals/${encodeURIComponent(proposal_id)}`,
  });
});
router.post('/catalog/synonym-proposals/:proposal_id/review', async (req: Request, res: Response): Promise<void> => {
  const proposal_id = String((req.params as Record<string, string>).proposal_id || '');
  await proxyRequest(req, res, {
    targetUrl: `${config.ORCHESTRATOR_URL}/v1/catalog/synonym-proposals/${encodeURIComponent(proposal_id)}/review`,
  });
});
router.post('/catalog/consolidate', catalogProxy('/v1/catalog/consolidate'));

// ─── Phase F3 — Auditor Issues (Govern → Auditor Issues page) ──────────────
function governanceProxy(pathname: string) {
  return async (req: Request, res: Response): Promise<void> => {
    const traceId = (req as Request & { id?: string }).id;
    const qs = req.url.includes('?') ? req.url.substring(req.url.indexOf('?')) : '';
    logger.info('proxy_governance', { layer: 'router', trace_id: traceId, path: pathname });
    await proxyRequest(req, res, {
      targetUrl: `${config.ORCHESTRATOR_URL}${pathname}${qs}`,
    });
  };
}
router.get('/governance/auditor-issues', governanceProxy('/v1/governance/auditor-issues'));
router.get('/governance/auditor-issues/summary', governanceProxy('/v1/governance/auditor-issues/summary'));
router.get('/governance/auditor-issues/:issue_id', async (req: Request, res: Response): Promise<void> => {
  const issue_id = String((req.params as Record<string, string>).issue_id || '');
  await proxyRequest(req, res, {
    targetUrl: `${config.ORCHESTRATOR_URL}/v1/governance/auditor-issues/${encodeURIComponent(issue_id)}`,
  });
});
router.post('/governance/auditor-issues/:issue_id/resolve', async (req: Request, res: Response): Promise<void> => {
  const issue_id = String((req.params as Record<string, string>).issue_id || '');
  await proxyRequest(req, res, {
    targetUrl: `${config.ORCHESTRATOR_URL}/v1/governance/auditor-issues/${encodeURIComponent(issue_id)}/resolve`,
  });
});

export default router;
