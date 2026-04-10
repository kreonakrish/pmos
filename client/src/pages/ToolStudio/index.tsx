import { useState, useCallback } from 'react';
import { Box, Skeleton, Paper, Typography, Button } from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import { useTools, useCreateTool, useUpdateTool, useDeleteTool } from '@/api/tools';
import { useStudioStore } from '@/store/studioStore';
import ToolList from './ToolList';
import ToolEditor from './ToolEditor';
import type { Tool } from '@/types';

/** Extended tool data for the editor (includes config fields beyond the base Tool type) */
export interface ToolFormData {
  id?: number;
  tool_id?: string;
  name: string;
  description: string;
  tool_type: ToolType;
  domains: string[];
  timeout_ms: number;
  max_retries: number;
  status: Tool['status'];
  config: Record<string, unknown>;
  avg_latency_ms: number;
  success_rate: number;
  last_health_check?: string;
  is_dynamic: boolean;
  agent_count?: number;
}

export type ToolType = 'API' | 'Database' | 'Python' | 'GitHub' | 'WebService';

/** Map API uppercase tool_type to UI ToolType */
const TOOL_TYPE_MAP: Record<string, ToolType> = {
  API: 'API',
  DATABASE: 'Database',
  PYTHON: 'Python',
  GITHUB: 'GitHub',
  WEBSERVICE: 'WebService',
};

function normalizeToolType(raw: string): ToolType {
  return TOOL_TYPE_MAP[raw.toUpperCase()] ?? (TOOL_TYPE_MAP[raw] || 'API');
}

const TOOL_LIST_WIDTH = 280;

const DEFAULT_TOOL: ToolFormData = {
  name: 'New Tool',
  description: '',
  tool_type: 'API',
  domains: [],
  timeout_ms: 30000,
  max_retries: 3,
  status: 'OFFLINE',
  config: {},
  avg_latency_ms: 0,
  success_rate: 0,
  is_dynamic: false,
};

export default function ToolStudioPage() {
  const { data: tools, isLoading, isError, refetch } = useTools();
  const selectedToolId = useStudioStore((s) => s.selectedToolId);
  const setSelectedTool = useStudioStore((s) => s.setSelectedTool);
  const setDirtyTool = useStudioStore((s) => s.setDirtyTool);

  const createTool = useCreateTool();
  const updateTool = useUpdateTool();
  const deleteTool = useDeleteTool();

  const [toolData, setToolData] = useState<ToolFormData | null>(null);
  const [isCreating, setIsCreating] = useState(false);

  const handleSelectTool = useCallback(
    (tool: Tool) => {
      setSelectedTool(String(tool.id));
      setIsCreating(false);
      setToolData({
        id: tool.id,
        tool_id: tool.tool_id,
        name: tool.name,
        description: tool.description ?? '',
        tool_type: normalizeToolType(tool.tool_type),
        domains: [],
        timeout_ms: 30000,
        max_retries: 3,
        status: tool.status,
        config: {
          endpoint: tool.endpoint ?? '',
          hostname: tool.hostname ?? '',
          auth_method: tool.auth_method ?? 'NONE',
          // Map endpoint to connection_string for Database config UI
          connection_string: tool.endpoint ?? '',
          // Map endpoint to base_url for API config UI
          base_url: tool.endpoint ?? '',
          ...(tool.auth_config ?? {}),
        },
        avg_latency_ms: tool.avg_latency_ms,
        success_rate: tool.success_rate,
        last_health_check: tool.last_health_check,
        is_dynamic: tool.is_dynamic,
      });
      setDirtyTool(false);
    },
    [setSelectedTool, setDirtyTool],
  );

  const handleCreateTool = useCallback(() => {
    setSelectedTool(null);
    setIsCreating(true);
    setToolData({ ...DEFAULT_TOOL });
    setDirtyTool(true);
  }, [setSelectedTool, setDirtyTool]);

  const handleDeleteTool = useCallback(() => {
    if (!toolData?.tool_id) {
      // Not yet persisted — just clear the editor
      setSelectedTool(null);
      setToolData(null);
      setIsCreating(false);
      setDirtyTool(false);
      return;
    }
    deleteTool.mutate(toolData.tool_id, {
      onSuccess: () => {
        setSelectedTool(null);
        setToolData(null);
        setIsCreating(false);
        setDirtyTool(false);
      },
    });
  }, [toolData, deleteTool, setSelectedTool, setDirtyTool]);

  const handleDuplicateTool = useCallback(() => {
    if (!toolData) return;
    setSelectedTool(null);
    setIsCreating(true);
    setToolData({
      ...toolData,
      id: undefined,
      tool_id: undefined,
      name: `${toolData.name} (Copy)`,
    });
    setDirtyTool(true);
  }, [toolData, setSelectedTool, setDirtyTool]);

  const handleSaveComplete = useCallback(() => {
    if (!toolData) return;

    if (isCreating) {
      createTool.mutate(
        {
          name: toolData.name,
          description: toolData.description,
          tool_type: toolData.tool_type,
          hostname: (toolData.config as Record<string, unknown>).hostname as string | undefined,
        },
        {
          onSuccess: (created) => {
            setDirtyTool(false);
            setIsCreating(false);
            setSelectedTool(String(created.id));
            setToolData({
              ...toolData,
              id: created.id,
              tool_id: created.tool_id,
            });
          },
        },
      );
    } else if (toolData.tool_id) {
      updateTool.mutate(
        {
          toolId: toolData.tool_id,
          payload: {
            name: toolData.name,
            description: toolData.description,
            tool_type: toolData.tool_type,
            status: toolData.status,
          },
        },
        {
          onSuccess: () => {
            setDirtyTool(false);
          },
        },
      );
    }
  }, [toolData, isCreating, createTool, updateTool, setDirtyTool, setSelectedTool]);

  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', height: '100%', gap: 2 }}>
        <Skeleton
          variant="rectangular"
          width={TOOL_LIST_WIDTH}
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
            Failed to load tools
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
      <ToolList
        tools={tools ?? []}
        selectedToolId={selectedToolId}
        isError={isError}
        onSelect={handleSelectTool}
        onCreate={handleCreateTool}
        onDuplicate={handleDuplicateTool}
        onDelete={handleDeleteTool}
        onRefetch={refetch}
      />
      <ToolEditor
        toolData={toolData}
        isCreating={isCreating}
        onChange={(data) => {
          setToolData(data);
          setDirtyTool(true);
        }}
        onSave={handleSaveComplete}
        onDelete={handleDeleteTool}
        onDuplicate={handleDuplicateTool}
      />
    </Box>
  );
}
