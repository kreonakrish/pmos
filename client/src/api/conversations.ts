import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import apiClient from '@/api/axios';
import type { Conversation, Message } from '@/types';
import type { Visualization } from '@/api/visualization';

/**
 * Wire shape returned by POST /v1/conversations/:id/messages. The
 * orchestrator surfaces the persisted assistant message under
 * `agent_message`, but for deterministic Report (Ext2) hits the chart
 * inferer also lifts the `visualizations` array to the top level so the
 * client can render charts on the FIRST send without waiting for a
 * conversation refresh.
 */
export interface ChatResponse {
  agent_message?: Message;
  visualizations?: Visualization[];
  // Pass-through for any other top-level keys the backend may add.
  [key: string]: unknown;
}

export function useConversations() {
  return useQuery<Conversation[]>({
    queryKey: ['conversations'],
    queryFn: async () => {
      const { data } = await apiClient.get('/v1/conversations');
      const convs = data.conversations ?? data.items ?? data;
      // Normalize: use conversation_id (UUID) as the primary id
      return convs.map((c: Record<string, unknown>) => ({
        ...c,
        id: (c.conversation_id as string) || String(c.id),
      }));
    },
  });
}

export function useConversationMessages(conversationId: string | null) {
  return useQuery<Message[]>({
    queryKey: ['conversations', conversationId, 'messages'],
    queryFn: async () => {
      const { data } = await apiClient.get(`/v1/conversations/${conversationId}/messages`);
      const msgs = data.messages ?? data.items ?? data;
      // Normalize: map created_at to timestamp, map role 'assistant' to 'agent' for display
      return msgs.map((m: Record<string, unknown>) => ({
        ...m,
        id: String(m.message_id || m.id),
        timestamp: m.timestamp || m.created_at || new Date().toISOString(),
        role: m.role === 'assistant' ? 'agent' : m.role,
      }));
    },
    enabled: !!conversationId,
  });
}

export function useCreateConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (params?: { title?: string; team_id?: string }) => {
      const { data } = await apiClient.post('/v1/conversations', {
        title: params?.title ?? 'New Conversation',
        team_id: params?.team_id,
      });
      const conv = data.conversation ?? data;
      // Normalize id to conversation_id (UUID)
      return { ...conv, id: conv.conversation_id || conv.id } as Conversation;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['conversations'] });
    },
  });
}

export function useSendMessage() {
  const qc = useQueryClient();
  return useMutation<ChatResponse, Error, { conversationId: string; content: string }>({
    mutationFn: async (params) => {
      const { data } = await apiClient.post<ChatResponse>(
        `/v1/conversations/${params.conversationId}/messages`,
        { content: params.content },
        { timeout: 120_000 },
      );
      return data;
    },
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({
        queryKey: ['conversations', variables.conversationId, 'messages'],
      });
    },
  });
}

export function useDeleteConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      await apiClient.delete(`/v1/conversations/${id}`);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['conversations'] });
    },
  });
}

export function useRenameConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (params: { id: string; title: string }) => {
      const { data } = await apiClient.patch(`/v1/conversations/${params.id}`, {
        title: params.title,
      });
      return data as Conversation;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['conversations'] });
    },
  });
}
