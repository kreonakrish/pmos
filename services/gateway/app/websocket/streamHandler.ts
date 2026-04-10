import { IncomingMessage, Server as HttpServer } from 'http';
import { WebSocket, WebSocketServer } from 'ws';
import jwt from 'jsonwebtoken';
import axios from 'axios';
import { v4 as uuidv4 } from 'uuid';
import { config } from '../config';
import { logger } from '../utils/logger';
import { JwtPayload } from '../middleware/auth';

/** Message schema pushed to WS clients. */
interface StreamChunk {
  type: 'step' | 'tool_call' | 'score' | 'course_correct' | 'complete' | 'error';
  agent_name: string;
  content: string;
  score: number | null;
  trace_id: string;
  timestamp: string;
}

function sendJson(ws: WebSocket, data: unknown): void {
  if (ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(data));
  }
}

function sendError(ws: WebSocket, message: string, traceId: string): void {
  const chunk: StreamChunk = {
    type: 'error',
    agent_name: 'gateway',
    content: message,
    score: null,
    trace_id: traceId,
    timestamp: new Date().toISOString(),
  };
  sendJson(ws, chunk);
  ws.close(1008, message);
}

function authenticateToken(token: string): JwtPayload {
  return jwt.verify(token, config.JWT_SECRET) as JwtPayload;
}

/**
 * Attaches a WebSocket server to the given HTTP server.
 * Endpoint: ws://<host>:4000/v1/ws/chat
 * Auth: ?token=<JWT>
 */
export function attachWebSocketServer(httpServer: HttpServer): WebSocketServer {
  const wss = new WebSocketServer({ server: httpServer, path: '/v1/ws/chat' });

  wss.on('connection', (ws: WebSocket, req: IncomingMessage) => {
    const traceId = uuidv4();

    // Extract JWT from query string
    const url = new URL(req.url ?? '', `http://${req.headers.host}`);
    const token = url.searchParams.get('token');

    if (!token) {
      logger.warn('ws_auth_missing_token', { layer: 'websocket', trace_id: traceId });
      sendError(ws, 'Authentication required: provide ?token=<JWT>', traceId);
      return;
    }

    let user: JwtPayload;
    try {
      user = authenticateToken(token);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Token verification failed';
      logger.warn('ws_auth_failed', { layer: 'websocket', trace_id: traceId, reason: message });
      sendError(ws, `Authentication failed: ${message}`, traceId);
      return;
    }

    logger.info('ws_connected', { layer: 'websocket', trace_id: traceId, sub: user.sub });

    ws.on('message', async (raw) => {
      let payload: Record<string, unknown>;
      try {
        payload = JSON.parse(raw.toString()) as Record<string, unknown>;
      } catch {
        sendJson(ws, {
          type: 'error',
          agent_name: 'gateway',
          content: 'Invalid JSON payload',
          score: null,
          trace_id: traceId,
          timestamp: new Date().toISOString(),
        });
        return;
      }

      logger.info('ws_message_received', {
        layer: 'websocket',
        trace_id: traceId,
        sub: user.sub,
      });

      // Forward to orchestrator streaming endpoint
      try {
        const response = await axios.post(
          `${config.ORCHESTRATOR_URL}/v1/orchestrator/chat/stream`,
          { ...payload, trace_id: traceId, user_id: user.sub },
          {
            headers: {
              'content-type': 'application/json',
              'x-request-id': traceId,
            },
            responseType: 'stream',
            timeout: 300_000,
          },
        );

        const stream = response.data as NodeJS.ReadableStream;
        let buffer = '';

        stream.on('data', (chunk: Buffer) => {
          buffer += chunk.toString();
          const lines = buffer.split('\n');
          buffer = lines.pop() ?? '';

          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed) continue;

            // SSE format: "data: {...}"
            const jsonStr = trimmed.startsWith('data: ') ? trimmed.slice(6) : trimmed;
            try {
              const parsed: StreamChunk = JSON.parse(jsonStr) as StreamChunk;
              sendJson(ws, { ...parsed, trace_id: traceId });

              if (parsed.type === 'complete' || parsed.type === 'error') {
                ws.close(1000, 'Stream complete');
              }
            } catch {
              // Non-JSON SSE comment or keep-alive — ignore
            }
          }
        });

        stream.on('error', (err: Error) => {
          logger.error('ws_stream_error', {
            layer: 'websocket',
            trace_id: traceId,
            error: err.message,
          });
          sendError(ws, `Upstream stream error: ${err.message}`, traceId);
        });

        stream.on('end', () => {
          logger.info('ws_stream_ended', { layer: 'websocket', trace_id: traceId });
        });
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : 'Upstream error';
        logger.error('ws_upstream_error', {
          layer: 'websocket',
          trace_id: traceId,
          error: message,
        });
        sendError(ws, `Failed to reach orchestrator: ${message}`, traceId);
      }
    });

    ws.on('close', (code, reason) => {
      logger.info('ws_disconnected', {
        layer: 'websocket',
        trace_id: traceId,
        close_code: code,
        reason: reason.toString(),
      });
    });

    ws.on('error', (err: Error) => {
      logger.error('ws_socket_error', {
        layer: 'websocket',
        trace_id: traceId,
        error: err.message,
      });
    });
  });

  return wss;
}
