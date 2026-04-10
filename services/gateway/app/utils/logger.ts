interface LogRecord {
  level: string;
  message: string;
  service: 'gateway';
  timestamp: string;
  trace_id?: string;
  span_id?: string;
  layer?: string;
  duration_ms?: number;
  [key: string]: unknown;
}

type LogLevel = 'DEBUG' | 'INFO' | 'WARN' | 'ERROR';

const LOG_LEVEL_PRIORITY: Record<LogLevel, number> = {
  DEBUG: 0,
  INFO: 1,
  WARN: 2,
  ERROR: 3,
};

function getCurrentLogLevel(): LogLevel {
  const level = process.env['LOG_LEVEL'] as LogLevel | undefined;
  return level && LOG_LEVEL_PRIORITY[level] !== undefined ? level : 'INFO';
}

function shouldLog(level: LogLevel): boolean {
  return LOG_LEVEL_PRIORITY[level] >= LOG_LEVEL_PRIORITY[getCurrentLogLevel()];
}

function emit(level: LogLevel, message: string, extra: Partial<LogRecord> = {}): void {
  if (!shouldLog(level)) return;
  const record: LogRecord = {
    level,
    message,
    service: 'gateway',
    timestamp: new Date().toISOString(),
    ...extra,
  };
  // stdout only — collected by Docker/k8s log aggregator
  console.log(JSON.stringify(record));
}

export const logger = {
  debug(message: string, extra?: Partial<LogRecord>): void {
    emit('DEBUG', message, extra);
  },
  info(message: string, extra?: Partial<LogRecord>): void {
    emit('INFO', message, extra);
  },
  warn(message: string, extra?: Partial<LogRecord>): void {
    emit('WARN', message, extra);
  },
  error(message: string, extra?: Partial<LogRecord>): void {
    emit('ERROR', message, extra);
  },
};

export type { LogRecord };
