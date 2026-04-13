import { useState, useCallback, useEffect } from 'react';
import { Box, Skeleton, Paper, Typography, Button } from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import {
  useAgents,
  useCreateAgent,
  useUpdateAgent,
  useDeleteAgent,
  useAgentTools,
  useSyncAgentTools,
} from '@/api/agents';
import { useTools } from '@/api/tools';
import { useStudioStore } from '@/store/studioStore';
import AgentList from './AgentList';
import AgentEditor from './AgentEditor';
import type { Agent } from '@/types';

/** Extended agent data for the editor */
export interface AgentFormData {
  id?: number;
  agent_id?: string;
  name: string;
  role: string;
  status: Agent['status'];
  tools: string[];
  domains: string[];
  avatar_color: string;
  primary_language: string;
  llm_provider: string;
  llm_model: string;
  temperature: number;
  max_tokens: number;
  memory_seed: string;
  reasoning_seed: string;
  scoring_weights: ScoringWeights;
}

export interface ScoringWeights {
  relevance: number;
  accuracy: number;
  precision: number;
  latency: number;
  confidence: number;
  knowledge_usage: number;
}

const DEFAULT_AGENT: AgentFormData = {
  name: 'New Agent',
  role: '',
  status: 'IDLE',
  tools: [],
  domains: [],
  avatar_color: '#5c9ce6',
  primary_language: 'Any',
  llm_provider: 'OpenAI',
  llm_model: 'gpt-4o',
  temperature: 0.7,
  max_tokens: 4096,
  memory_seed: '',
  reasoning_seed: '',
  scoring_weights: {
    relevance: 0.2,
    accuracy: 0.2,
    precision: 0.15,
    latency: 0.15,
    confidence: 0.15,
    knowledge_usage: 0.15,
  },
};

const AGENT_LIST_WIDTH = 280;

export default function AgentStudioPage() {
  const { data: agents, isLoading, isError, refetch } = useAgents();
  const { data: allTools } = useTools();
  const selectedAgentId = useStudioStore((s) => s.selectedAgentId);
  const setSelectedAgent = useStudioStore((s) => s.setSelectedAgent);
  const setDirtyAgent = useStudioStore((s) => s.setDirtyAgent);

  const createAgent = useCreateAgent();
  const updateAgent = useUpdateAgent();
  const deleteAgent = useDeleteAgent();
  const syncTools = useSyncAgentTools();

  const [agentData, setAgentData] = useState<AgentFormData | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [currentAgentUuid, setCurrentAgentUuid] = useState<string | undefined>(undefined);

  // Fetch assigned tools for the selected agent
  const { data: agentToolsData } = useAgentTools(currentAgentUuid);

  // When agent tools load, update the form data with tool names
  useEffect(() => {
    if (agentToolsData && agentData && currentAgentUuid === agentData.agent_id) {
      const toolNames = agentToolsData.map((t) => t.tool_name);
      // Only update if different to avoid infinite loops
      const current = JSON.stringify(agentData.tools);
      const fetched = JSON.stringify(toolNames);
      if (current !== fetched) {
        setAgentData((prev) => prev ? { ...prev, tools: toolNames } : prev);
      }
    }
  }, [agentToolsData, currentAgentUuid]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSelectAgent = useCallback(
    (agent: Agent) => {
      setSelectedAgent(String(agent.id));
      setIsCreating(false);
      setCurrentAgentUuid(agent.agent_id);
      setAgentData({
        id: agent.id,
        agent_id: agent.agent_id,
        name: agent.name,
        role: agent.role ?? agent.description ?? '',
        status: agent.status,
        tools: [], // Will be populated by useAgentTools effect
        domains: agent.domains ?? [],
        avatar_color: '#5c9ce6',
        primary_language: 'Any',
        llm_provider: 'OpenAI',
        llm_model: agent.foundation_model || 'gpt-4o',
        temperature: 0.7,
        max_tokens: 4096,
        memory_seed: (agent as unknown as Record<string, string>).memory_seed ?? '',
        reasoning_seed: (agent as unknown as Record<string, string>).reasoning_seed ?? '',
        scoring_weights: { ...DEFAULT_AGENT.scoring_weights },
      });
      setDirtyAgent(false);
    },
    [setSelectedAgent, setDirtyAgent],
  );

  const handleCreateAgent = useCallback(() => {
    setSelectedAgent(null);
    setIsCreating(true);
    setCurrentAgentUuid(undefined);
    setAgentData({ ...DEFAULT_AGENT });
    setDirtyAgent(true);
  }, [setSelectedAgent, setDirtyAgent]);

  const handleDeleteAgent = useCallback(() => {
    if (!agentData?.agent_id) {
      setSelectedAgent(null);
      setAgentData(null);
      setIsCreating(false);
      setDirtyAgent(false);
      return;
    }
    deleteAgent.mutate(agentData.agent_id, {
      onSuccess: () => {
        setSelectedAgent(null);
        setAgentData(null);
        setIsCreating(false);
        setCurrentAgentUuid(undefined);
        setDirtyAgent(false);
      },
    });
  }, [agentData, deleteAgent, setSelectedAgent, setDirtyAgent]);

  const handleDuplicateAgent = useCallback(() => {
    if (!agentData) return;
    setSelectedAgent(null);
    setIsCreating(true);
    setCurrentAgentUuid(undefined);
    setAgentData({ ...agentData, id: undefined, agent_id: undefined, name: `${agentData.name} (Copy)` });
    setDirtyAgent(true);
  }, [agentData, setSelectedAgent, setDirtyAgent]);

  // Build a name->tool_id map for syncing tools
  const toolNameToId = new Map((allTools ?? []).map((t) => [t.name, t.tool_id]));

  const handleSaveComplete = useCallback(() => {
    if (!agentData) return;

    const saveToolAssignments = (agentUuid: string) => {
      const toolIds = agentData.tools
        .map((name) => toolNameToId.get(name))
        .filter((id): id is string => !!id);
      syncTools.mutate({ agentId: agentUuid, toolIds });
    };

    if (isCreating) {
      createAgent.mutate(
        {
          name: agentData.name,
          description: agentData.role || undefined,
          foundation_model: agentData.llm_model,
          is_primary: false,
        },
        {
          onSuccess: (created) => {
            const createdAny = created as unknown as Record<string, Record<string, unknown>>;
            const newUuid = created.agent_id ?? createdAny.agent?.agent_id as string;
            setDirtyAgent(false);
            setIsCreating(false);
            setSelectedAgent(String(created.id ?? createdAny.agent?.id));
            setCurrentAgentUuid(newUuid);
            setAgentData((prev) => prev ? {
              ...prev,
              id: created.id ?? createdAny.agent?.id as number,
              agent_id: newUuid,
            } : prev);
            if (newUuid && agentData.tools.length > 0) {
              saveToolAssignments(newUuid);
            }
          },
        },
      );
    } else if (agentData.agent_id) {
      updateAgent.mutate(
        {
          agentId: agentData.agent_id,
          payload: {
            name: agentData.name,
            description: agentData.role || undefined,
            foundation_model: agentData.llm_model,
            status: agentData.status,
            memory_seed: agentData.memory_seed || undefined,
            reasoning_seed: agentData.reasoning_seed || undefined,
          },
        },
        {
          onSuccess: () => {
            setDirtyAgent(false);
            saveToolAssignments(agentData.agent_id!);
          },
        },
      );
    }
  }, [agentData, isCreating, createAgent, updateAgent, syncTools, toolNameToId, setDirtyAgent, setSelectedAgent]);

  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', height: '100%', gap: 2 }}>
        <Skeleton
          variant="rectangular"
          width={AGENT_LIST_WIDTH}
          sx={{ borderRadius: 2, flexShrink: 0, height: '100%' }}
        />
        <Skeleton variant="rectangular" sx={{ flex: 1, borderRadius: 2, height: '100%' }} />
      </Box>
    );
  }

  if (isError) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%' }}>
        <Paper sx={{ p: 4, textAlign: 'center', maxWidth: 400 }}>
          <Typography variant="h6" color="error" gutterBottom>
            Failed to load agents
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Unable to connect to the agent-mgmt service.
          </Typography>
          <Button variant="outlined" startIcon={<RefreshIcon />} onClick={() => refetch()}>
            Retry
          </Button>
        </Paper>
      </Box>
    );
  }

  return (
    <Box sx={{ display: 'flex', height: 'calc(100vh - 112px)', gap: 0 }}>
      <AgentList
        agents={agents ?? []}
        selectedAgentId={selectedAgentId}
        onSelect={handleSelectAgent}
        onCreate={handleCreateAgent}
      />
      <AgentEditor
        agentData={agentData}
        isCreating={isCreating}
        onChange={(data) => {
          setAgentData(data);
          setDirtyAgent(true);
        }}
        onSave={handleSaveComplete}
        onDelete={handleDeleteAgent}
        onDuplicate={handleDuplicateAgent}
      />
    </Box>
  );
}
