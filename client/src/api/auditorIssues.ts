import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import apiClient from './axios';

// ---------------------------------------------------------------------------
// Types — match the governance auditor-issues backend (Phase F3).
// ---------------------------------------------------------------------------
export type AuditorIssueKind =
  | 'SYNONYM_AMBIGUITY'
  | 'COLUMN_AMBIGUITY'
  | 'NO_RESOLUTION'
  | 'ORPHAN_ENTITY'
  | 'MAPPING_LOW_CONFIDENCE'
  | 'OTHER';

export type AuditorIssueStatus =
  | 'OPEN'
  | 'IN_REVIEW'
  | 'RESOLVED'
  | 'REJECTED'
  | 'SUPERSEDED';

export type AuditorIssueSeverity = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';

export interface AuditorIssue {
  issue_id: string;
  kind: AuditorIssueKind;
  severity: AuditorIssueSeverity;
  status: AuditorIssueStatus;
  title: string;
  description: string | null;
  resource_type: string | null;
  resource_id: string | null;
  payload: Record<string, unknown> | null;
  raised_by: string | null;
  raised_trace: string | null;
  assigned_to: string | null;
  resolved_by: string | null;
  resolution: string | null;
  raised_at: string | null;
  updated_at: string | null;
  resolved_at: string | null;
}

export interface AuditorIssueListResponse {
  issues: AuditorIssue[];
  count: number;
}

export interface AuditorIssueSummaryBucket {
  kind: AuditorIssueKind;
  status: AuditorIssueStatus;
  severity: AuditorIssueSeverity;
  n: number;
}

export interface AuditorIssueSummary {
  open_total: number;
  buckets: AuditorIssueSummaryBucket[];
}

export interface AuditorIssueFilters {
  status?: AuditorIssueStatus | '';
  kind?: AuditorIssueKind | '';
  severity?: AuditorIssueSeverity | '';
  limit?: number;
}

export interface ResolveAuditorIssueInput {
  issueId: string;
  status: 'IN_REVIEW' | 'RESOLVED' | 'REJECTED' | 'SUPERSEDED';
  resolution?: string;
  resolved_by?: string;
  assigned_to?: string;
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------
export function useAuditorIssues(filters: AuditorIssueFilters) {
  const params: Record<string, string | number> = {};
  if (filters.status) params.status = filters.status;
  if (filters.kind) params.kind = filters.kind;
  if (filters.severity) params.severity = filters.severity;
  if (filters.limit) params.limit = filters.limit;

  return useQuery<AuditorIssueListResponse>({
    queryKey: [
      'governance',
      'auditor-issues',
      filters.status ?? '',
      filters.kind ?? '',
      filters.severity ?? '',
      filters.limit ?? 0,
    ],
    queryFn: async () =>
      (await apiClient.get('/v1/governance/auditor-issues', { params })).data,
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
}

export function useAuditorIssuesSummary() {
  return useQuery<AuditorIssueSummary>({
    queryKey: ['governance', 'auditor-issues', 'summary'],
    queryFn: async () =>
      (await apiClient.get('/v1/governance/auditor-issues/summary')).data,
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
}

export function useAuditorIssue(issueId: string | null) {
  return useQuery<AuditorIssue>({
    queryKey: ['governance', 'auditor-issues', 'detail', issueId ?? ''],
    queryFn: async () =>
      (await apiClient.get(`/v1/governance/auditor-issues/${issueId}`)).data,
    enabled: !!issueId,
    staleTime: 10_000,
  });
}

export function useResolveAuditorIssue() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: ResolveAuditorIssueInput) => {
      const { data } = await apiClient.post(
        `/v1/governance/auditor-issues/${input.issueId}/resolve`,
        {
          status: input.status,
          resolution: input.resolution,
          resolved_by: input.resolved_by,
          assigned_to: input.assigned_to,
        },
      );
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['governance', 'auditor-issues'] });
    },
  });
}
