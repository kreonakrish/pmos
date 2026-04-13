import { useState, useCallback, useEffect } from 'react';
import { Box, Skeleton, Paper, Typography, Button } from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import { useSearchParams } from 'react-router-dom';
import type { Edge, Node } from 'reactflow';
import { useTeams, useTeam, useCreateTeam, useUpdateTeam, useDeleteTeam, useSyncTeamHierarchy } from '@/api/teams';
import type { TeamAgentHierarchy } from '@/api/teams';
import { useAgents } from '@/api/agents';
import type { Team } from '@/types';
import TeamList from './TeamList';
import TeamCanvas from './TeamCanvas';

export default function TeamStudioPage() {
  const [searchParams] = useSearchParams();
  const teamFromUrl = searchParams.get('team');
  const [selectedTeamId, setSelectedTeamId] = useState<string | null>(teamFromUrl);

  // Auto-select team from URL query param
  useEffect(() => {
    if (teamFromUrl && teamFromUrl !== selectedTeamId) {
      setSelectedTeamId(teamFromUrl);
    }
  }, [teamFromUrl]); // eslint-disable-line react-hooks/exhaustive-deps

  const { data: teams, isLoading: teamsLoading, isError: teamsError, refetch: refetchTeams } = useTeams();
  const { data: selectedTeam, isLoading: teamLoading } = useTeam(selectedTeamId);
  const { data: agents, isLoading: agentsLoading } = useAgents();

  const createTeam = useCreateTeam();
  const updateTeam = useUpdateTeam();
  const deleteTeam = useDeleteTeam();
  const syncHierarchy = useSyncTeamHierarchy();

  const handleSelectTeam = useCallback((teamId: string) => {
    setSelectedTeamId(teamId);
  }, []);

  const handleCreateTeam = useCallback(() => {
    createTeam.mutate(
      {
        name: `Team ${(teams?.length ?? 0) + 1}`,
        description: '',
        use_smart_workflow: true,
        accuracy_threshold: 0.7,
        max_retries: 3,
        retry_strategy: 'EXPONENTIAL',
      },
      {
        onSuccess: (newTeam) => {
          setSelectedTeamId(newTeam.team_id);
        },
      }
    );
  }, [createTeam, teams]);

  const handleSave = useCallback(
    (teamPatch: Partial<Team>, nodes: Node[], edges: Edge[]) => {
      if (!selectedTeamId) return;

      // Save team metadata
      updateTeam.mutate({ teamId: selectedTeamId, payload: teamPatch });

      // Build hierarchy from canvas nodes + edges
      const agentHierarchy: TeamAgentHierarchy[] = [];
      const allAgents = agents ?? [];

      for (const node of nodes) {
        const agentId = node.data?.agentId;
        if (!agentId) continue;

        // Find the agent's UUID from numeric id
        const agent = allAgents.find((a) => a.id === agentId);
        if (!agent) continue;

        const isOrchestrator = node.type === 'orchestratorNode';
        const isFallback = node.type === 'fallbackNode';

        // Find parent from edges (edge target = this node → source is parent)
        const parentEdge = edges.find((e) => e.target === node.id);
        let parentAgentUuid: string | null = null;
        if (parentEdge) {
          const parentNode = nodes.find((n) => n.id === parentEdge.source);
          if (parentNode?.data?.agentId) {
            const parentAgent = allAgents.find((a) => a.id === parentNode.data.agentId);
            parentAgentUuid = parentAgent?.agent_id ?? null;
          }
        }

        // Get rules from node data if available
        const rules = node.data?.rules ?? {};

        agentHierarchy.push({
          agent_id: agent.agent_id,
          priority: isOrchestrator ? 0 : (agentHierarchy.length),
          role: isOrchestrator ? 'orchestrator' : (isFallback ? 'fallback' : 'specialist'),
          parent_agent_id: parentAgentUuid,
          execution_mode: rules.executionMode ?? 'sequential',
          criticality: rules.criticality ?? 'MEDIUM',
          timeout_seconds: rules.timeout ?? 30,
          fallback_agent_id: rules.fallbackAgentId ?? null,
        });
      }

      // Sync hierarchy to backend
      if (agentHierarchy.length > 0) {
        syncHierarchy.mutate({ teamId: selectedTeamId, agents: agentHierarchy });
      }
    },
    [selectedTeamId, updateTeam, syncHierarchy, agents]
  );

  const handleDelete = useCallback(() => {
    if (!selectedTeamId) return;
    deleteTeam.mutate(selectedTeamId, {
      onSuccess: () => {
        setSelectedTeamId(null);
      },
    });
  }, [selectedTeamId, deleteTeam]);

  const handleDuplicate = useCallback(() => {
    if (!selectedTeam) return;
    createTeam.mutate(
      {
        name: `${selectedTeam.name} (Copy)`,
        description: selectedTeam.description,
        use_smart_workflow: selectedTeam.use_smart_workflow,
        accuracy_threshold: selectedTeam.accuracy_threshold,
        max_retries: selectedTeam.max_retries,
        retry_strategy: selectedTeam.retry_strategy,
      },
      {
        onSuccess: (newTeam) => {
          setSelectedTeamId(newTeam.team_id);
        },
      }
    );
  }, [selectedTeam, createTeam]);

  if (teamsLoading && agentsLoading) {
    return (
      <Box sx={{ display: 'flex', height: 'calc(100vh - 112px)' }}>
        <Box sx={{ width: 260, p: 2, display: 'flex', flexDirection: 'column', gap: 1 }}>
          <Skeleton variant="text" width={100} height={32} />
          <Skeleton variant="rectangular" height={40} sx={{ borderRadius: 1 }} />
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} variant="rectangular" height={56} sx={{ borderRadius: 1 }} />
          ))}
        </Box>
        <Box sx={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Skeleton variant="rectangular" width="80%" height="60%" sx={{ borderRadius: 2 }} />
        </Box>
      </Box>
    );
  }

  if (teamsError) {
    return (
      <Box sx={{ p: 3, display: 'flex', justifyContent: 'center' }}>
        <Paper sx={{ p: 4, textAlign: 'center', maxWidth: 400 }}>
          <Typography variant="h6" color="error" gutterBottom>
            Failed to load teams
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Unable to fetch team data. The agent-mgmt service may be unavailable.
          </Typography>
          <Button variant="outlined" startIcon={<RefreshIcon />} onClick={() => refetchTeams()}>
            Retry
          </Button>
        </Paper>
      </Box>
    );
  }

  return (
    <Box sx={{ display: 'flex', height: 'calc(100vh - 112px)', mx: -3, mt: -3, mb: -3 }}>
      <TeamList
        teams={teams}
        isLoading={teamsLoading}
        selectedTeamId={selectedTeamId}
        onSelectTeam={handleSelectTeam}
        onCreateTeam={handleCreateTeam}
      />
      <TeamCanvas
        team={selectedTeam ?? null}
        agents={agents ?? []}
        isLoading={teamLoading || agentsLoading}
        onSave={handleSave}
        onDelete={handleDelete}
        onDuplicate={handleDuplicate}
      />
    </Box>
  );
}
