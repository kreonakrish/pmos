import { useMutation } from '@tanstack/react-query';
import apiClient from './axios';

// ---------------------------------------------------------------------------
// Types — match backend response from POST /v1/translate
// ---------------------------------------------------------------------------
export interface CanonicalEntity {
  name: string;
  domain: string;
  fq_name: string;
  confidence: number;
}

export interface CanonicalRelationship {
  type?: string;
  from?: string;
  to?: string;
  confidence?: number;
}

export interface DatasetBinding {
  asset_fq_name: string;
  columns: string[];
  source_uri?: string | null;
}

export interface OntologySubgraphNode {
  id: string;
  label: string;
  properties?: Array<{ name: string; type: string }>;
}

export interface OntologySubgraphEdge {
  type: string;
  from: string | null;
  to: string | null;
  properties?: Array<{ name: string; type: string }>;
}

export interface OntologySubgraph {
  nodes: OntologySubgraphNode[];
  edges: OntologySubgraphEdge[];
}

// Ext2 — deterministic Report short-circuit. The translator surfaces any
// ``Report`` nodes whose attributes overlap the user's question so the chat
// pipeline can run them as-is instead of synthesizing fresh SQL.
export type ReportSystem = 'SSRS' | 'COGNOS' | 'POWERBI' | 'TABLEAU' | 'CUSTOM';
export type ReportCommandType = 'SQL' | 'MDX' | 'DAX';

export interface ReportDataset {
  dataset_id: string;
  name: string;
  command: string;
  command_type: ReportCommandType;
  source_uri: string | null;
  source_name: string | null;
}

export interface MatchedReport {
  report_id: string;
  name: string;
  description: string;
  system: ReportSystem;
  owner_team: string | null;
  datasets: ReportDataset[];
  uses_attributes: string[];
  score: number;
  why: string;
}

export interface TranslationResult {
  intent: string;
  domain: string;
  canonical_entities: CanonicalEntity[];
  relationships: CanonicalRelationship[];
  dataset_bindings: DatasetBinding[];
  domain_subtasks: string[];
  used_ontology_subgraph: OntologySubgraph;
  ontology_versions: string[];
  fallback_used: boolean;
  trace_id: string;
  // Phase F4 — clarification + ambiguity gate
  clarification_needed?: boolean;
  clarification_question?: string | null;
  ambiguous_options?: Array<Record<string, unknown>>;
  auditor_issue_id?: string | null;
  auditor_issue_kind?: string | null;
  // Ext2 — deterministic Report matches (empty list when none).
  matched_reports: MatchedReport[];
}

/** Phase F7 — one turn in the multi-turn clarification dialog. */
export interface TranslationTurn {
  role: 'user' | 'translator';
  content: string;
  trace_id?: string;
  timestamp?: string;
}

export interface TranslateRequest {
  question: string;
  team_id?: string;
  conversation_id?: string;
  trace_id?: string;
  /** Phase F7 — prior dialog turns. Defaults to []. */
  prior_turns?: TranslationTurn[];
}

export interface PromoteExampleRequest {
  question: string;
  canonical_entities: CanonicalEntity[];
  relationships: CanonicalRelationship[];
  dataset_bindings: DatasetBinding[];
  decomposition: string[];
  intent: string;
  domain?: string;
  score: number;
  promoted_by: string;
  trace_id?: string;
}

export interface PromoteExampleResponse {
  status: 'ok' | 'skipped_no_embedder' | 'error';
  point_id?: string;
  message?: string;
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------
export function useTranslate() {
  return useMutation<TranslationResult, Error, TranslateRequest>({
    mutationFn: async (payload) => {
      const { data } = await apiClient.post<TranslationResult>(
        '/v1/translate',
        payload,
      );
      // Defensive normalization — backends sometimes drop empty arrays.
      return {
        intent: data.intent,
        domain: data.domain,
        canonical_entities: Array.isArray(data.canonical_entities)
          ? data.canonical_entities
          : [],
        relationships: Array.isArray(data.relationships) ? data.relationships : [],
        dataset_bindings: Array.isArray(data.dataset_bindings)
          ? data.dataset_bindings
          : [],
        domain_subtasks: Array.isArray(data.domain_subtasks)
          ? data.domain_subtasks
          : [],
        used_ontology_subgraph: {
          nodes: Array.isArray(data.used_ontology_subgraph?.nodes)
            ? data.used_ontology_subgraph.nodes
            : [],
          edges: Array.isArray(data.used_ontology_subgraph?.edges)
            ? data.used_ontology_subgraph.edges
            : [],
        },
        ontology_versions: Array.isArray(data.ontology_versions)
          ? data.ontology_versions
          : [],
        fallback_used: Boolean(data.fallback_used),
        trace_id: data.trace_id,
        clarification_needed: Boolean(data.clarification_needed),
        clarification_question: data.clarification_question ?? null,
        ambiguous_options: Array.isArray(data.ambiguous_options)
          ? data.ambiguous_options
          : [],
        auditor_issue_id: data.auditor_issue_id ?? null,
        auditor_issue_kind: data.auditor_issue_kind ?? null,
        matched_reports: Array.isArray(data.matched_reports)
          ? (data.matched_reports as unknown[]).map((raw): MatchedReport => {
              const r = (raw ?? {}) as Record<string, unknown>;
              const datasetsRaw = Array.isArray(r.datasets) ? (r.datasets as unknown[]) : [];
              const usesRaw = Array.isArray(r.uses_attributes)
                ? (r.uses_attributes as unknown[])
                : [];
              return {
                report_id: String(r.report_id ?? ''),
                name: String(r.name ?? ''),
                description: String(r.description ?? ''),
                system: (r.system ?? 'CUSTOM') as ReportSystem,
                owner_team: (r.owner_team as string | null | undefined) ?? null,
                datasets: datasetsRaw.map((draw): ReportDataset => {
                  const d = (draw ?? {}) as Record<string, unknown>;
                  return {
                    dataset_id: String(d.dataset_id ?? ''),
                    name: String(d.name ?? ''),
                    command: String(d.command ?? ''),
                    command_type: (d.command_type ?? 'SQL') as ReportCommandType,
                    source_uri: (d.source_uri as string | null | undefined) ?? null,
                    source_name: (d.source_name as string | null | undefined) ?? null,
                  };
                }),
                uses_attributes: usesRaw.map((a) => String(a ?? '')),
                score: Number(r.score ?? 0),
                why: String(r.why ?? ''),
              };
            })
          : [],
      };
    },
  });
}

export function usePromoteExample() {
  return useMutation<PromoteExampleResponse, Error, PromoteExampleRequest>({
    mutationFn: async (payload) => {
      const { data } = await apiClient.post<PromoteExampleResponse>(
        '/v1/translator/examples',
        payload,
      );
      return data;
    },
  });
}
