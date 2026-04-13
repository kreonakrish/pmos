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
  // AUTH_PASSWORD retained only for transitional compatibility; real auth is per-user.
  AUTH_PASSWORD: z.string().optional(),
  JWT_EXPIRY_SEC: z.coerce.number().optional().default(86400),
  // MySQL (auth DB)
  MYSQL_HOST: z.string().default('localhost'),
  MYSQL_PORT: z.coerce.number().default(3306),
  MYSQL_DB: z.string().default('pmos'),
  MYSQL_USER: z.string().default('root'),
  MYSQL_PASSWORD: z.string().min(1, 'MYSQL_PASSWORD must be set in .env'),
  MYSQL_POOL_SIZE: z.coerce.number().default(10),
  // Initial seed passwords (only used on first boot / when user does not yet exist)
  SUPER_ADMIN_USERNAME: z.string().default('superadmin'),
  SUPER_ADMIN_EMAIL: z.string().default('superadmin@pmos.local'),
  SUPER_ADMIN_PASSWORD: z.string().min(8, 'SUPER_ADMIN_PASSWORD is required on first boot'),
  KRISH_USERNAME: z.string().default('krish'),
  KRISH_EMAIL: z.string().default('krish@pmos.local'),
  KRISH_INITIAL_PASSWORD: z.string().min(8, 'KRISH_INITIAL_PASSWORD is required on first boot'),
  BCRYPT_ROUNDS: z.coerce.number().default(12),
  LOG_LEVEL: z.enum(['DEBUG', 'INFO', 'WARN', 'ERROR']).default('INFO'),
  NODE_ENV: z.enum(['development', 'production', 'test']).default('development'),
  DOWNSTREAM_TIMEOUT_MS: z.coerce.number().default(3000),
  LOG_SOURCE: z.enum(['docker', 'k8s', 'loki']).default('docker'),
  DOCKER_SOCKET_PATH: z.string().default('/var/run/docker.sock'),
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
