export type ToolType = 'DATABASE' | 'API' | 'GITHUB' | 'PYTHON' | 'WEBSERVICE' | 'FILE' | 'VECTOR' | 'GRAPH';
export type ToolStatus = 'ACTIVE' | 'DEGRADED' | 'OFFLINE';
export type AuthMethod = 'NONE' | 'API_KEY' | 'BEARER' | 'BASIC' | 'OAUTH2';

export interface Tool {
  id?: number;
  tool_id: string;
  name: string;
  description?: string;
  tool_type: ToolType;
  hostname?: string;
  endpoint?: string;
  auth_method: AuthMethod;
  auth_config?: Record<string, unknown> | null;
  status: ToolStatus;
  avg_latency_ms: number;
  success_rate: number;
  last_health_check?: string | null;
  is_dynamic: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface CreateToolRequest {
  name: string;
  description?: string;
  tool_type: ToolType;
  hostname?: string;
  endpoint?: string;
  auth_method?: AuthMethod;
  auth_config?: Record<string, unknown>;
  is_dynamic?: boolean;
}

export interface UpdateToolRequest {
  name?: string;
  description?: string;
  tool_type?: ToolType;
  hostname?: string;
  endpoint?: string;
  auth_method?: AuthMethod;
  auth_config?: Record<string, unknown>;
  status?: ToolStatus;
  avg_latency_ms?: number;
  success_rate?: number;
}
