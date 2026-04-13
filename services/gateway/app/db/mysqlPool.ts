import mysql from 'mysql2/promise';
import { config } from '../config';
import { logger } from '../utils/logger';

let pool: mysql.Pool | null = null;

export function getPool(): mysql.Pool {
  if (!pool) {
    pool = mysql.createPool({
      host: config.MYSQL_HOST,
      port: config.MYSQL_PORT,
      database: config.MYSQL_DB,
      user: config.MYSQL_USER,
      password: config.MYSQL_PASSWORD,
      connectionLimit: config.MYSQL_POOL_SIZE,
      waitForConnections: true,
      queueLimit: 0,
      enableKeepAlive: true,
    });
    logger.info('mysql_pool_created', { host: config.MYSQL_HOST, db: config.MYSQL_DB });
  }
  return pool;
}

export async function closePool(): Promise<void> {
  if (pool) {
    await pool.end();
    pool = null;
  }
}
