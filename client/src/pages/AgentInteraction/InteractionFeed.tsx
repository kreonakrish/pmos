import React, { useState, useCallback, useMemo, useRef, useEffect } from 'react';
import {
  Box,
  Typography,
  TextField,
  Button,
  Chip,
  Paper,
  InputAdornment,
  useTheme,
} from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import FileDownloadIcon from '@mui/icons-material/FileDownload';
import type { AgentInteraction } from '@/types';

/* ---- Type badge color ---- */

const TYPE_COLOR: Record<string, 'info' | 'success' | 'warning' | 'error' | 'secondary' | 'default'> = {
  task_assignment: 'info',
  tool_call: 'success',
  tool_result: 'success',
  score_evaluation: 'warning',
  score_request: 'warning',
  course_correction: 'warning',
  memory_read: 'secondary',
  memory_write: 'secondary',
  rag_query: 'secondary',
  error: 'error',
  fallback: 'error',
};

/* ---- Props ---- */

interface Props {
  interactions: AgentInteraction[];
  onSelect: (interaction: AgentInteraction) => void;
  selectedId?: string;
}

/* ---- Component ---- */

const InteractionFeed: React.FC<Props> = ({ interactions, onSelect, selectedId }) => {
  const theme = useTheme();
  const [filter, setFilter] = useState('');
  const listRef = useRef<HTMLDivElement>(null);

  const filtered = useMemo(() => {
    if (!filter.trim()) return interactions;
    const lower = filter.toLowerCase();
    return interactions.filter(
      (i) =>
        i.from_service.toLowerCase().includes(lower) ||
        i.to_service.toLowerCase().includes(lower) ||
        i.type.toLowerCase().includes(lower) ||
        (i.summary ?? '').toLowerCase().includes(lower),
    );
  }, [interactions, filter]);

  // Auto-scroll to bottom on new interactions
  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [interactions.length]);

  const handleExport = useCallback(() => {
    const blob = new Blob([JSON.stringify(interactions, null, 2)], {
      type: 'application/json',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'interactions.json';
    a.click();
    URL.revokeObjectURL(url);
  }, [interactions]);

  return (
    <Paper
      elevation={0}
      sx={{
        bgcolor: 'background.paper',
        borderTop: `1px solid ${theme.palette.divider}`,
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
      }}
    >
      {/* Toolbar */}
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 1,
          px: 2,
          py: 1,
          borderBottom: `1px solid ${theme.palette.divider}`,
        }}
      >
        <TextField
          size="small"
          placeholder="Filter by agent or type..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          sx={{ flex: 1, maxWidth: 320 }}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <SearchIcon fontSize="small" sx={{ color: 'text.secondary' }} />
              </InputAdornment>
            ),
          }}
        />
        <Button
          size="small"
          variant="outlined"
          startIcon={<FileDownloadIcon />}
          onClick={handleExport}
          sx={{ textTransform: 'none' }}
        >
          Export as JSON
        </Button>
      </Box>

      {/* Feed list */}
      <Box
        ref={listRef}
        sx={{
          flex: 1,
          overflow: 'auto',
        }}
      >
        {filtered.length === 0 && (
          <Box sx={{ p: 3, textAlign: 'center' }}>
            <Typography variant="body2" color="text.secondary">
              {filter ? 'No interactions match your filter.' : 'No interactions to display.'}
            </Typography>
          </Box>
        )}

        {filtered.map((interaction) => {
          const isSelected = interaction.id === selectedId;
          const chipColor = TYPE_COLOR[interaction.type] ?? 'default';
          const ts = new Date(interaction.timestamp);
          const timeStr = ts.toLocaleTimeString(undefined, {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
          });

          return (
            <Box
              key={interaction.id}
              sx={{
                display: 'flex',
                alignItems: 'center',
                gap: 1.5,
                px: 2,
                py: 0.75,
                borderBottom: `1px solid ${theme.palette.divider}`,
                cursor: 'pointer',
                bgcolor: isSelected ? theme.palette.action.selected : 'transparent',
                '&:hover': { bgcolor: theme.palette.action.hover },
                transition: 'background-color 0.1s',
              }}
              onClick={() => onSelect(interaction)}
            >
              {/* Timestamp */}
              <Typography
                variant="caption"
                sx={{
                  color: 'text.secondary',
                  fontFamily: 'monospace',
                  whiteSpace: 'nowrap',
                  minWidth: 70,
                }}
              >
                {timeStr}
              </Typography>

              {/* From -> To */}
              <Typography
                variant="caption"
                noWrap
                sx={{ fontWeight: 600, minWidth: 140, color: 'text.primary' }}
              >
                {interaction.from_service} &rarr; {interaction.to_service}
              </Typography>

              {/* Type badge */}
              <Chip
                label={interaction.type.replace(/_/g, ' ')}
                color={chipColor}
                size="small"
                sx={{ fontSize: '0.65rem', height: 20 }}
              />

              {/* Summary */}
              <Typography
                variant="caption"
                noWrap
                sx={{ flex: 1, color: 'text.secondary' }}
              >
                {interaction.summary ?? ''}
              </Typography>

              {/* Duration */}
              {interaction.duration_ms != null && (
                <Typography
                  variant="caption"
                  sx={{
                    color: 'text.secondary',
                    fontFamily: 'monospace',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {interaction.duration_ms}ms
                </Typography>
              )}
            </Box>
          );
        })}
      </Box>
    </Paper>
  );
};

export default InteractionFeed;
