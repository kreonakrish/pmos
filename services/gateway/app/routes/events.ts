import { Router, Request, Response } from 'express';
import axios from 'axios';
import { config } from '../config';
import { proxyRequest } from '../utils/httpProxy';
import { logger } from '../utils/logger';

const router = Router();

// ──────────────────────────────────────────────────────────────────────────────
// GET /v1/events/conversations/:conversationId/stream
// Long-lived Server-Sent Events stream proxied from the orchestrator's Redis
// stream pmos:events:<conversationId>. Emits one SSE message per pipeline event.
// Used by the Decomposition Timeline UI to render a live trace of agent
// actions, decomposition revisions, score evaluations, and sufficiency
// verdicts as the team works.
// ──────────────────────────────────────────────────────────────────────────────
router.get(
  '/events/conversations/:conversationId/stream',
  async (req: Request, res: Response): Promise<void> => {
    const traceId = (req as Request & { id?: string }).id;
    const { conversationId } = req.params;
    const lastEventId =
      (req.headers['last-event-id'] as string | undefined) ??
      (req.query.last_event_id as string | undefined) ??
      '';

    logger.info('events_stream_open', {
      layer: 'router',
      trace_id: traceId,
      conversation_id: conversationId,
      last_event_id: lastEventId,
    });

    // SSE headers: keep the connection open and disable proxy buffering.
    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');
    res.setHeader('X-Accel-Buffering', 'no');
    res.flushHeaders?.();

    const upstreamUrl =
      `${config.ORCHESTRATOR_URL}/v1/events/conversations/` +
      encodeURIComponent(String(conversationId)) +
      `/stream`;

    const upstreamHeaders: Record<string, string> = {
      accept: 'text/event-stream',
      'x-request-id': traceId ?? '',
    };
    if (lastEventId) {
      upstreamHeaders['last-event-id'] = lastEventId;
    }
    if (req.headers['authorization']) {
      upstreamHeaders['authorization'] = req.headers['authorization'] as string;
    }

    let upstream: { data: NodeJS.ReadableStream; status: number } | null = null;
    try {
      const resp = await axios.get(upstreamUrl, {
        headers: upstreamHeaders,
        responseType: 'stream',
        timeout: 0, // streaming endpoint — no overall timeout
        validateStatus: () => true,
      });
      upstream = resp;

      if (resp.status >= 400) {
        // Drain and end with a JSON error encoded in SSE.
        res.write(`event: error\ndata: {"status":${resp.status}}\n\n`);
        res.end();
        return;
      }

      resp.data.on('data', (chunk: Buffer) => {
        // Pipe upstream SSE bytes verbatim — they're already SSE-formatted
        // by the orchestrator's events route.
        res.write(chunk);
      });

      resp.data.on('end', () => {
        logger.info('events_stream_upstream_ended', {
          layer: 'router',
          trace_id: traceId,
          conversation_id: conversationId,
        });
        res.end();
      });

      resp.data.on('error', (err: Error) => {
        logger.warn('events_stream_upstream_error', {
          layer: 'router',
          trace_id: traceId,
          error: err.message,
        });
        res.end();
      });
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      logger.error('events_stream_failed', {
        layer: 'router',
        trace_id: traceId,
        conversation_id: conversationId,
        error: message,
      });
      res.status(502).end();
      return;
    }

    // If the browser disconnects, close the upstream stream so we don't keep
    // a dead Redis read open.
    req.on('close', () => {
      logger.info('events_stream_client_closed', {
        layer: 'router',
        trace_id: traceId,
        conversation_id: conversationId,
      });
      try {
        // Casting because axios' Readable stream is wrapped.
        const s = upstream?.data as
          | (NodeJS.ReadableStream & { destroy?: () => void })
          | undefined;
        s?.destroy?.();
      } catch {
        // ignore
      }
    });
  },
);

// ──────────────────────────────────────────────────────────────────────────────
// GET /v1/events/conversations/:conversationId/replay
// JSON replay of all events for the conversation, sourced from MySQL
// pipeline_events. Used by the Decomposition Timeline UI for completed runs.
// ──────────────────────────────────────────────────────────────────────────────
router.get(
  '/events/conversations/:conversationId/replay',
  async (req: Request, res: Response): Promise<void> => {
    const { conversationId } = req.params;
    await proxyRequest(req, res, {
      targetUrl:
        `${config.ORCHESTRATOR_URL}/v1/events/conversations/` +
        encodeURIComponent(String(conversationId)) +
        `/replay`,
      timeout: 30_000,
    });
  },
);

export default router;
