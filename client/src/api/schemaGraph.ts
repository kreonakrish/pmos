import { useQuery } from '@tanstack/react-query';
import apiClient from '@/api/axios';

// ---------------------------------------------------------------------------
// Types — match backend response from GET /v1/catalog/schema-graph
// ---------------------------------------------------------------------------
export interface SchemaProperty {
  name: string;
  type: string;
}

export interface SchemaNode {
  id: string;
  label: string;
  properties: SchemaProperty[];
}

export interface SchemaEdge {
  type: string;
  from: string | null;
  to: string | null;
  properties: SchemaProperty[];
}

export interface SchemaGraphResponse {
  trace_id: string;
  nodes: SchemaNode[];
  edges: SchemaEdge[];
  node_count: number;
  edge_count: number;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------
export function useSchemaGraph() {
  return useQuery<SchemaGraphResponse>({
    queryKey: ['catalog', 'schema-graph'],
    queryFn: async () => {
      const { data } = await apiClient.get<SchemaGraphResponse>(
        '/v1/catalog/schema-graph',
      );
      // Defensive normalization: ensure properties arrays exist and edges have endpoints.
      const nodes: SchemaNode[] = (data.nodes ?? []).map((n) => ({
        id: n.id,
        label: n.label ?? n.id,
        properties: Array.isArray(n.properties) ? n.properties : [],
      }));
      const edges: SchemaEdge[] = (data.edges ?? []).map((e) => ({
        type: e.type,
        from: e.from ?? null,
        to: e.to ?? null,
        properties: Array.isArray(e.properties) ? e.properties : [],
      }));
      return {
        trace_id: data.trace_id,
        nodes,
        edges,
        node_count: data.node_count ?? nodes.length,
        edge_count: data.edge_count ?? edges.length,
      };
    },
    staleTime: 60_000,
  });
}
