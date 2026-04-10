import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import apiClient from '@/api/axios';
import type { Agent } from '@/types';

export function useAgents() {
  return useQuery<Agent[]>({
    queryKey: ['agents'],
    queryFn: async () => {
      const { data } = await apiClient.get('/v1/agents');
      return data.agents ?? data.items ?? data;
    },
  });
}

export interface CreateAgentPayload {
  name: string;
  description?: string;
  foundation_model: string;
  is_primary?: boolean;
}

export function useCreateAgent() {
  const qc = useQueryClient();
  return useMutation<Agent, Error, CreateAgentPayload>({
    mutationFn: async (payload) => {
      const { data } = await apiClient.post('/v1/agents', payload);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agents'] });
    },
  });
}

export interface UpdateAgentPayload {
  name?: string;
  description?: string;
  foundation_model?: string;
  status?: string;
  is_primary?: boolean;
  meta_capable?: boolean;
  memory_seed?: string;
  reasoning_seed?: string;
}

export function useUpdateAgent() {
  const qc = useQueryClient();
  return useMutation<Agent, Error, { agentId: string; payload: UpdateAgentPayload }>({
    mutationFn: async ({ agentId, payload }) => {
      const { data } = await apiClient.put(`/v1/agents/${agentId}`, payload);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agents'] });
    },
  });
}

export function useDeleteAgent() {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: async (agentId) => {
      await apiClient.delete(`/v1/agents/${agentId}`);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agents'] });
    },
  });
}

// ---------------------------------------------------------------------------
// Agent Tools (assignment persistence)
// ---------------------------------------------------------------------------

export interface AgentToolResponse {
  tool_id: string;
  tool_name: string;
  tool_type: string;
  tool_status: string;
  permission_level: string;
}

export function useAgentTools(agentId: string | undefined) {
  return useQuery<AgentToolResponse[]>({
    queryKey: ['agent-tools', agentId],
    queryFn: async () => {
      const { data } = await apiClient.get(`/v1/agents/${agentId}/tools`);
      return data.tools ?? [];
    },
    enabled: !!agentId,
    staleTime: 30_000,
  });
}

export function useSyncAgentTools() {
  const qc = useQueryClient();
  return useMutation<void, Error, { agentId: string; toolIds: string[] }>({
    mutationFn: async ({ agentId, toolIds }) => {
      await apiClient.put(`/v1/agents/${agentId}/tools`, { tool_ids: toolIds });
    },
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['agent-tools', vars.agentId] });
    },
  });
}

// ---------------------------------------------------------------------------
// Agent Test (LLM execution)
// ---------------------------------------------------------------------------

export interface AgentTestRequest {
  prompt: string;
  system_prompt?: string;
  provider?: string;
  model?: string;
  temperature?: number;
  max_tokens?: number;
}

export interface AgentTestResponse {
  success: boolean;
  response?: string;
  model?: string;
  latency_ms: number;
  tokens_used?: number;
  error?: string;
  trace_id: string;
}

export function useTestAgent() {
  return useMutation<AgentTestResponse, Error, { agentId: string; payload: AgentTestRequest }>({
    mutationFn: async ({ agentId, payload }) => {
      const { data } = await apiClient.post(`/v1/agents/${agentId}/test`, payload);
      return data;
    },
  });
}

// ---------------------------------------------------------------------------
// Agent Execution History
// ---------------------------------------------------------------------------

export interface AgentExecutionResponse {
  execution_id: string;
  agent_id: string;
  agent_name: string | null;
  prompt: string;
  response: string | null;
  model: string | null;
  temperature: number | null;
  latency_ms: number;
  tokens_used: number | null;
  status: 'success' | 'failure';
  error_message: string | null;
  tool_calls: unknown | null;
  team_id: string | null;
  team_name: string | null;
  conversation_id: string | null;
  source: string | null;
  trace_id: string | null;
  created_at: string;
}

export function useAgentExecutionHistory(agentId: string | undefined) {
  return useQuery<{ executions: AgentExecutionResponse[]; total: number }>({
    queryKey: ['agent-executions', agentId],
    queryFn: async () => {
      const { data } = await apiClient.get(`/v1/agents/${agentId}/executions?limit=100`);
      return data;
    },
    enabled: !!agentId,
    staleTime: 10_000,
    refetchInterval: 15_000,
  });
}
