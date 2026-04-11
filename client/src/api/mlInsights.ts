import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import apiClient from './axios';

// ---------------------------------------------------------------------------
// Bandits
// ---------------------------------------------------------------------------
export interface BanditSummary {
  trace_id: string;
  prior: { mean: number; strength: number };
  min_pulls_for_live: number;
  decisions: {
    total: number;
    rewarded: number;
    shadow: number;
    live: number;
    exploration: number;
    fallback: number;
    disagreements: number;
  };
  state: {
    rows: number;
    agents_tracked: number;
    contexts_tracked: number;
    max_pulls: number;
    total_pulls: number;
  };
  readiness: Array<{
    context_bucket: string;
    arms: number;
    min_pulls: number;
    max_pulls: number;
    avg_pulls: number;
    state: 'READY' | 'WARMING' | 'COLD';
  }>;
}

export interface BanditStateRow {
  agent_id: string;
  agent_name: string | null;
  context_bucket: string;
  alpha: number;
  beta: number;
  pulls: number;
  total_reward: number;
  posterior_mean: number;
  credible_low: number;
  credible_high: number;
  ready: boolean;
  last_updated: string | null;
  created_at: string | null;
}

export interface BanditDecisionRow {
  decision_id: string;
  trace_id: string | null;
  session_id: string | null;
  graph_id: string | null;
  node_id: string | null;
  context_bucket: string;
  mode: 'SHADOW' | 'LIVE' | 'EXPLORATION' | 'FALLBACK';
  selected_agent_id: string;
  selected_agent_name: string | null;
  bandit_pick_agent_id: string | null;
  bandit_pick_agent_name: string | null;
  candidate_agents: Array<{
    agent_id: string;
    agent_name: string;
    sampled_theta: number;
    alpha: number;
    beta: number;
    pulls: number;
  }>;
  reward: number | null;
  reward_recorded_at: string | null;
  created_at: string;
  disagreement: boolean;
}

export interface BanditConvergencePoint {
  i: number;
  ts: string | null;
  reward: number;
  alpha: number;
  beta: number;
  posterior_mean: number;
}

export function useBanditSummary() {
  return useQuery<BanditSummary>({
    queryKey: ['ml', 'bandits', 'summary'],
    queryFn: async () => (await apiClient.get('/v1/ml/bandits/summary')).data,
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
}

export function useBanditState(contextBucket?: string, limit = 200) {
  return useQuery<{ state: BanditStateRow[]; count: number }>({
    queryKey: ['ml', 'bandits', 'state', contextBucket ?? '', limit],
    queryFn: async () =>
      (
        await apiClient.get('/v1/ml/bandits/state', {
          params: { context_bucket: contextBucket, limit },
        })
      ).data,
    staleTime: 15_000,
  });
}

export function useBanditDecisions(opts?: {
  mode?: string;
  disagreementsOnly?: boolean;
  limit?: number;
}) {
  return useQuery<{ decisions: BanditDecisionRow[]; count: number }>({
    queryKey: [
      'ml',
      'bandits',
      'decisions',
      opts?.mode ?? '',
      !!opts?.disagreementsOnly,
      opts?.limit ?? 100,
    ],
    queryFn: async () =>
      (
        await apiClient.get('/v1/ml/bandits/decisions', {
          params: {
            mode: opts?.mode,
            disagreements_only: opts?.disagreementsOnly ? 'true' : undefined,
            limit: opts?.limit ?? 100,
          },
        })
      ).data,
    staleTime: 15_000,
  });
}

export function useBanditConvergence(
  agentId: string | null,
  contextBucket: string | null,
) {
  return useQuery<{ series: BanditConvergencePoint[] }>({
    queryKey: ['ml', 'bandits', 'convergence', agentId ?? '', contextBucket ?? ''],
    queryFn: async () =>
      (
        await apiClient.get('/v1/ml/bandits/convergence', {
          params: { agent_id: agentId, context_bucket: contextBucket },
        })
      ).data,
    enabled: !!agentId && !!contextBucket,
    staleTime: 15_000,
  });
}

// ---------------------------------------------------------------------------
// Embeddings
// ---------------------------------------------------------------------------
export interface EmbeddingSummary {
  trace_id: string;
  total: number;
  graphs: number;
  first_computed: string | null;
  last_computed: string | null;
  dim: number;
  algorithm: string;
  by_node_type: Array<{ node_type: string; n: number }>;
}

export interface EmbeddingProjectionPoint {
  node_id: string;
  graph_id: string | null;
  node_type: string;
  x: number;
  y: number;
}

export interface EmbeddingSimilarResponse {
  reference: {
    node_id: string;
    graph_id: string | null;
    node_type: string | null;
  };
  neighbors: Array<{
    node_id: string;
    graph_id: string | null;
    node_type: string | null;
    similarity: number;
  }>;
}

export function useEmbeddingSummary() {
  return useQuery<EmbeddingSummary>({
    queryKey: ['ml', 'embeddings', 'summary'],
    queryFn: async () => (await apiClient.get('/v1/ml/embeddings/summary')).data,
    staleTime: 60_000,
  });
}

export function useEmbeddingProjection(
  limit = 500,
  nodeType?: string,
) {
  return useQuery<{ points: EmbeddingProjectionPoint[]; count: number }>({
    queryKey: ['ml', 'embeddings', 'projection', limit, nodeType ?? ''],
    queryFn: async () =>
      (
        await apiClient.get('/v1/ml/embeddings/projection', {
          params: { limit, node_type: nodeType },
        })
      ).data,
    staleTime: 60_000,
  });
}

export function useEmbeddingSimilar(nodeId: string | null, k = 10) {
  return useQuery<EmbeddingSimilarResponse>({
    queryKey: ['ml', 'embeddings', 'similar', nodeId ?? '', k],
    queryFn: async () =>
      (
        await apiClient.get('/v1/ml/embeddings/similar', {
          params: { node_id: nodeId, k },
        })
      ).data,
    enabled: !!nodeId && nodeId.length > 0,
    staleTime: 30_000,
  });
}

// ---------------------------------------------------------------------------
// Learned Scorer (1B)
// ---------------------------------------------------------------------------
export interface LearnedScorerSummary {
  trace_id: string;
  active_model: {
    model_version: string;
    algorithm: string;
    n_features: number;
    n_samples: number;
    n_positive: number;
    n_synthetic: number;
    n_real: number;
    train_accuracy: number | null;
    val_accuracy: number | null;
    val_auc: number | null;
    weights_path: string;
    notes: string | null;
    is_active: boolean;
    created_at: string;
    feature_names: string[];
  } | null;
  models: Array<{
    model_version: string;
    algorithm: string;
    n_samples: number;
    val_accuracy: number | null;
    val_auc: number | null;
    is_active: boolean;
    created_at: string;
  }>;
  prediction_stats: {
    total: number;
    labeled: number;
    avg_learned: number;
    avg_heuristic: number;
    mae_vs_heuristic: number;
    positive_labels: number;
    negative_labels: number;
  };
  w7_learned_quality: {
    value: number;
    auto_adjust: boolean | null;
    updated_at: string | null;
    mode: 'LIVE' | 'SHADOW';
  };
}

export interface LearnedScorerPrediction {
  prediction_id: string;
  model_version: string | null;
  trace_id: string | null;
  session_id: string | null;
  graph_id: string | null;
  node_id: string | null;
  agent_id: string | null;
  agent_name: string | null;
  heuristic_score: number | null;
  learned_score: number;
  user_feedback: 'positive' | 'negative' | null;
  features: Record<string, number>;
  delta?: number;
  created_at: string;
}

export function useLearnedScorerSummary() {
  return useQuery<LearnedScorerSummary>({
    queryKey: ['ml', 'learned-scorer', 'summary'],
    queryFn: async () =>
      (await apiClient.get('/v1/ml/learned-scorer/summary')).data,
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
}

export function useLearnedScorerPredictions(limit = 100, labeledOnly = false) {
  return useQuery<{ predictions: LearnedScorerPrediction[]; count: number }>({
    queryKey: ['ml', 'learned-scorer', 'predictions', limit, labeledOnly],
    queryFn: async () =>
      (
        await apiClient.get('/v1/ml/learned-scorer/predictions', {
          params: { limit, labeled_only: labeledOnly ? 'true' : undefined },
        })
      ).data,
    staleTime: 30_000,
  });
}

// ---------------------------------------------------------------------------
// SOP Discovery (2D)
// ---------------------------------------------------------------------------
export interface SOPProposal {
  proposal_id: string;
  cluster_size: number;
  avg_score: number | null;
  best_agent_id: string | null;
  best_agent_name: string | null;
  summary: string;
  sample_messages: string[];
  keywords: string[];
  status: 'PENDING' | 'PROMOTED' | 'REJECTED';
  promoted_sop_id: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string;
}

export function useSOPProposals(status?: string, limit = 50) {
  return useQuery<{ proposals: SOPProposal[]; count: number }>({
    queryKey: ['ml', 'sops', 'proposals', status ?? '', limit],
    queryFn: async () =>
      (
        await apiClient.get('/v1/ml/sops/proposals', {
          params: { status, limit },
        })
      ).data,
    staleTime: 15_000,
  });
}

export function usePromoteSOP() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (proposalId: string) => {
      const { data } = await apiClient.post(
        `/v1/ml/sops/proposals/${proposalId}/promote`,
        {},
      );
      return data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['ml', 'sops'] }),
  });
}

export function useRejectSOP() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (proposalId: string) => {
      const { data } = await apiClient.post(
        `/v1/ml/sops/proposals/${proposalId}/reject`,
        {},
      );
      return data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['ml', 'sops'] }),
  });
}
