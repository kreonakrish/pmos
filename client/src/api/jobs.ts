import { useQuery } from '@tanstack/react-query';
import apiClient from './axios';

export interface Job {
  graph_id: string;
  session_id: string;
  conversation_id: string;
  user_request: string;
  status: string;
  current_iteration: number;
  created_at: string;
  updated_at: string;
  recovery_note?: string;
  total_nodes: number;
  success_nodes: number;
  failed_nodes: number;
  pending_nodes: number;
  avg_score: number | null;
  agents_used: string[];
}

export interface JobDetail extends Job {
  nodes: JobNode[];
  edges: Array<{ from: string; to: string; type: string }>;
}

export interface JobNode {
  node_id: string;
  description: string;
  status: string;
  depth: number;
  score: number | null;
  assigned_agent_name: string | null;
  bid_confidence: number | null;
  execution_time_ms: number | null;
  created_at: string;
  updated_at: string;
}

export function useJobs(limit = 50) {
  return useQuery<Job[]>({
    queryKey: ['jobs', limit],
    queryFn: async () => {
      const { data } = await apiClient.get(`/v1/jobs?limit=${limit}`);
      return data.jobs ?? [];
    },
    refetchInterval: 10_000,
  });
}

export function useJobDetail(graphId: string | null) {
  return useQuery<JobDetail>({
    queryKey: ['jobs', graphId],
    queryFn: async () => {
      const { data } = await apiClient.get(`/v1/jobs/${graphId}`);
      return data;
    },
    enabled: !!graphId,
    refetchInterval: 5_000,
  });
}
