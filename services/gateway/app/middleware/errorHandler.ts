import { Request, Response, NextFunction } from 'express';
import { logger } from '../utils/logger';

export interface ApiError extends Error {
  statusCode?: number;
  code?: string;
}

/**
 * Global Express error handler.
 * Must be the last middleware registered (4-parameter signature).
 */
export function errorHandler(
  err: ApiError,
  req: Request,
  res: Response,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  _next: NextFunction,
): void {
  const traceId = (req as Request & { id?: string }).id;
  const statusCode = err.statusCode ?? 500;
  const code = err.code ?? 'INTERNAL_ERROR';

  logger.error('unhandled_error', {
    layer: 'middleware',
    trace_id: traceId,
    error: err.message,
    stack: err.stack,
    status_code: statusCode,
  });

  res.status(statusCode).json({
    error: err.message || 'An unexpected error occurred',
    code,
    trace_id: traceId,
  });
}
