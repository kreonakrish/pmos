import axios from 'axios';
import mysql from 'mysql2/promise';
import neo4j, { Driver, auth as neo4jAuth } from 'neo4j-driver';
import { config as appConfig } from '../config';
import { logger } from '../utils/logger';

export interface ToolTestRequest {
  tool_id: string;
  tool_type: string;
  config: Record<string, unknown>;
  inputs: Record<string, unknown>;
}

export interface ToolTestResult {
  success: boolean;
  output: unknown;
  error?: string;
  latency_ms: number;
  tool_type: string;
  trace_id: string;
}

const TOOL_TEST_TIMEOUT = 30_000;

// ---------------------------------------------------------------------------
// DATABASE executor — connects to the configured DB and runs a query
// ---------------------------------------------------------------------------
async function executeDatabaseTool(
  config: Record<string, unknown>,
  inputs: Record<string, unknown>,
): Promise<unknown> {
  const query = (inputs.query as string) || (config.query_template as string);
  if (!query) throw new Error('No query provided. Pass { "query": "SELECT ..." } in inputs.');

  const maxRows = Number(config.max_rows ?? inputs.max_rows ?? 100);

  // Parse connection string or use individual fields
  let connStr = (config.connection_string as string) || '';
  // Normalize localhost to host.docker.internal when running inside Docker
  connStr = connStr.replace(/localhost|127\.0\.0\.1/g, 'host.docker.internal');

  // Defaults from the service's own MySQL config (fallback when conn string has no creds)
  let host = appConfig.MYSQL_HOST;
  let port = appConfig.MYSQL_PORT;
  let user = appConfig.MYSQL_USER;
  let password = appConfig.MYSQL_PASSWORD;
  let database = '';

  if (connStr) {
    // mysql://user:pass@host:port/database  OR  mysql://host:port/database (no creds)
    const match = connStr.match(/^mysql:\/\/(?:([^:@]+)(?::([^@]*))?@)?([^:/]+)(?::(\d+))?(?:\/(.+))?$/);
    if (match) {
      if (match[1]) user = match[1];
      if (match[2]) password = match[2];
      host = match[3] || host;
      port = match[4] ? parseInt(match[4], 10) : port;
      database = match[5] || database;
    }
  }

  // Allow explicit overrides from config/inputs
  host = (config.host as string) || host;
  port = Number(config.port ?? port);
  user = (config.user as string) || user;
  password = (config.password as string) || password;
  database = (config.database as string) || (inputs.database as string) || database;

  const conn = await mysql.createConnection({ host, port, user, password, database });
  try {
    // Wrap with LIMIT if not already present and it's a SELECT
    let safeQuery = query.trim();
    const isSelect = /^\s*SELECT/i.test(safeQuery);
    if (isSelect && !/LIMIT\s+\d+/i.test(safeQuery)) {
      safeQuery = safeQuery.replace(/;?\s*$/, ` LIMIT ${maxRows}`);
    }

    // Bind parameters if provided
    const params = (inputs.params as unknown[]) || [];
    const [rows, fields] = await conn.query(safeQuery, params);

    const columns = Array.isArray(fields)
      ? fields.map((f: { name: string }) => f.name)
      : [];

    const rowArray = Array.isArray(rows) ? rows : [rows];
    return {
      columns,
      rows: rowArray.slice(0, maxRows),
      row_count: rowArray.length,
      query: safeQuery,
    };
  } finally {
    await conn.end();
  }
}

// ---------------------------------------------------------------------------
// API executor — makes an HTTP request using the tool's config
// ---------------------------------------------------------------------------
async function executeApiTool(
  config: Record<string, unknown>,
  inputs: Record<string, unknown>,
): Promise<unknown> {
  const baseUrl = (config.base_url as string) || (inputs.url as string);
  if (!baseUrl) throw new Error('No base_url configured. Set it in tool config or pass { "url": "..." }.');

  const method = ((config.http_method as string) || (inputs.method as string) || 'GET').toUpperCase();

  // Build headers
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  const configHeaders = config.headers as Array<{ key: string; value: string }> | undefined;
  if (Array.isArray(configHeaders)) {
    for (const h of configHeaders) {
      if (h.key && h.value) headers[h.key] = h.value;
    }
  }
  // Merge input headers
  const inputHeaders = inputs.headers as Record<string, string> | undefined;
  if (inputHeaders && typeof inputHeaders === 'object') {
    Object.assign(headers, inputHeaders);
  }

  // Auth
  const authType = (config.auth_type as string) || 'none';
  const authConfig = (config.auth_config as Record<string, string>) || {};
  if (authType === 'api_key' && authConfig.header_name && authConfig.api_key) {
    headers[authConfig.header_name] = authConfig.api_key;
  } else if (authType === 'bearer' && authConfig.token) {
    headers['Authorization'] = `Bearer ${authConfig.token}`;
  } else if (authType === 'basic' && authConfig.username && authConfig.password) {
    const encoded = Buffer.from(`${authConfig.username}:${authConfig.password}`).toString('base64');
    headers['Authorization'] = `Basic ${encoded}`;
  }

  // Body — merge template with inputs
  let body: unknown = undefined;
  if (['POST', 'PUT', 'PATCH'].includes(method)) {
    const template = config.body_template as string | undefined;
    if (template) {
      try {
        body = JSON.parse(template);
        if (typeof body === 'object' && body && inputs.body && typeof inputs.body === 'object') {
          body = { ...(body as Record<string, unknown>), ...(inputs.body as Record<string, unknown>) };
        }
      } catch {
        body = inputs.body ?? template;
      }
    } else {
      body = inputs.body ?? inputs;
    }
  }

  // Query params
  const queryParams = (inputs.query_params as Record<string, string>) || (inputs.params as Record<string, string>) || undefined;

  const resp = await axios({
    method: method as 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH',
    url: baseUrl,
    headers,
    data: body,
    params: queryParams,
    timeout: TOOL_TEST_TIMEOUT,
    validateStatus: () => true,
  });

  return {
    status: resp.status,
    status_text: resp.statusText,
    headers: resp.headers,
    data: resp.data,
  };
}

// ---------------------------------------------------------------------------
// GITHUB executor — calls GitHub API based on action type
// ---------------------------------------------------------------------------
async function executeGitHubTool(
  config: Record<string, unknown>,
  inputs: Record<string, unknown>,
): Promise<unknown> {
  const repoUrl = (config.repo_url as string) || '';
  const pat = (config.pat as string) || '';
  const action = (config.action as string) || (inputs.action as string) || 'search_code';
  const actionConfig = (config.action_config as Record<string, string>) || {};

  const headers: Record<string, string> = {
    Accept: 'application/vnd.github.v3+json',
    'User-Agent': 'PMOS-ToolTest',
  };
  if (pat) headers['Authorization'] = `Bearer ${pat}`;

  // Extract owner/repo from URL
  const repoMatch = repoUrl.match(/github\.com\/([^/]+)\/([^/]+)/);
  const owner = repoMatch?.[1] || (inputs.owner as string) || '';
  const repo = (repoMatch?.[2] || (inputs.repo as string) || '').replace(/\.git$/, '');

  switch (action) {
    case 'read_file': {
      const filePath = actionConfig.file_path || (inputs.file_path as string) || 'README.md';
      const branch = (config.branch as string) || 'main';
      const resp = await axios.get(
        `https://api.github.com/repos/${owner}/${repo}/contents/${filePath}?ref=${branch}`,
        { headers, timeout: TOOL_TEST_TIMEOUT, validateStatus: () => true },
      );
      if (resp.data?.content) {
        resp.data.decoded_content = Buffer.from(resp.data.content, 'base64').toString('utf-8');
      }
      return { status: resp.status, data: resp.data };
    }
    case 'list_prs': {
      const state = actionConfig.state || 'open';
      const maxResults = actionConfig.max_results || '10';
      const resp = await axios.get(
        `https://api.github.com/repos/${owner}/${repo}/pulls?state=${state}&per_page=${maxResults}`,
        { headers, timeout: TOOL_TEST_TIMEOUT, validateStatus: () => true },
      );
      return { status: resp.status, count: Array.isArray(resp.data) ? resp.data.length : 0, data: resp.data };
    }
    case 'create_issue': {
      const title = actionConfig.title_template || (inputs.title as string) || 'Test Issue from PMOS';
      const labels = actionConfig.labels ? actionConfig.labels.split(',').map((l: string) => l.trim()) : [];
      const body = (inputs.body as string) || 'Created via PMOS tool test.';
      const resp = await axios.post(
        `https://api.github.com/repos/${owner}/${repo}/issues`,
        { title, body, labels },
        { headers, timeout: TOOL_TEST_TIMEOUT, validateStatus: () => true },
      );
      return { status: resp.status, data: resp.data };
    }
    case 'search_code': {
      const query = actionConfig.search_query || (inputs.query as string) || '';
      const searchQ = owner && repo ? `${query}+repo:${owner}/${repo}` : query;
      const resp = await axios.get(
        `https://api.github.com/search/code?q=${encodeURIComponent(searchQ)}&per_page=10`,
        { headers, timeout: TOOL_TEST_TIMEOUT, validateStatus: () => true },
      );
      return { status: resp.status, total_count: resp.data?.total_count, data: resp.data };
    }
    default: {
      const searchQuery = (inputs.query as string) || 'fastapi';
      const resp = await axios.get(
        `https://api.github.com/search/repositories?q=${encodeURIComponent(searchQuery)}&per_page=5`,
        { headers, timeout: TOOL_TEST_TIMEOUT, validateStatus: () => true },
      );
      return { status: resp.status, total_count: resp.data?.total_count, items: resp.data?.items?.map((i: Record<string, unknown>) => ({ name: i.full_name, stars: i.stargazers_count, description: i.description })) };
    }
  }
}

// ---------------------------------------------------------------------------
// PYTHON executor — proxies to orchestrator's sandbox endpoint (Python 3.11)
// ---------------------------------------------------------------------------
async function executePythonTool(
  config: Record<string, unknown>,
  inputs: Record<string, unknown>,
): Promise<unknown> {
  const code = (config.code as string) || (inputs.code as string);
  if (!code) throw new Error('No Python code provided. Set code in tool config or pass { "code": "..." }.');

  const orchestratorUrl = appConfig.ORCHESTRATOR_URL;
  const resp = await axios.post(
    `${orchestratorUrl}/v1/sandbox/execute-python`,
    { code, inputs, timeout: 30 },
    { timeout: TOOL_TEST_TIMEOUT, validateStatus: () => true },
  );

  const data = resp.data;
  if (!data.success) {
    throw new Error(data.error || 'Python execution failed');
  }
  return data.output;
}

// ---------------------------------------------------------------------------
// WEBSERVICE executor — similar to API but with simpler defaults
// ---------------------------------------------------------------------------
async function executeWebServiceTool(
  config: Record<string, unknown>,
  inputs: Record<string, unknown>,
): Promise<unknown> {
  // WebService reuses the API executor with minor adjustments
  return executeApiTool(config, inputs);
}

// ---------------------------------------------------------------------------
// GRAPH executor — connects to Neo4j and runs Cypher queries
// ---------------------------------------------------------------------------
async function executeGraphTool(
  config: Record<string, unknown>,
  inputs: Record<string, unknown>,
): Promise<unknown> {
  const query = (inputs.query as string) || (config.query_template as string);
  if (!query) throw new Error('No Cypher query provided. Pass { "query": "MATCH ..." } in inputs.');

  const maxRows = Number(config.max_rows ?? inputs.max_rows ?? 100);

  // Connection from config or env
  let uri = (config.connection_string as string) || (config.uri as string) || '';
  const user = (config.user as string) || (config.username as string) || 'neo4j';
  const password = (config.password as string) || '';

  if (!uri) throw new Error('No Neo4j URI configured. Set connection_string or uri in tool config.');

  let driver: Driver | null = null;
  try {
    driver = neo4j.driver(uri, neo4jAuth.basic(user, password));

    const session = driver.session({ database: (config.database as string) || undefined });
    try {
      const params = (inputs.params as Record<string, unknown>) || {};
      const result = await session.run(query, params);

      const records = result.records.slice(0, maxRows).map((record) => {
        const obj: Record<string, unknown> = {};
        for (const key of record.keys as string[]) {
          const val = record.get(key);
          obj[key] = neo4jValueToPlain(val);
        }
        return obj;
      });

      return {
        records,
        record_count: result.records.length,
        returned_count: records.length,
        keys: result.records.length > 0 ? (result.records[0].keys as string[]) : [],
        query,
      };
    } finally {
      await session.close();
    }
  } finally {
    if (driver) await driver.close();
  }
}

/**
 * Convert Neo4j native values (integers, nodes, relationships, paths) to plain JS objects.
 */
function neo4jValueToPlain(val: unknown): unknown {
  if (val === null || val === undefined) return val;

  // Neo4j Integer
  if (neo4j.isInt(val)) {
    const n = val as { toNumber: () => number };
    return n.toNumber();
  }

  // Node
  if (typeof val === 'object' && val !== null && 'labels' in val && 'properties' in val) {
    const node = val as { labels: string[]; properties: Record<string, unknown>; identity: unknown };
    const props: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(node.properties)) {
      props[k] = neo4jValueToPlain(v);
    }
    return { _labels: node.labels, ...props };
  }

  // Relationship
  if (typeof val === 'object' && val !== null && 'type' in val && 'properties' in val && 'start' in val && 'end' in val) {
    const rel = val as { type: string; properties: Record<string, unknown> };
    const props: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(rel.properties)) {
      props[k] = neo4jValueToPlain(v);
    }
    return { _type: rel.type, ...props };
  }

  // Array
  if (Array.isArray(val)) {
    return val.map(neo4jValueToPlain);
  }

  // Plain object
  if (typeof val === 'object' && val !== null) {
    const obj: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(val as Record<string, unknown>)) {
      obj[k] = neo4jValueToPlain(v);
    }
    return obj;
  }

  return val;
}

// ---------------------------------------------------------------------------
// Main dispatch
// ---------------------------------------------------------------------------
export async function executeToolTest(
  request: ToolTestRequest,
  traceId: string,
): Promise<ToolTestResult> {
  const start = Date.now();
  const toolType = request.tool_type.toUpperCase();

  logger.info('tool_test_start', 'service', {
    trace_id: traceId,
    tool_id: request.tool_id,
    tool_type: toolType,
  });

  try {
    let output: unknown;

    switch (toolType) {
      case 'DATABASE':
        output = await executeDatabaseTool(request.config, request.inputs);
        break;
      case 'API':
        output = await executeApiTool(request.config, request.inputs);
        break;
      case 'GITHUB':
        output = await executeGitHubTool(request.config, request.inputs);
        break;
      case 'PYTHON':
        output = await executePythonTool(request.config, request.inputs);
        break;
      case 'WEBSERVICE':
        output = await executeWebServiceTool(request.config, request.inputs);
        break;
      case 'GRAPH':
        output = await executeGraphTool(request.config, request.inputs);
        break;
      default:
        throw new Error(`Unsupported tool type: ${toolType}`);
    }

    const latency = Date.now() - start;
    logger.info('tool_test_success', 'service', {
      trace_id: traceId,
      tool_id: request.tool_id,
      tool_type: toolType,
      latency_ms: latency,
    });

    return {
      success: true,
      output,
      latency_ms: latency,
      tool_type: toolType,
      trace_id: traceId,
    };
  } catch (err: unknown) {
    const latency = Date.now() - start;
    const e = err as Record<string, unknown>;
    const error = (e?.sqlMessage as string) || (e?.message as string) || (e?.code as string) || String(err);

    logger.error('tool_test_failed', 'service', {
      trace_id: traceId,
      tool_id: request.tool_id,
      tool_type: toolType,
      error,
      latency_ms: latency,
    });

    return {
      success: false,
      output: null,
      error,
      latency_ms: latency,
      tool_type: toolType,
      trace_id: traceId,
    };
  }
}
