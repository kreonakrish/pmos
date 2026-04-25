import neo4j, { Driver, auth as neo4jAuth, Session } from 'neo4j-driver';
import { config } from '../config';
import { logger } from '../utils/logger';

class Neo4jAdapter {
  private driver: Driver | null = null;

  connect(): void {
    if (!config.NEO4J_URI) {
      logger.warn('NEO4J_URI not set — Neo4j adapter disabled', 'adapter');
      return;
    }
    this.driver = neo4j.driver(
      config.NEO4J_URI,
      neo4jAuth.basic(config.NEO4J_USER, config.NEO4J_PASSWORD),
    );
    logger.info('Neo4j driver initialised', 'adapter', { target: config.NEO4J_URI });
  }

  isReady(): boolean {
    return this.driver !== null;
  }

  async run<T = Record<string, unknown>>(
    cypher: string,
    params: Record<string, unknown> = {},
  ): Promise<T[]> {
    if (!this.driver) return [];
    const session: Session = this.driver.session({ database: config.NEO4J_DATABASE });
    try {
      const result = await session.run(cypher, params);
      return result.records.map((rec) => {
        const obj: Record<string, unknown> = {};
        for (const key of rec.keys as string[]) {
          obj[key] = rec.get(key);
        }
        return obj as T;
      });
    } finally {
      await session.close();
    }
  }

  async close(): Promise<void> {
    if (this.driver) {
      await this.driver.close();
      this.driver = null;
    }
  }
}

export const neo4jAdapter = new Neo4jAdapter();
