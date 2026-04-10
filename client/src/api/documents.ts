import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import apiClient from '@/api/axios';
import type { Document } from '@/types';

interface DocumentFilters {
  status?: string;
  team_id?: string;
  agent_id?: number;
}

export interface RagConfig {
  embedding_model: string;
  embedding_dimension: number;
  chunk_size: number;
  chunk_overlap: number;
  chunk_strategies: string[];
  available_models: string[];
  vector_store_backend: string;
  top_k: number;
  reranker_model: string;
}

export interface ReindexParams {
  docId: string;
  chunk_strategy?: string;
  chunk_size?: number;
  chunk_overlap?: number;
  embedding_model?: string;
}

export function useDocuments(filters?: DocumentFilters) {
  return useQuery<Document[]>({
    queryKey: ['documents', filters],
    queryFn: async () => {
      const { data } = await apiClient.get('/v1/documents', { params: filters });
      return data.documents ?? data.items ?? data;
    },
  });
}

export function useDocument(docId: string | null) {
  return useQuery<Document>({
    queryKey: ['documents', docId],
    queryFn: async () => {
      const { data } = await apiClient.get(`/v1/documents/${docId}`);
      return data;
    },
    enabled: !!docId,
  });
}

export function useRagConfig() {
  return useQuery<RagConfig>({
    queryKey: ['rag-config'],
    queryFn: async () => {
      const { data } = await apiClient.get('/v1/rag/config');
      return data;
    },
    staleTime: 60_000,
  });
}

export function useUploadDocument() {
  const qc = useQueryClient();
  return useMutation<
    { chunks_indexed: number; document_id: string },
    Error,
    {
      file: File;
      team_id?: string;
      agent_id?: number;
      chunk_strategy?: string;
      chunk_size?: number;
      chunk_overlap?: number;
      embedding_model?: string;
      conversation_id?: string;
    }
  >({
    mutationFn: async ({ file, team_id, agent_id, chunk_strategy, chunk_size, chunk_overlap, embedding_model, conversation_id }) => {
      const formData = new FormData();
      formData.append('file', file);
      if (team_id) formData.append('team_id', team_id);
      if (agent_id !== undefined) formData.append('agent_id', String(agent_id));
      if (chunk_strategy) formData.append('chunk_strategy', chunk_strategy);
      if (chunk_size) formData.append('chunk_size', String(chunk_size));
      if (chunk_overlap !== undefined) formData.append('chunk_overlap', String(chunk_overlap));
      if (embedding_model) formData.append('embedding_model', embedding_model);
      if (conversation_id) formData.append('conversation_id', conversation_id);

      const { data } = await apiClient.post('/v1/documents/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 120_000,
      });
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['documents'] });
    },
  });
}

export function useDeleteDocument() {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: async (docId) => {
      await apiClient.delete(`/v1/documents/${docId}`);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['documents'] });
    },
  });
}

export function useReindexDocument() {
  const qc = useQueryClient();
  return useMutation<void, Error, ReindexParams>({
    mutationFn: async ({ docId, ...config }) => {
      await apiClient.post(`/v1/documents/${docId}/reindex`, config);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['documents'] });
    },
  });
}

export function useTestRetrieval() {
  return useMutation<
    { results: Array<{ content: string; score: number; source: string }> },
    Error,
    { query: string; top_k?: number; document_id?: string }
  >({
    mutationFn: async (payload) => {
      const { data } = await apiClient.post('/v1/rag/query', payload);
      return data;
    },
  });
}
