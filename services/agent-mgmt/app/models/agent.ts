export type AgentStatus = 'IDLE' | 'ACTIVE' | 'BUSY' | 'DEGRADED' | 'DEPRECATED';

export interface Agent {
  id?: number;
  agent_id: string;
  name: string;
  description?: string;
  foundation_model: string;
  status: AgentStatus;
  accuracy_rate: number;
  success_rate: number;
  total_executions: number;
  health_score: number;
  meta_capable: boolean;
  is_primary: boolean;
  memory_seed?: string | null;
  reasoning_seed?: string | null;
  degraded_at?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface AgentTool {
  agent_id: string;
  tool_id: string;
  permission_level: 'READ' | 'WRITE' | 'ADMIN';
  assigned_at?: string;
}

export interface CreateAgentRequest {
  name: string;
  description?: string;
  foundation_model?: string;
  meta_capable?: boolean;
  is_primary?: boolean;
}

export interface UpdateAgentRequest {
  name?: string;
  description?: string;
  foundation_model?: string;
  status?: AgentStatus;
  meta_capable?: boolean;
  is_primary?: boolean;
  accuracy_rate?: number;
  success_rate?: number;
  health_score?: number;
  memory_seed?: string;
  reasoning_seed?: string;
}

export interface AssignToolRequest {
  tool_id: string;
  permission_level?: 'READ' | 'WRITE' | 'ADMIN';
}

export interface AgentFilter {
  status?: AgentStatus;
  meta_capable?: boolean;
}
