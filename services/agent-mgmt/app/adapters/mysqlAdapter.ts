import mysql from 'mysql2/promise';
import { config } from '../config';
import { logger } from '../utils/logger';

export type QueryResult<T = mysql.RowDataPacket> = T[];

class MySQLAdapter {
  private pool: mysql.Pool | null = null;

  private createPool(): mysql.Pool {
    return mysql.createPool({
      host: config.MYSQL_HOST,
      port: config.MYSQL_PORT,
      database: config.MYSQL_DB,
      user: config.MYSQL_USER,
      password: config.MYSQL_PASSWORD,
      connectionLimit: config.MYSQL_POOL_SIZE,
      waitForConnections: true,
      queueLimit: 0,
      enableKeepAlive: true,
      keepAliveInitialDelay: 0,
      charset: 'utf8mb4',
    });
  }

  async connect(): Promise<void> {
    const maxAttempts = 5;
    let attempt = 0;

    while (attempt < maxAttempts) {
      try {
        this.pool = this.createPool();
        // Test connection
        const conn = await this.pool.getConnection();
        conn.release();
        logger.info('MySQL pool connected', 'adapter', { host: config.MYSQL_HOST, port: config.MYSQL_PORT });
        return;
      } catch (err: unknown) {
        attempt++;
        const error = err as NodeJS.ErrnoException;
        if (error.code === 'ECONNREFUSED' && attempt < maxAttempts) {
          const delayMs = attempt * 2000;
          logger.warn(`MySQL connection refused, retrying in ${delayMs}ms`, 'adapter', {
            attempt,
            max_attempts: maxAttempts,
          });
          await new Promise<void>((resolve) => setTimeout(resolve, delayMs));
        } else {
          logger.error('MySQL connection failed', 'adapter', { error: error.message, attempt });
          throw err;
        }
      }
    }
  }

  getPool(): mysql.Pool {
    if (!this.pool) {
      throw new Error('MySQL pool not initialized — call connect() first');
    }
    return this.pool;
  }

  async query<T extends mysql.RowDataPacket>(
    sql: string,
    params?: unknown[]
  ): Promise<T[]> {
    const pool = this.getPool();
    const [rows] = await pool.query<T[]>(sql, params);
    return rows;
  }

  async execute<T extends mysql.RowDataPacket>(
    sql: string,
    params?: unknown[]
  ): Promise<[mysql.ResultSetHeader, mysql.FieldPacket[]]> {
    const pool = this.getPool();
    const result = await pool.execute(sql, params as any[]);
    return result as [mysql.ResultSetHeader, mysql.FieldPacket[]];
  }

  async getConnection(): Promise<mysql.PoolConnection> {
    return this.getPool().getConnection();
  }

  async transaction<T>(fn: (conn: mysql.PoolConnection) => Promise<T>): Promise<T> {
    const conn = await this.getConnection();
    await conn.beginTransaction();
    try {
      const result = await fn(conn);
      await conn.commit();
      return result;
    } catch (err) {
      await conn.rollback();
      throw err;
    } finally {
      conn.release();
    }
  }

  async healthCheck(): Promise<boolean> {
    try {
      await this.query('SELECT 1');
      return true;
    } catch {
      return false;
    }
  }

  async close(): Promise<void> {
    if (this.pool) {
      await this.pool.end();
      this.pool = null;
      logger.info('MySQL pool closed', 'adapter');
    }
  }
}

export const mysqlAdapter = new MySQLAdapter();
