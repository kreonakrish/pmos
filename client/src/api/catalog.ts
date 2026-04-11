import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import apiClient from './axios';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
export interface Crawler {
  crawler_id: string;
  name: string;
  description: string | null;
  source_type: string;
  connection: Record<string, unknown>;
  options: Record<string, unknown> | null;
  schedule_cron: string | null;
  status: 'ACTIVE' | 'PAUSED' | 'ERROR';
  last_run_at: string | null;
  last_run_status: 'SUCCESS' | 'FAILURE' | 'PARTIAL' | null;
  created_at: string;
}

export interface CrawlRun {
  run_id: string;
  crawler_id: string;
  started_at: string;
  finished_at: string | null;
  status: 'RUNNING' | 'SUCCESS' | 'FAILURE' | 'PARTIAL';
  assets_found: number;
  columns_found: number;
  mappings_made: number;
  entities_created: number;
  duration_ms: number | null;
  error_message: string | null;
  triggered_by: string | null;
}

export interface CatalogAsset {
  source_name: string;
  source_type: string;
  fq_name: string;
  fully_qualified: string;
  asset_type: string;
  schema_name: string | null;
  asset_name: string;
  row_count: number | null;
  comment: string | null;
  column_count: number;
}

export interface CatalogColumn {
  name: string;
  fq_name: string;
  data_type: string;
  nullable: boolean;
  is_pk: boolean;
  is_fk: boolean;
  fk_references: string | null;
  ordinal: number;
  sample_values: string[];
  comment: string | null;
  attribute: string | null;
  domain: string | null;
  entity: string | null;
  confidence: number | null;
  mapping_status: string | null;
}

export interface OntologyDomain {
  domain: string;
  entities: Array<{ entity: string; attributes: number }>;
}

export interface MappingDecision {
  decision_id: string;
  run_id: string;
  crawler_id: string;
  data_source: string;
  data_asset: string;
  data_column: string;
  data_type: string | null;
  is_pk: boolean;
  is_fk: boolean;
  sample_values: unknown;
  proposed_domain: string | null;
  proposed_entity: string | null;
  proposed_attribute: string | null;
  confidence: number | null;
  reasoning: string | null;
  model_version: string | null;
  status: 'AUTO_ACCEPTED' | 'CONFIRMED' | 'CORRECTED' | 'REJECTED' | 'PENDING';
  auditor_domain: string | null;
  auditor_entity: string | null;
  auditor_attribute: string | null;
  auditor_note: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  reward_signal: number | null;
  created_at: string;
}

export interface MappingDecisionSummary {
  total: number;
  auto_accepted: number;
  confirmed: number;
  corrected: number;
  rejected: number;
  avg_confidence: number;
  low_confidence: number;
  review_coverage: number;
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------
export function useCrawlers() {
  return useQuery<{ crawlers: Crawler[]; count: number }>({
    queryKey: ['catalog', 'crawlers'],
    queryFn: async () => (await apiClient.get('/v1/catalog/crawlers')).data,
    staleTime: 30_000,
    refetchInterval: 30_000,
  });
}

export function useCrawlRuns(crawlerId: string | null, limit = 20) {
  return useQuery<{ runs: CrawlRun[] }>({
    queryKey: ['catalog', 'runs', crawlerId ?? '', limit],
    queryFn: async () =>
      (await apiClient.get(`/v1/catalog/crawlers/${crawlerId}/runs`, { params: { limit } })).data,
    enabled: !!crawlerId,
    staleTime: 10_000,
    refetchInterval: 10_000,
  });
}

export function useRunCrawler() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (crawlerId: string) => {
      const { data } = await apiClient.post(`/v1/catalog/crawlers/${crawlerId}/run`, {});
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['catalog'] });
    },
  });
}

export function useCatalogAssets(sourceName?: string) {
  return useQuery<{ assets: CatalogAsset[] }>({
    queryKey: ['catalog', 'assets', sourceName ?? ''],
    queryFn: async () =>
      (await apiClient.get('/v1/catalog/assets', { params: { source_name: sourceName } })).data,
    staleTime: 30_000,
  });
}

export function useCatalogAssetDetail(fqName: string | null) {
  return useQuery<{ asset: Record<string, unknown> | null; columns: CatalogColumn[] }>({
    queryKey: ['catalog', 'asset-detail', fqName ?? ''],
    queryFn: async () =>
      (await apiClient.get(`/v1/catalog/assets/${encodeURIComponent(fqName || '')}`)).data,
    enabled: !!fqName,
    staleTime: 30_000,
  });
}

export function useOntology() {
  return useQuery<{ domains: OntologyDomain[] }>({
    queryKey: ['catalog', 'ontology'],
    queryFn: async () => (await apiClient.get('/v1/catalog/ontology')).data,
    staleTime: 30_000,
  });
}

export function useMappingDecisions(status?: string, limit = 100) {
  return useQuery<{ decisions: MappingDecision[]; count: number }>({
    queryKey: ['catalog', 'mapping-decisions', status ?? '', limit],
    queryFn: async () =>
      (await apiClient.get('/v1/catalog/mapping-decisions', { params: { status, limit } })).data,
    staleTime: 15_000,
  });
}

export function useMappingDecisionsSummary() {
  return useQuery<MappingDecisionSummary>({
    queryKey: ['catalog', 'mapping-decisions', 'summary'],
    queryFn: async () =>
      (await apiClient.get('/v1/catalog/mapping-decisions/summary')).data,
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
}

export interface ReviewAction {
  decisionId: string;
  action: 'CONFIRM' | 'CORRECT' | 'REJECT';
  auditor_domain?: string;
  auditor_entity?: string;
  auditor_attribute?: string;
  auditor_note?: string;
}

export function useReviewMapping() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: ReviewAction) => {
      const { data } = await apiClient.post(
        `/v1/catalog/mapping-decisions/${body.decisionId}/review`,
        {
          action: body.action,
          auditor_domain: body.auditor_domain,
          auditor_entity: body.auditor_entity,
          auditor_attribute: body.auditor_attribute,
          auditor_note: body.auditor_note,
          reviewed_by: 'admin',
        },
      );
      return data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['catalog'] }),
  });
}
