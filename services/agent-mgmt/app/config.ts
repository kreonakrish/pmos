import { z } from 'zod';
import dotenv from 'dotenv';

dotenv.config();

const schema = z.object({
  AGENT_MGMT_PORT: z.coerce.number().default(4001),
  MYSQL_HOST: z.string().default('localhost'),
  MYSQL_PORT: z.coerce.number().default(3306),
  MYSQL_DB: z.string().default('pmos'),
  MYSQL_USER: z.string().default('root'),
  MYSQL_PASSWORD: z.string(),
  MYSQL_POOL_SIZE: z.coerce.number().default(20),
  REDIS_URL: z.string().default('redis://localhost:6379'),
  ORCHESTRATOR_URL: z.string().default('http://pmos-orchestrator:8000'),
  MEMORY_SERVICE_URL: z.string().default('http://pmos-memory:8001'),
  SCORING_SERVICE_URL: z.string().default('http://pmos-scoring:8003'),
  TOOL_HEALTH_INTERVAL_SEC: z.coerce.number().default(60),
  LOG_LEVEL: z.enum(['DEBUG', 'INFO', 'WARN', 'ERROR']).default('INFO'),
  NODE_ENV: z.string().default('development'),
  NEO4J_URI: z.string().default(''),
  NEO4J_USER: z.string().default('neo4j'),
  NEO4J_PASSWORD: z.string().default(''),
  NEO4J_DATABASE: z.string().default('neo4j'),
});

function parseConfig() {
  const result = schema.safeParse(process.env);
  if (!result.success) {
    const errors = result.error.flatten().fieldErrors;
    const missing = Object.entries(errors)
      .map(([k, v]) => `${k}: ${v?.join(', ')}`)
      .join('; ');
    throw new Error(`[agent-mgmt] Configuration error — ${missing}`);
  }
  return result.data;
}

export const config = parseConfig();
export type Config = typeof config;
