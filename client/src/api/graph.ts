import { useQuery } from '@tanstack/react-query';
import apiClient from '@/api/axios';
import type { TaskGraphData } from '@/types';

export interface GraphTeam {
  team_id: string;
  name: string;
}

export function useTaskGraph(filters?: { conversationId?: string; teamId?: string; graphId?: string }) {
  return useQuery<TaskGraphData & { teams?: GraphTeam[] }>({
    queryKey: ['task-graph', filters?.conversationId, filters?.teamId, filters?.graphId],
    queryFn: async () => {
      const params: Record<string, string> = {};
      if (filters?.conversationId) params.conversation_id = filters.conversationId;
      if (filters?.teamId) params.team_id = filters.teamId;
      if (filters?.graphId) params.graph_id = filters.graphId;
      const { data } = await apiClient.get('/v1/graph/tasks', { params });
      // Normalize: map node_id to task_id, assigned_agent_name to agent_name
      const nodes = (data.nodes ?? []).map((n: Record<string, unknown>) => ({
        ...n,
        task_id: n.task_id || n.node_id || n.id,
        agent_name: n.agent_name || n.assigned_agent_name,
      }));
      // Normalize edges: API returns {from, to, type} but UI expects {source, target, relationship}
      const edges = (data.edges ?? []).map((e: Record<string, unknown>) => ({
        source: e.source || e.from,
        target: e.target || e.to,
        relationship: e.relationship || e.type || 'SPAWNED_BY',
      }));
      return { ...data, nodes, edges, teams: data.teams ?? [] };
    },
  });
}
