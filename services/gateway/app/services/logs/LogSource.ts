export interface LogLine {
  ts: string;
  service: string;
  level: 'DEBUG' | 'INFO' | 'WARN' | 'ERROR' | 'UNKNOWN';
  trace_id?: string;
  msg: string;
  raw: string;
}

export interface TailOptions {
  service: string;
  tail?: number;
  follow?: boolean;
  level?: LogLine['level'];
  traceId?: string;
  signal?: AbortSignal;
}

export interface LogSource {
  listServices(): Promise<string[]>;
  tail(opts: TailOptions): AsyncIterable<LogLine>;
}

export function parseLogLine(service: string, raw: string): LogLine {
  const trimmed = raw.trim();
  try {
    const j = JSON.parse(trimmed);
    const levelRaw = (j.level ?? j.severity ?? 'UNKNOWN').toString().toUpperCase();
    const level = (['DEBUG', 'INFO', 'WARN', 'ERROR'].includes(levelRaw)
      ? levelRaw
      : 'UNKNOWN') as LogLine['level'];
    return {
      ts: j.ts ?? j.timestamp ?? new Date().toISOString(),
      service,
      level,
      trace_id: j.trace_id ?? j.traceId,
      msg: j.msg ?? j.message ?? j.event ?? trimmed,
      raw: trimmed,
    };
  } catch {
    return {
      ts: new Date().toISOString(),
      service,
      level: 'UNKNOWN',
      msg: trimmed,
      raw: trimmed,
    };
  }
}
