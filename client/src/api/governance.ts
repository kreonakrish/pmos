import { useQuery } from '@tanstack/react-query';
import apiClient from './axios';

export interface TraceListEntry {
  trace_id: string;
  conversation_id: string | null;
  last_message_at: string | null;
  user_request: string | null;
  assistant_response: string | null;
  avg_score: number | null;
  tool_call_count?: number;
  avg_tool_latency_ms?: number | null;
}

export interface TimelineEntry {
  layer:
    | 'USER_MESSAGE'
    | 'TASK_NODE'
    | 'PIPELINE_STEP'
    | 'TOOL_CALL'
    | 'SCORING'
    | 'RL_FEEDBACK'
    | 'AGENT_INTERACTION'
    | 'ASSISTANT_RESPONSE';
  ts: string | null;
  title: string;
  detail: unknown;
  score?: number | null;
  source: string;
  ref_id?: string | null;
  agent?: string | null;
  agent_id?: number | null;
  status?: string | null;
  latency_ms?: number | null;
}

export interface TraceSummary {
  trace_id: string;
  conversation_id: string | null;
  graph_id: string | null;
  session_id: string | null;
  final_score: number | null;
  n_messages: number;
  n_tool_calls: number;
  n_pipeline_steps: number;
  n_task_nodes: number;
  n_score_records: number;
  n_rl_feedback: number;
  n_interactions: number;
  tools_used: string[];
  agents_involved: string[];
}

export interface TraceDetail {
  trace_id: string;
  summary: TraceSummary;
  conversation: Record<string, unknown> | null;
  messages: Array<Record<string, unknown>>;
  graph: Record<string, unknown> | null;
  task_nodes: Array<Record<string, unknown>>;
  task_edges: Array<{ type: string; from_id: string; to_id: string }>;
  pipeline_steps: Array<Record<string, unknown>>;
  tool_calls: Array<Record<string, unknown>>;
  score_history: Array<Record<string, unknown>>;
  rl_feedback: Array<Record<string, unknown>>;
  interactions: Array<Record<string, unknown>>;
  episodes: Array<Record<string, unknown>>;
  timeline: TimelineEntry[];
}

export function useGovernanceTraces(limit = 50) {
  return useQuery<{ traces: TraceListEntry[]; trace_id: string }>({
    queryKey: ['governance-traces', limit],
    queryFn: async () => {
      const { data } = await apiClient.get(`/v1/governance/traces`, {
        params: { limit },
      });
      return data;
    },
    staleTime: 30_000,
  });
}

export function useGovernanceTrace(traceId: string | null) {
  return useQuery<TraceDetail>({
    queryKey: ['governance-trace', traceId],
    queryFn: async () => {
      const { data } = await apiClient.get(`/v1/governance/traces/${traceId}`);
      return data;
    },
    enabled: !!traceId,
    staleTime: 30_000,
  });
}
