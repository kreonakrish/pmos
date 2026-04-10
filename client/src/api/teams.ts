import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import apiClient from '@/api/axios';
import type { Team } from '@/types';

export function useTeams() {
  return useQuery<Team[]>({
    queryKey: ['teams'],
    queryFn: async () => {
      const { data } = await apiClient.get('/v1/teams');
      return data.teams ?? data.items ?? data;
    },
  });
}

export function useTeam(teamId: string | null) {
  return useQuery<Team>({
    queryKey: ['teams', teamId],
    queryFn: async () => {
      const { data } = await apiClient.get(`/v1/teams/${teamId}`);
      return data.team ?? data;
    },
    enabled: !!teamId,
  });
}

export function useCreateTeam() {
  const qc = useQueryClient();
  return useMutation<Team, Error, Partial<Team>>({
    mutationFn: async (payload) => {
      const { data } = await apiClient.post('/v1/teams', payload);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['teams'] });
    },
  });
}

export function useUpdateTeam() {
  const qc = useQueryClient();
  return useMutation<Team, Error, { teamId: string; payload: Partial<Team> }>({
    mutationFn: async ({ teamId, payload }) => {
      const { data } = await apiClient.patch(`/v1/teams/${teamId}`, payload);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['teams'] });
    },
  });
}

export function useDeleteTeam() {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: async (teamId) => {
      await apiClient.delete(`/v1/teams/${teamId}`);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['teams'] });
    },
  });
}

export function useAddAgentToTeam() {
  const qc = useQueryClient();
  return useMutation<void, Error, { teamId: string; agentId: string; priority?: number; role?: string }>({
    mutationFn: async ({ teamId, agentId, priority, role }) => {
      await apiClient.post(`/v1/teams/${teamId}/agents`, {
        agent_id: agentId,
        priority: priority ?? 0,
        role,
      });
    },
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ['teams', variables.teamId] });
      qc.invalidateQueries({ queryKey: ['teams'] });
    },
  });
}

export interface TeamAgentHierarchy {
  agent_id: string;
  priority: number;
  role?: string;
  parent_agent_id?: string | null;
  execution_mode?: string;
  criticality?: string;
  timeout_seconds?: number;
  fallback_agent_id?: string | null;
}

export function useSyncTeamHierarchy() {
  const qc = useQueryClient();
  return useMutation<void, Error, { teamId: string; agents: TeamAgentHierarchy[] }>({
    mutationFn: async ({ teamId, agents }) => {
      await apiClient.put(`/v1/teams/${teamId}/hierarchy`, { agents });
    },
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ['teams', variables.teamId] });
      qc.invalidateQueries({ queryKey: ['teams'] });
    },
  });
}

export function useRemoveAgentFromTeam() {
  const qc = useQueryClient();
  return useMutation<void, Error, { teamId: string; agentId: string }>({
    mutationFn: async ({ teamId, agentId }) => {
      await apiClient.delete(`/v1/teams/${teamId}/agents/${agentId}`);
    },
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ['teams', variables.teamId] });
      qc.invalidateQueries({ queryKey: ['teams'] });
    },
  });
}
