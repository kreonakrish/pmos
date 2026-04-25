import axios, { AxiosRequestConfig, AxiosResponse } from 'axios';
import { Request, Response } from 'express';
import { logger } from './logger';

export interface ProxyOptions {
  targetUrl: string;
  timeout?: number;
  transformRequest?: (body: unknown) => unknown;
  transformResponse?: (data: unknown) => unknown;
}

/**
 * Forward an Express request to a downstream service and pipe the response back.
 * Propagates x-request-id and Authorization headers.
 */
export async function proxyRequest(
  req: Request,
  res: Response,
  options: ProxyOptions,
): Promise<void> {
  const { targetUrl, timeout = 10000 } = options;
  const traceId = req.id as string | undefined;
  const startMs = Date.now();

  const headers: Record<string, string> = {
    'content-type': 'application/json',
    'x-request-id': traceId ?? '',
  };

  // Propagate auth header downstream
  if (req.headers['authorization']) {
    headers['authorization'] = req.headers['authorization'] as string;
  }
  if (req.headers['x-api-key']) {
    headers['x-api-key'] = req.headers['x-api-key'] as string;
  }

  // Propagate the resolved user identity so downstream FastAPI services
  // can do their own RBAC lookup without re-decoding the JWT. The gateway
  // is the trust boundary: by the time we get here, authMiddleware has
  // already verified the signature.
  const reqUser = (req as Request & { user?: { uid?: number; sub?: string } }).user;
  if (reqUser?.uid !== undefined) {
    headers['x-user-id'] = String(reqUser.uid);
  }
  if (reqUser?.sub) {
    headers['x-user-sub'] = reqUser.sub;
  }

  const body = options.transformRequest ? options.transformRequest(req.body) : req.body;

  const axiosConfig: AxiosRequestConfig = {
    method: req.method as AxiosRequestConfig['method'],
    url: targetUrl,
    headers,
    data: ['GET', 'HEAD', 'DELETE'].includes(req.method.toUpperCase()) ? undefined : body,
    params: req.query,
    timeout,
    validateStatus: () => true, // let gateway forward all status codes
  };

  try {
    const upstream: AxiosResponse = await axios(axiosConfig);
    const durationMs = Date.now() - startMs;

    logger.info('proxy_response', {
      layer: 'adapter',
      trace_id: traceId,
      target_url: targetUrl,
      status: upstream.status,
      duration_ms: durationMs,
    });

    // Forward upstream headers selectively
    const forwardHeaders = ['content-type', 'x-request-id', 'retry-after'];
    forwardHeaders.forEach((h) => {
      const val = upstream.headers[h];
      if (val) res.setHeader(h, val as string);
    });

    const responseData = options.transformResponse
      ? options.transformResponse(upstream.data)
      : upstream.data;

    res.status(upstream.status).json(responseData);
  } catch (err: unknown) {
    const durationMs = Date.now() - startMs;
    const message = err instanceof Error ? err.message : String(err);

    logger.error('proxy_error', {
      layer: 'adapter',
      trace_id: traceId,
      target_url: targetUrl,
      error: message,
      duration_ms: durationMs,
    });

    res.status(502).json({
      error: 'Upstream service unavailable',
      code: 'UPSTREAM_ERROR',
      trace_id: traceId,
    });
  }
}
