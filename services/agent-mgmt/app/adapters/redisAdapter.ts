import Redis from 'ioredis';
import { v4 as uuidv4 } from 'uuid';
import { config } from '../config';
import { logger } from '../utils/logger';

const STREAM_MAXLEN = 10000;
const SOURCE_SERVICE = 'agent-mgmt';
const SCHEMA_VERSION = '1';

class RedisAdapter {
  private client: Redis | null = null;

  connect(): void {
    this.client = new Redis(config.REDIS_URL, {
      retryStrategy: (times) => Math.min(times * 100, 3000),
      maxRetriesPerRequest: 3,
      enableReadyCheck: true,
      lazyConnect: false,
    });

    this.client.on('connect', () => {
      logger.info('Redis connected', 'adapter', { url: config.REDIS_URL });
    });

    this.client.on('error', (err: Error) => {
      logger.error('Redis error', 'adapter', { error: err.message });
    });

    this.client.on('reconnecting', () => {
      logger.warn('Redis reconnecting', 'adapter');
    });
  }

  getClient(): Redis {
    if (!this.client) {
      throw new Error('Redis client not initialized — call connect() first');
    }
    return this.client;
  }

  async publish(stream: string, message: Record<string, unknown>): Promise<string> {
    const client = this.getClient();
    const enriched = {
      trace_id: (message.trace_id as string) || uuidv4(),
      source_service: SOURCE_SERVICE,
      timestamp: new Date().toISOString(),
      schema_version: SCHEMA_VERSION,
      ...message,
    };

    // XADD <stream> MAXLEN ~ <maxlen> * <fields...>
    const fields: string[] = [];
    for (const [key, value] of Object.entries(enriched)) {
      fields.push(key, typeof value === 'string' ? value : JSON.stringify(value));
    }

    const id = await client.xadd(stream, 'MAXLEN', '~', STREAM_MAXLEN, '*', ...fields);
    logger.debug(`Published to stream ${stream}`, 'adapter', {
      stream,
      message_id: id,
      trace_id: enriched.trace_id,
    });
    return id as string;
  }

  async healthCheck(): Promise<boolean> {
    try {
      const result = await this.getClient().ping();
      return result === 'PONG';
    } catch {
      return false;
    }
  }

  async close(): Promise<void> {
    if (this.client) {
      await this.client.quit();
      this.client = null;
      logger.info('Redis connection closed', 'adapter');
    }
  }
}

export const redisAdapter = new RedisAdapter();
