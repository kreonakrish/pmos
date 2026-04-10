import React, { useState, useCallback, useMemo, useRef, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Box,
  IconButton,
  Typography,
  Select,
  MenuItem,
  Collapse,
  Skeleton,
  ToggleButton,
  ToggleButtonGroup,
  useTheme,
} from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import PauseIcon from '@mui/icons-material/Pause';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import FullscreenIcon from '@mui/icons-material/Fullscreen';
import FullscreenExitIcon from '@mui/icons-material/FullscreenExit';
import type { SelectChangeEvent } from '@mui/material';
import type { AgentInteraction } from '@/types';

import { useConversationMessages } from '@/api/conversations';
import { useAgents } from '@/api/agents';
import { useAgentInteractions } from '@/api/decomposition';
import ErrorCard from '@/components/common/ErrorCard';
import EmptyState from '@/components/common/EmptyState';

import SequenceDiagram from './SequenceDiagram';
import InteractionDetail from './InteractionDetail';
import InteractionFeed from './InteractionFeed';

const AgentInteractionPage: React.FC = () => {
  const { id: conversationId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const theme = useTheme();

  const [selectedMessageId, setSelectedMessageId] = useState<string | undefined>(undefined);
  const [selectedInteraction, setSelectedInteraction] = useState<AgentInteraction | null>(null);
  const [feedOpen, setFeedOpen] = useState(true);
  const [feedMaximized, setFeedMaximized] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [replaySpeed, setReplaySpeed] = useState('1');
  const [replayIdx, setReplayIdx] = useState<number | null>(null);
  const replayTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const { data: messages, isLoading: msgsLoading } = useConversationMessages(conversationId ?? null);
  const { data: agents } = useAgents();

  const {
    data: allInteractions,
    isLoading: intLoading,
    isError: intError,
    refetch: intRefetch,
  } = useAgentInteractions(conversationId, selectedMessageId, agents);

  const isLoading = msgsLoading || intLoading;
  const interactions = allInteractions ?? [];

  // Derive participants from interactions
  const participants = useMemo(() => {
    const set = new Set<string>();
    for (const i of interactions) {
      if (i.from_service) set.add(i.from_service);
      if (i.to_service) set.add(i.to_service);
    }
    // Filter out meaningless entries (raw UUIDs, empty, "task", "agent", "0")
    const isValidName = (n: string) =>
      n.length > 2 && !/^[0-9a-f]{8}$/.test(n) && !['task', 'agent', '0', 'unknown'].includes(n.toLowerCase());

    const arr = Array.from(set).filter(isValidName);

    // Order: Orchestrator first, then services, then agents alphabetically
    const priority: Record<string, number> = {
      Orchestrator: 0, orchestrator: 0,
      Scoring: 10, scoring: 10, 'Scoring Service': 10,
      Memory: 11, memory: 11, 'Memory Service': 11,
    };
    arr.sort((a, b) => {
      const pa = priority[a] ?? 50;
      const pb = priority[b] ?? 50;
      if (pa !== pb) return pa - pb;
      return a.localeCompare(b);
    });
    return arr;
  }, [interactions]);

  // Replay: show interactions one by one
  const visibleInteractions = useMemo(() => {
    if (replayIdx == null) return interactions;
    return interactions.slice(0, replayIdx + 1);
  }, [interactions, replayIdx]);

  // Replay timer
  useEffect(() => {
    if (!isPlaying || interactions.length === 0) return;

    const speed = parseFloat(replaySpeed);
    const baseDelay = 800;
    const delay = baseDelay / speed;

    const currentIdx = replayIdx ?? -1;
    if (currentIdx >= interactions.length - 1) {
      setIsPlaying(false);
      return;
    }

    replayTimerRef.current = setTimeout(() => {
      setReplayIdx((prev) => (prev == null ? 0 : Math.min(prev + 1, interactions.length - 1)));
    }, delay);

    return () => {
      if (replayTimerRef.current) clearTimeout(replayTimerRef.current);
    };
  }, [isPlaying, replayIdx, replaySpeed, interactions.length, interactions]);

  const handlePlay = useCallback(() => {
    if (replayIdx == null || replayIdx >= interactions.length - 1) {
      setReplayIdx(0);
    }
    setIsPlaying(true);
  }, [replayIdx, interactions.length]);

  const handlePause = useCallback(() => {
    setIsPlaying(false);
  }, []);

  const handleMessageChange = useCallback((e: SelectChangeEvent<string>) => {
    setSelectedMessageId(e.target.value || undefined);
    setSelectedInteraction(null);
    setReplayIdx(null);
    setIsPlaying(false);
  }, []);

  const handleInteractionSelect = useCallback((interaction: AgentInteraction) => {
    setSelectedInteraction(interaction);
  }, []);

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

        <Typography variant="h6" noWrap sx={{ minWidth: 100 }}>
          Agent Interactions
        </Typography>

        {/* Message selector */}
        <Select
          size="small"
          displayEmpty
          value={selectedMessageId ?? ''}
          onChange={handleMessageChange}
          sx={{ minWidth: 200, fontSize: '0.85rem' }}
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

        <Box sx={{ flex: 1 }} />

        {/* Replay controls */}
        <IconButton
          size="small"
          onClick={isPlaying ? handlePause : handlePlay}
          disabled={interactions.length === 0}
        >
          {isPlaying ? <PauseIcon fontSize="small" /> : <PlayArrowIcon fontSize="small" />}
        </IconButton>

        <ToggleButtonGroup
          value={replaySpeed}
          exclusive
          onChange={(_e, val) => { if (val) setReplaySpeed(val); }}
          size="small"
        >
          <ToggleButton value="1" sx={{ fontSize: '0.7rem', px: 1, py: 0.25 }}>
            1x
          </ToggleButton>
          <ToggleButton value="2" sx={{ fontSize: '0.7rem', px: 1, py: 0.25 }}>
            2x
          </ToggleButton>
          <ToggleButton value="5" sx={{ fontSize: '0.7rem', px: 1, py: 0.25 }}>
            5x
          </ToggleButton>
        </ToggleButtonGroup>
      </Box>

      {/* Loading state */}
      {isLoading && (
        <Box sx={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Skeleton variant="rounded" width="80%" height="60%" />
        </Box>
      )}

      {/* Error state */}
      {intError && !isLoading && (
        <Box sx={{ p: 3 }}>
          <ErrorCard
            message="Failed to load agent interactions."
            onRetry={() => intRefetch()}
          />
        </Box>
      )}

      {/* Empty state */}
      {!isLoading && !intError && interactions.length === 0 && (
        <Box sx={{ flex: 1 }}>
          <EmptyState
            title="No agent interactions"
            description="No inter-service communication has been recorded for this conversation yet."
          />
        </Box>
      )}

      {/* Main content */}
      {!isLoading && !intError && interactions.length > 0 && (
        <>
          {/* Split: Sequence diagram + Detail panel */}
          <Box sx={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0 }}>
            {/* Sequence diagram (70%) */}
            <Box sx={{ flex: 7, minWidth: 0 }}>
              <SequenceDiagram
                interactions={visibleInteractions}
                participants={participants}
                onInteractionSelect={handleInteractionSelect}
                selectedId={selectedInteraction?.id}
              />
            </Box>

            {/* Detail panel (30%) — slides in */}
            {selectedInteraction && (
              <Box sx={{ flex: 3, minWidth: 260, maxWidth: 400 }}>
                <InteractionDetail
                  interaction={selectedInteraction}
                  onClose={() => setSelectedInteraction(null)}
                />
              </Box>
            )}
          </Box>

          {/* Feed toggle header */}
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 1,
              px: 2,
              py: 0.5,
              borderTop: `1px solid ${theme.palette.divider}`,
              bgcolor: 'background.paper',
            }}
          >
            <Box
              sx={{ display: 'flex', alignItems: 'center', gap: 1, cursor: 'pointer', flex: 1 }}
              onClick={() => setFeedOpen((prev) => !prev)}
            >
              <Typography variant="body2" sx={{ fontWeight: 600, color: 'text.secondary' }}>
                Interaction Feed ({interactions.length})
              </Typography>
              {feedOpen ? (
                <ExpandLessIcon fontSize="small" sx={{ color: 'text.secondary' }} />
              ) : (
                <ExpandMoreIcon fontSize="small" sx={{ color: 'text.secondary' }} />
              )}
            </Box>
            {feedOpen && (
              <IconButton
                size="small"
                onClick={() => setFeedMaximized((prev) => !prev)}
                sx={{ color: 'text.secondary' }}
              >
                {feedMaximized ? <FullscreenExitIcon fontSize="small" /> : <FullscreenIcon fontSize="small" />}
              </IconButton>
            )}
          </Box>

          {/* Feed (collapsible + maximizable) */}
          <Collapse in={feedOpen}>
            <Box
              sx={{
                height: feedMaximized ? 'calc(100vh - 200px)' : 320,
                overflow: 'auto',
                display: 'flex',
                transition: 'height 0.3s ease',
              }}
            >
              <InteractionFeed
                interactions={interactions}
                onSelect={handleInteractionSelect}
                selectedId={selectedInteraction?.id}
              />
            </Box>
          </Collapse>
        </>
      )}
    </Box>
  );
};

export default AgentInteractionPage;
