import { useQuery, useMutation } from '@tanstack/react-query';
import apiClient from './axios';

export interface ScoreHistoryEntry {
  id: number;
  agent_id: number;
  task_id?: string;
  context_type: string;
  score: number;
  factors: Record<string, number>;
  band_low: number;
  band_high: number;
  within_band: boolean;
  created_at: string;
}

export interface ScoringWeightsResponse {
  agent_id: number;
  weights: Record<string, number>;
  context_types: string[];
}

export interface ScoreBandResponse {
  low: number;
  high: number;
}

export interface EvaluateScorePayload {
  agent_id: number;
  task_id: string;
  context_type: string;
  response_text: string;
  used_knowledge: boolean;
  latency_ms: number;
  tool_calls: string[];
}

export interface EvaluateScoreResult {
  score: number;
  band: { low: number; high: number };
  recommendation: 'proceed' | 'course_correct' | 'escalate' | 'halt';
  factors: Record<string, number>;
  trace_id: string;
}

export function useScoreHistory(
  agentId: number,
  options?: { enabled?: boolean },
) {
  return useQuery<ScoreHistoryEntry[]>({
    queryKey: ['score-history', agentId],
    queryFn: async () => {
      const { data } = await apiClient.get(`/v1/scoring/history/${agentId}`);
      return data.history ?? data.items ?? data;
    },
    enabled: (options?.enabled ?? true) && agentId > 0,
    staleTime: 60_000,
  });
}

export function useScoringWeights(
  agentId: number,
  options?: { enabled?: boolean },
) {
  return useQuery<ScoringWeightsResponse>({
    queryKey: ['scoring-weights', agentId],
    queryFn: async () => {
      const { data } = await apiClient.get(`/v1/scoring/weights/${agentId}`);
      return data;
    },
    enabled: (options?.enabled ?? true) && agentId > 0,
    staleTime: 60_000,
  });
}

export function useScoreBand(agentId: number, contextType: string) {
  return useQuery<ScoreBandResponse>({
    queryKey: ['score-band', agentId, contextType],
    queryFn: async () => {
      const { data } = await apiClient.post('/v1/scoring/band', {
        agent_id: agentId,
        context_type: contextType,
      });
      return data;
    },
    enabled: agentId > 0 && !!contextType,
    staleTime: 60_000,
  });
}

export function useEvaluateScore() {
  return useMutation<EvaluateScoreResult, Error, EvaluateScorePayload>({
    mutationFn: async (payload) => {
      const { data } = await apiClient.post('/v1/scoring/evaluate', payload);
      return data;
    },
  });
}
