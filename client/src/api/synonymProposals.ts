import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import apiClient from './axios';

// ---------------------------------------------------------------------------
// Types — match the catalog synonym-proposals backend (Phase F5).
// ---------------------------------------------------------------------------
export type SynonymProposalKind =
  | 'SYNONYM'
  | 'DUPLICATION'
  | 'GRAIN'
  | 'NAMING'
  | 'OTHER';

export type SynonymProposalStatus =
  | 'PROPOSED'
  | 'CONFIRMED'
  | 'REJECTED'
  | 'APPLIED'
  | 'SUPERSEDED';

export interface SynonymMemberColumn {
  ba_fq_name: string;
  column_fq_name: string;
  source_uri: string | null;
  sample_values: string[];
}

export interface SynonymProposal {
  proposal_id: string;
  kind: SynonymProposalKind;
  domain: string | null;
  members_json: string[];
  member_columns_json: SynonymMemberColumn[];
  suggested_canonical_attr: string | null;
  suggested_canonical_column: string | null;
  rationale: string | null;
  confidence: number | null;
  status: SynonymProposalStatus;
  chosen_canonical_attr: string | null;
  chosen_canonical_column: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  applied_at: string | null;
  created_at: string | null;
}

export interface SynonymProposalListResponse {
  proposals: SynonymProposal[];
  count: number;
}

export interface SynonymProposalFilters {
  status?: SynonymProposalStatus | '';
  kind?: SynonymProposalKind | '';
  domain?: string;
}

export interface ReviewSynonymProposalInput {
  proposalId: string;
  action: 'CONFIRM' | 'REJECT';
  chosen_canonical_attr?: string;
  chosen_canonical_column?: string;
  reviewed_by?: string;
  note?: string;
}

export interface ReviewSynonymProposalResponse {
  proposal_id: string;
  status: SynonymProposalStatus;
  superseded?: number;
  message?: string;
}

export interface ConsolidationTriggerResponse {
  proposals_created: number;
  domain: string | null;
  message?: string;
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------
export function useSynonymProposals(filters: SynonymProposalFilters) {
  const params: Record<string, string> = {};
  if (filters.status) params.status = filters.status;
  if (filters.kind) params.kind = filters.kind;
  if (filters.domain) params.domain = filters.domain;

  return useQuery<SynonymProposalListResponse>({
    queryKey: [
      'catalog',
      'synonym-proposals',
      filters.status ?? '',
      filters.kind ?? '',
      filters.domain ?? '',
    ],
    queryFn: async () =>
      (await apiClient.get('/v1/catalog/synonym-proposals', { params })).data,
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
}

export function useReviewSynonymProposal() {
  const qc = useQueryClient();
  return useMutation<ReviewSynonymProposalResponse, Error, ReviewSynonymProposalInput>({
    mutationFn: async (input) => {
      const { data } = await apiClient.post(
        `/v1/catalog/synonym-proposals/${input.proposalId}/review`,
        {
          action: input.action,
          chosen_canonical_attr: input.chosen_canonical_attr,
          chosen_canonical_column: input.chosen_canonical_column,
          reviewed_by: input.reviewed_by,
          note: input.note,
        },
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['catalog', 'synonym-proposals'] });
      qc.invalidateQueries({ queryKey: ['catalog', 'mapping-decisions'] });
      qc.invalidateQueries({ queryKey: ['catalog', 'ontology'] });
    },
  });
}

export function useTriggerConsolidation() {
  const qc = useQueryClient();
  return useMutation<ConsolidationTriggerResponse, Error, { domain?: string }>({
    mutationFn: async ({ domain }) => {
      const { data } = await apiClient.post(
        '/v1/catalog/consolidate',
        {},
        { params: domain ? { domain } : {} },
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['catalog', 'synonym-proposals'] });
    },
  });
}
