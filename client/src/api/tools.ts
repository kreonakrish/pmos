import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import apiClient from './axios';

export interface ToolResponse {
  id: number;
  tool_id: string;
  name: string;
  description?: string;
  tool_type: string;
  hostname?: string;
  endpoint?: string;
  auth_method?: string;
  auth_config?: Record<string, unknown>;
  status: 'ACTIVE' | 'DEGRADED' | 'OFFLINE';
  avg_latency_ms: number;
  success_rate: number;
  last_health_check?: string;
  is_dynamic: boolean;
}

export interface CapabilityResponse {
  id: number;
  capability_type: 'TOOL' | 'SKILL' | 'AGENT';
  capability_id: string;
  name: string;
  description?: string;
  source: 'STATIC' | 'DYNAMIC';
  validation_score?: number;
  is_active: boolean;
  usage_count: number;
  created_at: string;
}

export interface CreateToolPayload {
  name: string;
  description?: string;
  tool_type: string;
  hostname?: string;
}

export function useTools() {
  return useQuery<ToolResponse[]>({
    queryKey: ['tools'],
    queryFn: async () => {
      const { data } = await apiClient.get('/v1/tools');
      return data.tools ?? data.items ?? data;
    },
    staleTime: 60_000,
  });
}

export function useCapabilities() {
  return useQuery<CapabilityResponse[]>({
    queryKey: ['capabilities'],
    queryFn: async () => {
      const { data } = await apiClient.get('/v1/capabilities');
      return data.capabilities ?? data.items ?? data;
    },
    staleTime: 60_000,
  });
}

export function useCreateTool() {
  const qc = useQueryClient();
  return useMutation<ToolResponse, Error, CreateToolPayload>({
    mutationFn: async (payload) => {
      const { data } = await apiClient.post('/v1/tools', {
        ...payload,
        tool_type: payload.tool_type.toUpperCase(),
      });
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tools'] });
    },
  });
}

export interface UpdateToolPayload {
  name?: string;
  description?: string;
  tool_type?: string;
  hostname?: string;
  status?: string;
}

export function useUpdateTool() {
  const qc = useQueryClient();
  return useMutation<ToolResponse, Error, { toolId: string; payload: UpdateToolPayload }>({
    mutationFn: async ({ toolId, payload }) => {
      const body = payload.tool_type
        ? { ...payload, tool_type: payload.tool_type.toUpperCase() }
        : payload;
      const { data } = await apiClient.put(`/v1/tools/${toolId}`, body);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tools'] });
    },
  });
}

export interface ToolExecutionResponse {
  execution_id: string;
  tool_id: string;
  tool_type: string;
  status: 'success' | 'failure';
  inputs: Record<string, unknown> | null;
  output: unknown | null;
  error_message: string | null;
  latency_ms: number;
  trace_id: string | null;
  agent_id: string | null;
  agent_name: string | null;
  team_id: string | null;
  team_name: string | null;
  conversation_id: string | null;
  source: string | null;
  created_at: string;
}

export function useToolExecutionHistory(toolId: string | undefined) {
  return useQuery<{ executions: ToolExecutionResponse[]; total: number }>({
    queryKey: ['tool-executions', toolId],
    queryFn: async () => {
      const { data } = await apiClient.get(`/v1/tools/${toolId}/executions?limit=100`);
      return data;
    },
    enabled: !!toolId,
    staleTime: 10_000,
    refetchInterval: 15_000,
  });
}

export function useDeleteTool() {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: async (toolId) => {
      await apiClient.delete(`/v1/tools/${toolId}`);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tools'] });
    },
  });
}
