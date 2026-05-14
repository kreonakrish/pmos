import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import apiClient from './axios';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
export type FinOpsPeriod = '24h' | '7d' | '30d' | '90d' | 'all';
export type FinOpsGroupBy =
  | 'service'
  | 'team'
  | 'agent'
  | 'model'
  | 'provider'
  | 'user'
  | 'conversation';

export interface FinOpsTotals {
  n_calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost_usd: number;
  avg_latency_ms: number;
  n_conversations: number;
  n_users: number;
  n_agents: number;
}

export interface FinOpsTrendPoint {
  d: string; // ISO date
  cost_usd: number;
  tokens: number;
  n_calls: number;
}

export interface FinOpsBreakdownRow {
  key: string;
  label: string;
  cost_usd: number;
  tokens: number;
  prompt_tokens: number;
  completion_tokens: number;
  n_calls: number;
  avg_latency_ms: number | null;
  first_seen: string | null;
  last_seen: string | null;
}

export interface FinOpsAgentRow {
  agent_id: string;
  agent_name: string;
  foundation_model: string | null;
  cost_usd: number;
  tokens: number;
  n_calls: number;
}

export interface FinOpsModelRow {
  provider: string;
  model: string;
  cost_usd: number;
  tokens: number;
  n_calls: number;
}

export interface FinOpsUserRow {
  user_id: string;
  n_conversations: number;
  cost_usd: number;
  tokens: number;
  n_calls: number;
}

export interface FinOpsConversationRow {
  conversation_id: string;
  user_id: string | null;
  team_id: string | null;
  title: string | null;
  n_calls: number;
  tokens: number;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
  first_call_ts: string | null;
  last_call_ts: string | null;
  sample_trace_id: string | null;
}

export interface FinOpsCallRow {
  call_id: string;
  ts: string;
  service_name: string;
  trace_id: string | null;
  agent_id: string | null;
  agent_name: string | null;
  provider: string;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost_usd: number;
  latency_ms: number | null;
  finish_reason: string | null;
  had_tool_calls: number;
  error: string | null;
}

export interface FinOpsConversationDetail {
  trace_id: string;
  conversation_id: string;
  summary: {
    n_calls: number;
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
    cost_usd: number;
    n_services: number;
    n_agents: number;
  };
  by_service: Array<{ service_name: string; cost_usd: number; n_calls: number }>;
  by_agent: Array<{ agent_id: string; agent_name: string; cost_usd: number; n_calls: number }>;
  calls: FinOpsCallRow[];
}

export interface FinOpsSummary {
  trace_id: string;
  period: FinOpsPeriod;
  totals: FinOpsTotals;
  daily_trend: FinOpsTrendPoint[];
  by_provider: Array<{ provider: string; cost_usd: number; tokens: number; n_calls: number }>;
  by_service: Array<{ service_name: string; cost_usd: number; tokens: number; n_calls: number }>;
  top_agents: FinOpsAgentRow[];
  top_models: FinOpsModelRow[];
  top_users: FinOpsUserRow[];
}

export interface PricingRow {
  pricing_id: number;
  provider: string;
  model: string;
  input_per_mtok: number;
  output_per_mtok: number;
  effective_from: string;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface PricingUpsertBody {
  provider: string;
  model: string;
  input_per_mtok: number;
  output_per_mtok: number;
  effective_from?: string;
  notes?: string;
}

export interface WhatIfResult {
  trace_id: string;
  agent_id: string;
  agent_name: string | null;
  period: FinOpsPeriod;
  n_calls_basis: number;
  prompt_tokens_basis: number;
  completion_tokens_basis: number;
  current: {
    model: string | null;
    provider: string | null;
    input_per_mtok: number | null;
    output_per_mtok: number | null;
    actual_cost_usd: number;
    projected_cost_usd: number;
  };
  candidate: {
    model: string;
    provider: string;
    input_per_mtok: number;
    output_per_mtok: number;
    projected_cost_usd: number;
  };
  savings_usd: number;
  savings_pct: number | null;
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------
export function useFinOpsSummary(period: FinOpsPeriod = '7d') {
  return useQuery<FinOpsSummary>({
    queryKey: ['finops', 'summary', period],
    queryFn: async () =>
      (await apiClient.get('/v1/finops/summary', { params: { period } })).data,
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
}

export interface FinOpsBreakdownFilters {
  service_name?: string;
  team_id?: string;
  agent_id?: string;
  user_id?: string;
  conversation_id?: string;
  provider?: string;
  model?: string;
}

export function useFinOpsBreakdown(
  group_by: FinOpsGroupBy,
  period: FinOpsPeriod = '7d',
  filters: FinOpsBreakdownFilters = {},
  limit = 100,
) {
  return useQuery<{ rows: FinOpsBreakdownRow[]; count: number; group_by: FinOpsGroupBy }>({
    queryKey: ['finops', 'breakdown', group_by, period, filters, limit],
    queryFn: async () =>
      (await apiClient.get('/v1/finops/breakdown', {
        params: { group_by, period, limit, ...filters },
      })).data,
    staleTime: 15_000,
  });
}

export function useFinOpsConversations(
  period: FinOpsPeriod = '7d',
  order_by: 'cost' | 'tokens' | 'calls' = 'cost',
  user_id?: string,
  limit = 100,
) {
  return useQuery<{ rows: FinOpsConversationRow[]; count: number }>({
    queryKey: ['finops', 'conversations', period, order_by, user_id ?? '', limit],
    queryFn: async () =>
      (await apiClient.get('/v1/finops/conversations', {
        params: { period, order_by, limit, ...(user_id ? { user_id } : {}) },
      })).data,
    staleTime: 30_000,
  });
}

export function useFinOpsConversationDetail(conversation_id: string | null) {
  return useQuery<FinOpsConversationDetail>({
    queryKey: ['finops', 'conversation', conversation_id],
    queryFn: async () =>
      (await apiClient.get(`/v1/finops/conversations/${conversation_id}`)).data,
    enabled: !!conversation_id,
    staleTime: 30_000,
  });
}

export function useFinOpsPricing() {
  return useQuery<{ rows: PricingRow[]; count: number }>({
    queryKey: ['finops', 'pricing'],
    queryFn: async () => (await apiClient.get('/v1/finops/pricing')).data,
    staleTime: 60_000,
  });
}

export function useUpsertPricing() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      pricing_id,
      body,
    }: {
      pricing_id?: number;
      body: PricingUpsertBody;
    }) => {
      if (pricing_id) {
        return (await apiClient.put(`/v1/finops/pricing/${pricing_id}`, body)).data;
      }
      return (await apiClient.post('/v1/finops/pricing', body)).data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['finops', 'pricing'] }),
  });
}

export function useFinOpsWhatIf(
  agent_id: string | null,
  candidate_model: string | null,
  period: FinOpsPeriod = '30d',
) {
  return useQuery<WhatIfResult>({
    queryKey: ['finops', 'whatif', agent_id, candidate_model, period],
    queryFn: async () =>
      (await apiClient.get('/v1/finops/whatif', {
        params: { agent_id, candidate_model, period },
      })).data,
    enabled: !!agent_id && !!candidate_model,
    staleTime: 30_000,
  });
}
