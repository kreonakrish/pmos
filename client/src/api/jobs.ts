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
  pattern_decision?: PatternDecisionTrace | null;
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

  /** Phase 22 — bid as capability contract. Present when the agent's bid
   *  emitted the structured shape (coverage + plan). Null when bidding was
   *  skipped (schema-meta override) or fell back to the legacy shape. */
  bid_plan_format?: string | null;
  bid_plan_parsed?: BidPlanStep[] | null;
  bid_coverage_parsed?: BidCoverage | null;
}

export interface BidPlanStep {
  tool: string;
  kind: string;       // 'sql' | 'cypher' | 'api' | 'python'
  sketch: string;
  expected_columns: string[];
  purpose: string;
}

export interface BidCoverage {
  answerable: string[];
  not_answerable: string[];
  reason_missing: string;
}

/** One candidate row in the pattern-dispatcher decision trace. */
export interface PatternCandidateScore {
  name: string;
  priority: number;
  score: number;
  threshold: number;
  accepted: boolean;
  evidence: string[];
  explanation: string;
  error: string | null;
  duration_ms: number;
}

/** Translator state captured at dispatch time — light summary, not the
 *  full TranslationResult. */
export interface PatternTranslatorSummary {
  intent?: string | null;
  domain?: string | null;
  fallback_used?: boolean | null;
  n_canonical_entities?: number;
  n_dataset_bindings?: number;
  n_matched_reports?: number;
  schema_meta_column?: string;
}

/** Full decision-trace payload the orchestrator stamps on TaskGraph and
 *  the UI renders in the Pattern Decision tab. */
export interface PatternDecisionTrace {
  candidates: PatternCandidateScore[];
  winner: string | null;
  duration_ms: number;
  translator_summary: PatternTranslatorSummary;
  /** True while the dispatcher is in shadow mode (Phase 1) — the trace
   *  was recorded but the legacy gates drove routing. */
  shadow: boolean;
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
