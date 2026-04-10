import React, { useState, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Box,
  IconButton,
  Typography,
  Select,
  MenuItem,
  Collapse,
  Skeleton,
  useTheme,
} from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import type { SelectChangeEvent } from '@mui/material';
import type { TaskNode } from '@/types';

import { useConversationMessages } from '@/api/conversations';
import { useTaskDecomposition } from '@/api/decomposition';
import ErrorCard from '@/components/common/ErrorCard';
import EmptyState from '@/components/common/EmptyState';

import DecompositionTree from './DecompositionTree';
import TaskDetailPanel from './TaskDetailPanel';
import ExecutionGantt from './ExecutionGantt';

const TaskDecompositionPage: React.FC = () => {
  const { id: conversationId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const theme = useTheme();

  const [selectedMessageId, setSelectedMessageId] = useState<string | undefined>(undefined);
  const [selectedNode, setSelectedNode] = useState<TaskNode | null>(null);
  const [ganttOpen, setGanttOpen] = useState(true);

  const {
    data: messages,
    isLoading: msgsLoading,
  } = useConversationMessages(conversationId ?? null);

  const {
    data: decomposition,
    isLoading: decompLoading,
    isError: decompError,
    refetch: decompRefetch,
  } = useTaskDecomposition(conversationId, selectedMessageId);

  const isLoading = msgsLoading || decompLoading;

  const handleMessageChange = useCallback((e: SelectChangeEvent<string>) => {
    setSelectedMessageId(e.target.value || undefined);
    setSelectedNode(null);
  }, []);

  const handleNodeSelect = useCallback((node: TaskNode) => {
    setSelectedNode(node);
  }, []);

  const conversationTitle = messages && messages.length > 0
    ? messages.find((m) => m.role === 'user')?.content.slice(0, 60) ?? 'Conversation'
    : 'Conversation';

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 100px)' }}>
      {/* Top bar */}
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 1.5,
          px: 2,
          py: 1,
          borderBottom: `1px solid ${theme.palette.divider}`,
          bgcolor: 'background.paper',
          borderRadius: '12px 12px 0 0',
          flexWrap: 'wrap',
        }}
      >
        <IconButton size="small" onClick={() => navigate('/chat')}>
          <ArrowBackIcon fontSize="small" />
        </IconButton>

        <Typography
          variant="h6"
          noWrap
          sx={{ flex: 1, minWidth: 120 }}
        >
          {conversationTitle}
        </Typography>

        {/* Message selector */}
        <Select
          size="small"
          displayEmpty
          value={selectedMessageId ?? ''}
          onChange={handleMessageChange}
          sx={{ minWidth: 220, fontSize: '0.85rem' }}
        >
          <MenuItem value="">
            <em>All messages</em>
          </MenuItem>
          {messages?.filter((m) => m.role === 'user').map((m) => (
            <MenuItem key={m.id} value={m.id}>
              {m.content.length > 50 ? m.content.slice(0, 49) + '\u2026' : m.content}
            </MenuItem>
          ))}
        </Select>
      </Box>

      {/* Loading state */}
      {isLoading && (
        <Box sx={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Skeleton variant="rounded" width="80%" height="60%" />
        </Box>
      )}

      {/* Error state */}
      {decompError && !isLoading && (
        <Box sx={{ p: 3 }}>
          <ErrorCard
            message="Failed to load task decomposition data."
            onRetry={() => decompRefetch()}
          />
        </Box>
      )}

      {/* Empty state */}
      {!isLoading && !decompError && decomposition && decomposition.nodes.length === 0 && (
        <Box sx={{ flex: 1 }}>
          <EmptyState
            title="No task decomposition"
            description="This conversation has not generated any task nodes yet."
          />
        </Box>
      )}

      {/* Main content */}
      {!isLoading && !decompError && decomposition && decomposition.nodes.length > 0 && (
        <>
          {/* Split: Tree + Detail */}
          <Box sx={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0 }}>
            {/* Tree (60%) */}
            <Box sx={{ flex: 3, minWidth: 0 }}>
              <DecompositionTree
                nodes={decomposition.nodes}
                edges={decomposition.edges}
                onNodeSelect={handleNodeSelect}
                selectedNodeId={selectedNode?.task_id}
              />
            </Box>

            {/* Detail panel (40%) */}
            <Box sx={{ flex: 2, minWidth: 280, maxWidth: 480 }}>
              <TaskDetailPanel
                node={selectedNode}
                conversationId={conversationId ?? ''}
                onClose={() => setSelectedNode(null)}
              />
            </Box>
          </Box>

          {/* Gantt toggle */}
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 1,
              px: 2,
              py: 0.5,
              borderTop: `1px solid ${theme.palette.divider}`,
              bgcolor: 'background.paper',
              cursor: 'pointer',
            }}
            onClick={() => setGanttOpen((prev) => !prev)}
          >
            <Typography variant="body2" sx={{ fontWeight: 600, color: 'text.secondary' }}>
              Execution Timeline
            </Typography>
            {ganttOpen ? (
              <ExpandLessIcon fontSize="small" sx={{ color: 'text.secondary' }} />
            ) : (
              <ExpandMoreIcon fontSize="small" sx={{ color: 'text.secondary' }} />
            )}
          </Box>

          {/* Gantt chart (collapsible) */}
          <Collapse in={ganttOpen}>
            <Box sx={{ maxHeight: 260, overflow: 'auto' }}>
              <ExecutionGantt
                nodes={decomposition.nodes}
                onTaskSelect={handleNodeSelect}
                selectedNodeId={selectedNode?.task_id}
              />
            </Box>
          </Collapse>
        </>
      )}
    </Box>
  );
};

export default TaskDecompositionPage;
