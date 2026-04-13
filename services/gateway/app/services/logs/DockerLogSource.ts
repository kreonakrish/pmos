import http from 'http';
import { LogSource, LogLine, TailOptions, parseLogLine } from './LogSource';

// Logical PMOS service name → Docker container name.
const SERVICE_CONTAINER_MAP: Record<string, string> = {
  gateway: 'pmos-gateway',
  'agent-mgmt': 'pmos-agent-mgmt',
  orchestrator: 'pmos-orchestrator',
  memory: 'pmos-memory',
  rag: 'pmos-rag',
  scoring: 'pmos-scoring',
  'meta-assembly': 'pmos-meta-assembly',
  client: 'pmos-client',
};

export class DockerLogSource implements LogSource {
  constructor(private readonly socketPath = '/var/run/docker.sock') {}

  async listServices(): Promise<string[]> {
    return Object.keys(SERVICE_CONTAINER_MAP);
  }

  async *tail(opts: TailOptions): AsyncIterable<LogLine> {
    const container = SERVICE_CONTAINER_MAP[opts.service];
    if (!container) throw new Error(`unknown service: ${opts.service}`);

    const qs = new URLSearchParams({
      stdout: '1',
      stderr: '1',
      follow: opts.follow ? '1' : '0',
      tail: String(opts.tail ?? 200),
      timestamps: '0',
    });

    const req = http.request({
      socketPath: this.socketPath,
      path: `/containers/${container}/logs?${qs}`,
      method: 'GET',
    });
    req.end();

    if (opts.signal) {
      opts.signal.addEventListener('abort', () => req.destroy(), { once: true });
    }

    const res: http.IncomingMessage = await new Promise((resolve, reject) => {
      req.once('response', resolve);
      req.once('error', reject);
    });

    // Docker multiplexes stdout/stderr with an 8-byte header per frame when
    // the container has no TTY. Strip frame headers and yield line-by-line.
    let buf = Buffer.alloc(0);
    let lineBuf = '';

    for await (const chunk of res) {
      buf = Buffer.concat([buf, chunk as Buffer]);

      while (buf.length >= 8) {
        const size = buf.readUInt32BE(4);
        if (buf.length < 8 + size) break;
        const payload = buf.subarray(8, 8 + size).toString('utf8');
        buf = buf.subarray(8 + size);

        lineBuf += payload;
        const parts = lineBuf.split('\n');
        lineBuf = parts.pop() ?? '';

        for (const line of parts) {
          if (!line) continue;
          const parsed = parseLogLine(opts.service, line);
          if (opts.level && parsed.level !== opts.level) continue;
          if (opts.traceId && parsed.trace_id !== opts.traceId) continue;
          yield parsed;
        }
      }
    }

    if (lineBuf.trim()) {
      yield parseLogLine(opts.service, lineBuf);
    }
  }
}
