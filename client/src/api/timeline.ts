// Decomposition Timeline API — Phase A.7
//
// Two surfaces:
//   - replayTimeline(conversationId): fetch all events for a completed
//     conversation from MySQL pipeline_events.
//   - streamTimeline(conversationId, onEvent, onClose): open an SSE stream
//     from the gateway (/v1/events/conversations/:id/stream) and invoke
//     onEvent for each parsed event. Returns an abort handle.
//
// We use fetch + ReadableStream rather than the EventSource API so we can
// include the JWT bearer token (EventSource does not support custom headers).

import apiClient from './axios';

const runtimeCfg =
  (typeof window !== 'undefined' &&
    (window as unknown as { __PMOS_CONFIG__?: { apiBaseUrl?: string } })
      .__PMOS_CONFIG__) ||
  {};
const API_BASE_URL: string =
  runtimeCfg.apiBaseUrl || import.meta.env.VITE_API_BASE_URL || '';

export interface TimelineEvent {
  event_id: string;
  trace_id: string;
  conversation_id: string;
  graph_id?: string;
  node_id?: string;
  iteration?: number;
  round?: number;
  kind: string;
  status: string;
  payload: Record<string, unknown>;
  ts: string;
}

export interface ReplayResponse {
  conversation_id: string;
  events: TimelineEvent[];
}

export async function replayTimeline(
  conversationId: string,
): Promise<TimelineEvent[]> {
  const resp = await apiClient.get<ReplayResponse>(
    `/v1/events/conversations/${encodeURIComponent(conversationId)}/replay`,
  );
  return resp.data.events ?? [];
}

// ──────────────────────────────────────────────────────────────────────────────
// SSE streaming via fetch + ReadableStream
// ──────────────────────────────────────────────────────────────────────────────

export interface StreamHandle {
  abort: () => void;
}

interface ParsedSSE {
  id?: string;
  event?: string;
  data?: string;
}

function parseSSEBlock(block: string): ParsedSSE | null {
  // SSE block ends with a blank line. Each line is `field: value`.
  const out: ParsedSSE = {};
  for (const line of block.split('\n')) {
    if (!line || line.startsWith(':')) continue; // comment / heartbeat
    const idx = line.indexOf(':');
    if (idx < 0) continue;
    const field = line.slice(0, idx).trim();
    // Value has an optional leading space per spec
    const value = line.slice(idx + 1).replace(/^\s/, '');
    if (field === 'id') out.id = value;
    else if (field === 'event') out.event = value;
    else if (field === 'data') out.data = (out.data ?? '') + value;
  }
  return out.data !== undefined ? out : null;
}

export function streamTimeline(
  conversationId: string,
  onEvent: (e: TimelineEvent) => void,
  onClose?: (reason?: string) => void,
  lastEventId?: string,
): StreamHandle {
  const controller = new AbortController();

  const url =
    `${API_BASE_URL}/v1/events/conversations/${encodeURIComponent(conversationId)}/stream` +
    (lastEventId ? `?last_event_id=${encodeURIComponent(lastEventId)}` : '');

  const headers: Record<string, string> = { accept: 'text/event-stream' };
  const token = localStorage.getItem('pmos_token');
  if (token) headers.authorization = `Bearer ${token}`;
  if (lastEventId) headers['last-event-id'] = lastEventId;

  (async () => {
    try {
      const resp = await fetch(url, {
        method: 'GET',
        headers,
        signal: controller.signal,
      });
      if (!resp.ok || !resp.body) {
        onClose?.(`status_${resp.status}`);
        return;
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';
      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          onClose?.('upstream_ended');
          return;
        }
        buffer += decoder.decode(value, { stream: true });
        // SSE events are separated by a blank line (\n\n).
        let sep = buffer.indexOf('\n\n');
        while (sep >= 0) {
          const block = buffer.slice(0, sep);
          buffer = buffer.slice(sep + 2);
          const parsed = parseSSEBlock(block);
          if (parsed?.data) {
            try {
              const ev = JSON.parse(parsed.data) as TimelineEvent;
              onEvent(ev);
            } catch {
              // ignore malformed payload; keep the stream alive
            }
          }
          sep = buffer.indexOf('\n\n');
        }
      }
    } catch (err) {
      if ((err as { name?: string })?.name === 'AbortError') {
        onClose?.('aborted');
      } else {
        onClose?.((err as Error).message);
      }
    }
  })();

  return {
    abort: () => controller.abort(),
  };
}
