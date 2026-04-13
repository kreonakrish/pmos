import apiClient from '@/api/axios';

export interface LogLine {
  ts: string;
  service: string;
  level: 'DEBUG' | 'INFO' | 'WARN' | 'ERROR' | 'UNKNOWN';
  trace_id?: string;
  msg: string;
  raw: string;
}

export async function listLogServices(): Promise<string[]> {
  const { data } = await apiClient.get<{ services: string[] }>('/v1/logs/services');
  return data.services;
}

export interface TailParams {
  service: string;
  tail?: number;
  level?: string;
  traceId?: string;
}

/**
 * Open an SSE-style live tail over fetch (so we can send the JWT in the
 * Authorization header; native EventSource can't). Calls onLine for each
 * parsed log line. Returns an AbortController to stop the stream.
 */
export function openLiveTail(
  params: TailParams,
  onLine: (line: LogLine) => void,
  onError?: (err: unknown) => void,
): AbortController {
  const controller = new AbortController();
  const token = localStorage.getItem('pmos_token') ?? '';
  const qs = new URLSearchParams({
    service: params.service,
    follow: '1',
    tail: String(params.tail ?? 200),
  });
  if (params.level) qs.set('level', params.level);
  if (params.traceId) qs.set('trace_id', params.traceId);

  const runtimeCfg = (window as unknown as { __PMOS_CONFIG__?: { apiBaseUrl?: string } })
    .__PMOS_CONFIG__ || {};
  const base = runtimeCfg.apiBaseUrl || import.meta.env.VITE_API_BASE_URL || '';

  (async () => {
    try {
      const res = await fetch(`${base}/v1/logs/tail?${qs}`, {
        headers: { Authorization: `Bearer ${token}`, Accept: 'text/event-stream' },
        signal: controller.signal,
      });
      if (!res.ok || !res.body) throw new Error(`tail failed: ${res.status}`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });

        // SSE frames are separated by a blank line.
        const frames = buf.split('\n\n');
        buf = frames.pop() ?? '';
        for (const frame of frames) {
          const dataLine = frame.split('\n').find((l) => l.startsWith('data:'));
          if (!dataLine) continue;
          try {
            const payload = JSON.parse(dataLine.slice(5).trim()) as LogLine;
            onLine(payload);
          } catch {
            /* skip malformed frame */
          }
        }
      }
    } catch (err) {
      if ((err as { name?: string })?.name !== 'AbortError') onError?.(err);
    }
  })();

  return controller;
}
