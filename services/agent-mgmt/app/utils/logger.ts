const SERVICE_NAME = 'agent-mgmt';

type LogLevel = 'DEBUG' | 'INFO' | 'WARN' | 'ERROR';

interface LogRecord {
  level: LogLevel;
  message: string;
  service: string;
  layer: string;
  timestamp: string;
  trace_id?: string;
  span_id?: string;
  duration_ms?: number;
  [key: string]: unknown;
}

function log(level: LogLevel, message: string, layer: string, extra: Record<string, unknown> = {}): void {
  const record: LogRecord = {
    level,
    message,
    service: SERVICE_NAME,
    layer,
    timestamp: new Date().toISOString(),
    ...extra,
  };
  // stdout only — collected by Docker/k8s log aggregator
  process.stdout.write(JSON.stringify(record) + '\n');
}

export const logger = {
  debug: (message: string, layer: string, extra?: Record<string, unknown>) =>
    log('DEBUG', message, layer, extra),
  info: (message: string, layer: string, extra?: Record<string, unknown>) =>
    log('INFO', message, layer, extra),
  warn: (message: string, layer: string, extra?: Record<string, unknown>) =>
    log('WARN', message, layer, extra),
  error: (message: string, layer: string, extra?: Record<string, unknown>) =>
    log('ERROR', message, layer, extra),
};
