import { useQuery, useMutation } from '@tanstack/react-query';
import apiClient from './axios';

export interface MemoryEntryResponse {
  id: number;
  agent_id: number;
  memory_tier: 'SHORT_TERM' | 'LONG_TERM' | 'REASONING' | 'EPISODIC';
  content: string;
  metadata?: Record<string, unknown>;
  relevance_score: number;
  access_count: number;
  decay_factor: number;
  expires_at?: string;
  created_at: string;
}

export interface AssemblePromptPayload {
  agent_id: number;
  context: {
    task_type: string;
    domain: string;
    recent_messages: string[];
  };
  tiers?: string[];
}

export interface AssemblePromptResponse {
  system_prompt: string;
  sources: {
    short_term_hits: number;
    long_term_hits: number;
    reasoning_hits: number;
    episodic_hits: number;
  };
  trace_id: string;
}

export function useMemoryEntries(
  agentId: number,
  tier?: string,
  options?: { enabled?: boolean },
) {
  return useQuery<MemoryEntryResponse[]>({
    queryKey: ['memory-entries', agentId, tier],
    queryFn: async () => {
      const params: Record<string, string | number> = { agent_id: agentId };
      if (tier) {
        params.tier = tier.toLowerCase();
        if (params.tier !== 'short_term') {
          params.query = '*';
        }
      }
      const { data } = await apiClient.get('/v1/memory/entries', { params });
      const raw = data.results ?? data.items ?? data;
      if (!Array.isArray(raw)) return [];

      // Normalize backend response to unified MemoryEntryResponse
      return raw.map((r: Record<string, unknown>, idx: number) => ({
        id: Number(r.id ?? r.episode_id ?? idx),
        agent_id: Number(r.agent_id ?? agentId),
        memory_tier: (tier?.toUpperCase() ?? 'EPISODIC') as MemoryEntryResponse['memory_tier'],
        content: String(
          r.content ?? r.final_output ?? r.value ?? r.pattern ?? r.task_description ?? ''
        ),
        metadata: {
          session_id: r.session_id,
          outcome: r.outcome,
          episode_id: r.episode_id,
          key: r.key ?? r.key_text,
          ...(r.metadata as Record<string, unknown> ?? {}),
        },
        relevance_score: Number(r.relevance_score ?? r.similarity_score ?? r.importance_score ?? 0),
        access_count: Number(r.access_count ?? r.frequency ?? 0),
        decay_factor: Number(r.decay_factor ?? r.importance_score ?? 0.5),
        expires_at: r.expires_at ? String(r.expires_at) : undefined,
        created_at: String(r.created_at ?? ''),
      }));
    },
    enabled: (options?.enabled ?? true) && agentId > 0,
    staleTime: 30_000,
  });
}

export interface MemoryStats {
  short_term: number;
  long_term: number;
  reasoning: number;
  episodic: number;
}

export function useMemoryStats(agentId: number | undefined) {
  return useQuery<MemoryStats>({
    queryKey: ['memory-stats', agentId],
    queryFn: async () => {
      // Fetch counts from each tier in parallel
      const tiers = ['short_term', 'long_term', 'reasoning', 'episodic'] as const;
      const results = await Promise.allSettled(
        tiers.map(async (tier) => {
          const params: Record<string, string | number> = { agent_id: agentId!, tier };
          if (tier !== 'short_term') params.query = '*';
          params.k = 50;
          const { data } = await apiClient.get('/v1/memory/retrieve', { params });
          return (data.results ?? []).length;
        }),
      );
      return {
        short_term: results[0].status === 'fulfilled' ? results[0].value : 0,
        long_term: results[1].status === 'fulfilled' ? results[1].value : 0,
        reasoning: results[2].status === 'fulfilled' ? results[2].value : 0,
        episodic: results[3].status === 'fulfilled' ? results[3].value : 0,
      };
    },
    enabled: !!agentId && agentId > 0,
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
}

export function useAssemblePrompt() {
  return useMutation<AssemblePromptResponse, Error, AssemblePromptPayload>({
    mutationFn: async (payload) => {
      const { data } = await apiClient.post('/v1/memory/assemble-prompt', payload);
      return data;
    },
  });
}
