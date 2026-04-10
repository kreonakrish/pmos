import { Router, Request, Response } from 'express';
import { z } from 'zod';
import { capabilityService } from '../services/capabilityService';
import { logger } from '../utils/logger';
import { requestTotal, requestDurationSeconds } from '../utils/metrics';

const router = Router();

function traceId(req: Request): string {
  return (req.headers['x-request-id'] as string) || '';
}

function errorResponse(res: Response, status: number, message: string, code: string, tid: string) {
  return res.status(status).json({ error: message, code, trace_id: tid });
}

const registerCapabilitySchema = z.object({
  capability_type: z.enum(['TOOL', 'SKILL', 'AGENT']),
  capability_id: z.string().min(1),
  name: z.string().min(1),
  description: z.string().optional(),
  spec_json: z.record(z.unknown()).optional(),
  gap_id: z.string().optional(),
  validation_score: z.number().min(0).max(1).optional(),
});

// GET /v1/capabilities
router.get('/', async (req: Request, res: Response) => {
  const start = Date.now();
  const tid = traceId(req);
  try {
    const capabilities = await capabilityService.listCapabilities();
    requestTotal.inc({ method: 'GET', path: '/v1/capabilities', status: '200' });
    return res.json({ capabilities, count: capabilities.length, trace_id: tid });
  } catch (err: unknown) {
    const error = err as Error;
    logger.error('listCapabilities failed', 'router', { error: error.message, trace_id: tid });
    requestTotal.inc({ method: 'GET', path: '/v1/capabilities', status: '500' });
    return errorResponse(res, 500, 'Internal server error', 'INTERNAL_ERROR', tid);
  } finally {
    requestDurationSeconds.observe({ method: 'GET', path: '/v1/capabilities' }, (Date.now() - start) / 1000);
  }
});

// POST /v1/capabilities
router.post('/', async (req: Request, res: Response) => {
  const start = Date.now();
  const tid = traceId(req);
  try {
    const parsed = registerCapabilitySchema.safeParse(req.body);
    if (!parsed.success) {
      requestTotal.inc({ method: 'POST', path: '/v1/capabilities', status: '400' });
      return errorResponse(res, 400, parsed.error.message, 'VALIDATION_ERROR', tid);
    }

    const capability = await capabilityService.registerCapability({
      ...parsed.data,
      trace_id: tid,
    });

    requestTotal.inc({ method: 'POST', path: '/v1/capabilities', status: '201' });
    return res.status(201).json({ capability, trace_id: tid });
  } catch (err: unknown) {
    const error = err as Error;
    logger.error('registerCapability failed', 'router', { error: error.message, trace_id: tid });
    requestTotal.inc({ method: 'POST', path: '/v1/capabilities', status: '500' });
    return errorResponse(res, 500, 'Internal server error', 'INTERNAL_ERROR', tid);
  } finally {
    requestDurationSeconds.observe({ method: 'POST', path: '/v1/capabilities' }, (Date.now() - start) / 1000);
  }
});

export default router;
