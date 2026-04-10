import { Request, Response, NextFunction } from 'express';
import { v4 as uuidv4 } from 'uuid';

/**
 * Injects a unique request ID into req.id and sets x-request-id response header.
 * If the incoming request already has x-request-id, that value is reused.
 */
export function requestId(req: Request, res: Response, next: NextFunction): void {
  const existing = req.headers['x-request-id'];
  const id = typeof existing === 'string' && existing.length > 0 ? existing : uuidv4();

  // Express 5 removed req.id from typings; assign via type assertion
  (req as Request & { id: string }).id = id;
  res.setHeader('x-request-id', id);

  next();
}
