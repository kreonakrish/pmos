export type RetryStrategy = 'LINEAR' | 'EXPONENTIAL' | 'FIBONACCI';

export interface Team {
  id?: number;
  team_id: string;
  name: string;
  description?: string;
  use_smart_workflow: boolean;
  accuracy_threshold: number;
  max_retries: number;
  retry_strategy: RetryStrategy;
  created_at?: string;
  updated_at?: string;
  agents?: TeamAgent[];
}

export interface TeamAgent {
  team_id: string;
  agent_id: string;
  priority: number;
  role?: string;
  accuracy: number;
  success_rate: number;
  assigned_at?: string;
  parent_agent_id?: string | null;
  execution_mode?: string;
  criticality?: string;
  timeout_seconds?: number;
  fallback_agent_id?: string | null;
}

export interface CreateTeamRequest {
  name: string;
  description?: string;
  use_smart_workflow?: boolean;
  accuracy_threshold?: number;
  max_retries?: number;
  retry_strategy?: RetryStrategy;
}

export interface UpdateTeamRequest {
  name?: string;
  description?: string;
  use_smart_workflow?: boolean;
  accuracy_threshold?: number;
  max_retries?: number;
  retry_strategy?: RetryStrategy;
}

export interface AddAgentToTeamRequest {
  agent_id: string;
  priority?: number;
  role?: string;
  parent_agent_id?: string | null;
  execution_mode?: string;
  criticality?: string;
  timeout_seconds?: number;
  fallback_agent_id?: string | null;
}

export interface TeamAgentHierarchy {
  agent_id: string;
  priority: number;
  role?: string;
  parent_agent_id?: string | null;
  execution_mode?: string;
  criticality?: string;
  timeout_seconds?: number;
  fallback_agent_id?: string | null;
}
