import { Router, Request, Response } from 'express';
import Redis from 'ioredis';
import { config } from '../config';
import { proxyRequest } from '../utils/httpProxy';
import { logger } from '../utils/logger';
import { v4 as uuidv4 } from 'uuid';

const router = Router();

function getPublishClient(): Redis {
  return new Redis(config.REDIS_URL, { lazyConnect: true, enableOfflineQueue: false });
}

/**
 * POST /v1/rag/query
 * Proxies to RAG service /v1/rag/query
 */
router.post('/rag/query', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  logger.info('proxy_rag_query', { layer: 'router', trace_id: traceId });
  await proxyRequest(req, res, { targetUrl: `${config.RAG_SERVICE_URL}/v1/rag/query`, timeout: 30_000 });
});

/**
 * POST /v1/documents
 * Ingests a document: proxies to RAG /v1/rag/ingest AND publishes to events:documents Redis stream.
 */
router.post('/documents', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id ?? uuidv4();
  logger.info('proxy_document_ingest', { layer: 'router', trace_id: traceId });

  // Publish to Redis stream before proxying so the event is always emitted
  const redis = getPublishClient();
  try {
    await redis.xadd(
      'events:documents',
      '*',
      'trace_id', traceId,
      'source_service', 'gateway',
      'timestamp', new Date().toISOString(),
      'schema_version', '1',
      'payload', JSON.stringify(req.body),
    );
    logger.info('redis_stream_published', {
      layer: 'adapter',
      trace_id: traceId,
      stream: 'events:documents',
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    logger.error('redis_stream_publish_failed', {
      layer: 'adapter',
      trace_id: traceId,
      error: message,
      stream: 'events:documents',
    });
    // Do not abort — still proxy to RAG service
  } finally {
    redis.disconnect();
  }

  await proxyRequest(req, res, { targetUrl: `${config.RAG_SERVICE_URL}/v1/rag/ingest`, timeout: 60_000 });
});

// ─── Document management routes ─────────────────────────────────────────────

/**
 * GET /v1/documents
 */
router.get('/documents', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  logger.info('proxy_documents_list', { layer: 'router', trace_id: traceId });
  await proxyRequest(req, res, { targetUrl: `${config.RAG_SERVICE_URL}/v1/rag/documents` });
});

/**
 * GET /v1/documents/:docId
 */
router.get('/documents/:docId', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { docId } = req.params;
  logger.info('proxy_document_get', { layer: 'router', trace_id: traceId, doc_id: docId });
  await proxyRequest(req, res, { targetUrl: `${config.RAG_SERVICE_URL}/v1/rag/documents/${docId}` });
});

/**
 * DELETE /v1/documents/:docId
 */
router.delete('/documents/:docId', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { docId } = req.params;
  logger.info('proxy_document_delete', { layer: 'router', trace_id: traceId, doc_id: docId });
  await proxyRequest(req, res, { targetUrl: `${config.RAG_SERVICE_URL}/v1/rag/documents/${docId}` });
});

/**
 * POST /v1/documents/:docId/reindex
 */
router.post('/documents/:docId/reindex', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  const { docId } = req.params;
  logger.info('proxy_document_reindex', { layer: 'router', trace_id: traceId, doc_id: docId });
  await proxyRequest(req, res, { targetUrl: `${config.RAG_SERVICE_URL}/v1/rag/documents/${docId}/reindex`, timeout: 60_000 });
});

/**
 * POST /v1/documents/upload — Multipart file upload for binary formats (PDF, DOCX, XLSX, etc.)
 * Proxied directly to RAG service which handles parsing.
 */
router.post('/documents/upload', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  logger.info('proxy_document_upload', { layer: 'router', trace_id: traceId });

  // For multipart uploads, pipe the raw request to the RAG service
  const axios = (await import('axios')).default;
  try {
    const upstream = await axios.post(
      `${config.RAG_SERVICE_URL}/v1/rag/upload`,
      req,
      {
        headers: {
          ...req.headers,
          host: undefined,
          'x-request-id': traceId ?? '',
        },
        maxContentLength: 50 * 1024 * 1024, // 50MB
        timeout: 120_000,
        validateStatus: () => true,
      },
    );
    res.status(upstream.status).json(upstream.data);
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    logger.error('proxy_upload_failed', { layer: 'adapter', trace_id: traceId, error: message });
    res.status(502).json({ error: 'Upload proxy failed', code: 'UPSTREAM_ERROR', trace_id: traceId });
  }
});

/**
 * GET /v1/rag/config — Get RAG pipeline configuration for the UI
 */
router.get('/rag/config', async (req: Request, res: Response): Promise<void> => {
  const traceId = (req as Request & { id?: string }).id;
  logger.info('proxy_rag_config', { layer: 'router', trace_id: traceId });
  await proxyRequest(req, res, { targetUrl: `${config.RAG_SERVICE_URL}/v1/rag/config` });
});

export default router;
