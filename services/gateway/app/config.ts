import { z } from 'zod';
import dotenv from 'dotenv';

dotenv.config();

const configSchema = z.object({
  GATEWAY_PORT: z.coerce.number().default(4000),
  JWT_SECRET: z.string().min(32, 'JWT_SECRET must be at least 32 characters'),
  API_KEY: z.string().optional(),
  RATE_LIMIT_RPM: z.coerce.number().default(120),
  ORCHESTRATOR_URL: z.string().url('ORCHESTRATOR_URL must be a valid URL'),
  AGENT_MGMT_URL: z.string().url('AGENT_MGMT_URL must be a valid URL'),
  RAG_SERVICE_URL: z.string().url('RAG_SERVICE_URL must be a valid URL'),
  SCORING_SERVICE_URL: z.string().url().optional().default('http://localhost:8003'),
  MEMORY_SERVICE_URL: z.string().url().optional().default('http://localhost:8001'),
  META_ASSEMBLY_URL: z.string().url().optional().default('http://localhost:8004'),
  REDIS_URL: z.string().default('redis://localhost:6379'),
  AUTH_PASSWORD: z.string().optional().default('pmos2024'),
  JWT_EXPIRY_SEC: z.coerce.number().optional().default(86400),
  LOG_LEVEL: z.enum(['DEBUG', 'INFO', 'WARN', 'ERROR']).default('INFO'),
  NODE_ENV: z.enum(['development', 'production', 'test']).default('development'),
  DOWNSTREAM_TIMEOUT_MS: z.coerce.number().default(3000),
});

function loadConfig() {
  const result = configSchema.safeParse(process.env);
  if (!result.success) {
    const errors = result.error.errors.map((e) => `  ${e.path.join('.')}: ${e.message}`).join('\n');
    throw new Error(`Configuration validation failed:\n${errors}`);
  }
  return result.data;
}

export const config = loadConfig();
export type Config = typeof config;
