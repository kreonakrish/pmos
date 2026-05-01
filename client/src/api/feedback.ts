// Phase C.3 — user feedback API client.

import apiClient from './axios';

export interface FeedbackBody {
  rating?: 'UP' | 'DOWN' | 'NEUTRAL';
  comment?: string;
  trace_id?: string;
  graph_id?: string;
  turn_id?: string;
}

export interface FeedbackRow {
  id: number;
  conversation_id: string;
  trace_id?: string;
  graph_id?: string;
  turn_id?: string;
  user_id?: number | null;
  rating: 'UP' | 'DOWN' | 'NEUTRAL';
  comment?: string | null;
  created_at: string;
}

export async function postFeedback(
  conversationId: string,
  body: FeedbackBody,
): Promise<{ id: number }> {
  const resp = await apiClient.post<{ id: number }>(
    `/v1/conversations/${encodeURIComponent(conversationId)}/feedback`,
    body,
  );
  return resp.data;
}

export async function listFeedback(
  conversationId: string,
  limit = 20,
): Promise<FeedbackRow[]> {
  const resp = await apiClient.get<{ items: FeedbackRow[] }>(
    `/v1/conversations/${encodeURIComponent(conversationId)}/feedback`,
    { params: { limit } },
  );
  return resp.data.items ?? [];
}
