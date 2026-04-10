import { Router, Request, Response } from 'express';
import { z } from 'zod';
import { toolService } from '../services/toolService';
import { executeToolTest, ToolTestRequest } from '../services/toolExecutor';
import { toolHistoryService } from '../services/toolHistoryService';
import { logger } from '../utils/logger';
import { requestTotal, requestDurationSeconds } from '../utils/metrics';

const router = Router();

function traceId(req: Request): string {
  return (req.headers['x-request-id'] as string) || '';
}

function errorResponse(res: Response, status: number, message: string, code: string, tid: string) {
  return res.status(status).json({ error: message, code, trace_id: tid });
}

const toolTypeEnum = z.enum(['DATABASE', 'API', 'GITHUB', 'PYTHON', 'WEBSERVICE', 'FILE', 'VECTOR', 'GRAPH']);
const authMethodEnum = z.enum(['NONE', 'API_KEY', 'BEARER', 'BASIC', 'OAUTH2']);

const createToolSchema = z.object({
  name: z.string().min(1),
  description: z.string().optional(),
  tool_type: toolTypeEnum,
  hostname: z.string().optional(),
  endpoint: z.string().optional(),
  auth_method: authMethodEnum.optional(),
  auth_config: z.record(z.unknown()).optional(),
  is_dynamic: z.boolean().optional(),
});

const updateToolSchema = z.object({
  name: z.string().min(1).optional(),
  description: z.string().optional(),
  tool_type: toolTypeEnum.optional(),
  hostname: z.string().optional(),
  endpoint: z.string().optional(),
  auth_method: authMethodEnum.optional(),
  auth_config: z.record(z.unknown()).optional(),
  status: z.enum(['ACTIVE', 'DEGRADED', 'OFFLINE']).optional(),
  avg_latency_ms: z.number().min(0).optional(),
  success_rate: z.number().min(0).max(1).optional(),
});

// GET /v1/tools
router.get('/', async (req: Request, res: Response) => {
  const start = Date.now();
  const tid = traceId(req);
  try {
    const tools = await toolService.listTools();
    requestTotal.inc({ method: 'GET', path: '/v1/tools', status: '200' });
    return res.json({ tools, count: tools.length, trace_id: tid });
  } catch (err: unknown) {
    const error = err as Error;
    logger.error('listTools failed', 'router', { error: error.message, trace_id: tid });
    requestTotal.inc({ method: 'GET', path: '/v1/tools', status: '500' });
    return errorResponse(res, 500, 'Internal server error', 'INTERNAL_ERROR', tid);
  } finally {
    requestDurationSeconds.observe({ method: 'GET', path: '/v1/tools' }, (Date.now() - start) / 1000);
  }
});

// POST /v1/tools
router.post('/', async (req: Request, res: Response) => {
  const start = Date.now();
  const tid = traceId(req);
  try {
    const parsed = createToolSchema.safeParse(req.body);
    if (!parsed.success) {
      requestTotal.inc({ method: 'POST', path: '/v1/tools', status: '400' });
      return errorResponse(res, 400, parsed.error.message, 'VALIDATION_ERROR', tid);
    }
    const tool = await toolService.createTool(parsed.data);
    requestTotal.inc({ method: 'POST', path: '/v1/tools', status: '201' });
    return res.status(201).json({ tool, trace_id: tid });
  } catch (err: unknown) {
    const error = err as Error;
    logger.error('createTool failed', 'router', { error: error.message, trace_id: tid });
    requestTotal.inc({ method: 'POST', path: '/v1/tools', status: '500' });
    return errorResponse(res, 500, 'Internal server error', 'INTERNAL_ERROR', tid);
  } finally {
    requestDurationSeconds.observe({ method: 'POST', path: '/v1/tools' }, (Date.now() - start) / 1000);
  }
});

// POST /v1/tools/test — execute a tool with sample inputs
const testToolSchema = z.object({
  tool_id: z.string().optional(),
  tool_type: z.string(),
  config: z.record(z.unknown()).default({}),
  inputs: z.record(z.unknown()).default({}),
  // Tracing context — passed by orchestrator pipeline or UI
  agent_id: z.string().optional(),
  agent_name: z.string().optional(),
  team_id: z.string().optional(),
  team_name: z.string().optional(),
  conversation_id: z.string().optional(),
  source: z.enum(['manual', 'pipeline', 'health_check']).optional(),
});

router.post('/test', async (req: Request, res: Response) => {
  const start = Date.now();
  const tid = traceId(req);
  try {
    const parsed = testToolSchema.safeParse(req.body);
    if (!parsed.success) {
      requestTotal.inc({ method: 'POST', path: '/v1/tools/test', status: '400' });
      return errorResponse(res, 400, parsed.error.message, 'VALIDATION_ERROR', tid);
    }

    const testReq: ToolTestRequest = {
      tool_id: parsed.data.tool_id || 'test',
      tool_type: parsed.data.tool_type,
      config: parsed.data.config,
      inputs: parsed.data.inputs,
    };

    const result = await executeToolTest(testReq, tid);

    // Persist execution to history with tracing context (fire-and-forget)
    const toolId = parsed.data.tool_id || 'unknown';
    toolHistoryService.recordExecution(toolId, parsed.data.inputs, result, {
      agent_id: parsed.data.agent_id,
      agent_name: parsed.data.agent_name,
      team_id: parsed.data.team_id,
      team_name: parsed.data.team_name,
      conversation_id: parsed.data.conversation_id,
      source: parsed.data.source || 'manual',
    }).catch(() => {});

    const status = result.success ? 200 : 422;
    requestTotal.inc({ method: 'POST', path: '/v1/tools/test', status: String(status) });
    return res.status(status).json(result);
  } catch (err: unknown) {
    const error = err as Error;
    logger.error('toolTest failed', 'router', { error: error.message, trace_id: tid });
    requestTotal.inc({ method: 'POST', path: '/v1/tools/test', status: '500' });
    return errorResponse(res, 500, 'Internal server error', 'INTERNAL_ERROR', tid);
  } finally {
    requestDurationSeconds.observe({ method: 'POST', path: '/v1/tools/test' }, (Date.now() - start) / 1000);
  }
});

// GET /v1/tools/:tool_id/executions — get execution history for a tool
router.get('/:tool_id/executions', async (req: Request, res: Response) => {
  const start = Date.now();
  const tid = traceId(req);
  const tool_id = String(req.params.tool_id);
  const limit = Math.min(Number(req.query.limit) || 50, 200);
  const offset = Number(req.query.offset) || 0;

  try {
    const { executions, total } = await toolHistoryService.getHistory(tool_id, limit, offset);
    requestTotal.inc({ method: 'GET', path: '/v1/tools/:id/executions', status: '200' });
    return res.json({ executions, total, limit, offset, trace_id: tid });
  } catch (err: unknown) {
    const error = err as Error;
    logger.error('getToolHistory failed', 'router', { error: error.message, tool_id, trace_id: tid });
    requestTotal.inc({ method: 'GET', path: '/v1/tools/:id/executions', status: '500' });
    return errorResponse(res, 500, 'Internal server error', 'INTERNAL_ERROR', tid);
  } finally {
    requestDurationSeconds.observe({ method: 'GET', path: '/v1/tools/:id/executions' }, (Date.now() - start) / 1000);
  }
});

// GET /v1/tools/:tool_id
router.get('/:tool_id', async (req: Request, res: Response) => {
  const start = Date.now();
  const tid = traceId(req);
  const tool_id = String(req.params.tool_id);
  try {
    const tool = await toolService.getTool(tool_id);
    if (!tool) {
      requestTotal.inc({ method: 'GET', path: '/v1/tools/:id', status: '404' });
      return errorResponse(res, 404, 'Tool not found', 'NOT_FOUND', tid);
    }
    requestTotal.inc({ method: 'GET', path: '/v1/tools/:id', status: '200' });
    return res.json({ tool, trace_id: tid });
  } catch (err: unknown) {
    const error = err as Error;
    logger.error('getTool failed', 'router', { error: error.message, tool_id, trace_id: tid });
    requestTotal.inc({ method: 'GET', path: '/v1/tools/:id', status: '500' });
    return errorResponse(res, 500, 'Internal server error', 'INTERNAL_ERROR', tid);
  } finally {
    requestDurationSeconds.observe({ method: 'GET', path: '/v1/tools/:id' }, (Date.now() - start) / 1000);
  }
});

// PUT /v1/tools/:tool_id
router.put('/:tool_id', async (req: Request, res: Response) => {
  const start = Date.now();
  const tid = traceId(req);
  const tool_id = String(req.params.tool_id);
  try {
    const parsed = updateToolSchema.safeParse(req.body);
    if (!parsed.success) {
      requestTotal.inc({ method: 'PUT', path: '/v1/tools/:id', status: '400' });
      return errorResponse(res, 400, parsed.error.message, 'VALIDATION_ERROR', tid);
    }
    const tool = await toolService.updateTool(tool_id, parsed.data);
    if (!tool) {
      requestTotal.inc({ method: 'PUT', path: '/v1/tools/:id', status: '404' });
      return errorResponse(res, 404, 'Tool not found', 'NOT_FOUND', tid);
    }
    requestTotal.inc({ method: 'PUT', path: '/v1/tools/:id', status: '200' });
    return res.json({ tool, trace_id: tid });
  } catch (err: unknown) {
    const error = err as Error;
    logger.error('updateTool failed', 'router', { error: error.message, tool_id, trace_id: tid });
    requestTotal.inc({ method: 'PUT', path: '/v1/tools/:id', status: '500' });
    return errorResponse(res, 500, 'Internal server error', 'INTERNAL_ERROR', tid);
  } finally {
    requestDurationSeconds.observe({ method: 'PUT', path: '/v1/tools/:id' }, (Date.now() - start) / 1000);
  }
});

// DELETE /v1/tools/:tool_id
router.delete('/:tool_id', async (req: Request, res: Response) => {
  const start = Date.now();
  const tid = traceId(req);
  const tool_id = String(req.params.tool_id);
  try {
    const deleted = await toolService.deleteTool(tool_id);
    if (!deleted) {
      requestTotal.inc({ method: 'DELETE', path: '/v1/tools/:id', status: '404' });
      return errorResponse(res, 404, 'Tool not found', 'NOT_FOUND', tid);
    }
    requestTotal.inc({ method: 'DELETE', path: '/v1/tools/:id', status: '200' });
    return res.json({ message: 'Tool deleted', trace_id: tid });
  } catch (err: unknown) {
    const error = err as Error;
    logger.error('deleteTool failed', 'router', { error: error.message, tool_id, trace_id: tid });
    requestTotal.inc({ method: 'DELETE', path: '/v1/tools/:id', status: '500' });
    return errorResponse(res, 500, 'Internal server error', 'INTERNAL_ERROR', tid);
  } finally {
    requestDurationSeconds.observe({ method: 'DELETE', path: '/v1/tools/:id' }, (Date.now() - start) / 1000);
  }
});

export default router;
