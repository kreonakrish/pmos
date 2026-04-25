import { useQuery } from '@tanstack/react-query';
import apiClient from './axios';

// ---------------------------------------------------------------------------
// Ext2 — deterministic Report nodes (Data Catalog → Reports tab).
//
// Backed by GET /v1/catalog/reports on the orchestrator. Read-only.
// ---------------------------------------------------------------------------
export type ReportSystem = 'SSRS' | 'COGNOS' | 'POWERBI' | 'TABLEAU' | 'CUSTOM';
export type ReportCommandType = 'SQL' | 'MDX' | 'DAX';

export interface CatalogReportDataset {
  dataset_id: string;
  name: string;
  command: string;
  command_type: ReportCommandType;
  source_uri: string | null;
  source_name: string | null;
}

export interface CatalogReport {
  report_id: string;
  name: string;
  description: string;
  system: ReportSystem;
  owner_team: string | null;
  created_at: string | null;
  updated_at: string | null;
  datasets: CatalogReportDataset[];
  uses_attributes: string[];
}

export interface CatalogReportsResponse {
  trace_id?: string;
  reports: CatalogReport[];
  count: number;
}

export interface ReportFilters {
  system?: ReportSystem | '';
  owner_team?: string;
}

function normalizeReports(raw: unknown): CatalogReport[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((entry): CatalogReport => {
    const r = (entry ?? {}) as Record<string, unknown>;
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
      created_at: (r.created_at as string | null | undefined) ?? null,
      updated_at: (r.updated_at as string | null | undefined) ?? null,
      datasets: datasetsRaw.map((draw): CatalogReportDataset => {
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
    };
  });
}

export function useReports(filters: ReportFilters = {}) {
  const params: Record<string, string> = {};
  if (filters.system) params.system = filters.system;
  if (filters.owner_team) params.owner_team = filters.owner_team;

  return useQuery<CatalogReportsResponse>({
    queryKey: ['catalog', 'reports', filters.system ?? '', filters.owner_team ?? ''],
    queryFn: async () => {
      const { data } = await apiClient.get<CatalogReportsResponse>(
        '/v1/catalog/reports',
        { params },
      );
      return {
        trace_id: data?.trace_id,
        reports: normalizeReports((data as { reports?: unknown })?.reports),
        count: Number((data as { count?: number })?.count ?? 0),
      };
    },
    staleTime: 30_000,
  });
}
