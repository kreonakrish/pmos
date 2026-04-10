import React, { useState, useCallback } from 'react';
import {
  Box,
  Typography,
  Chip,
  Paper,
  IconButton,
  Collapse,
  Tooltip,
  useTheme,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import type { AgentInteraction } from '@/types';

/* ---- Type color map ---- */

const TYPE_CHIP_COLOR: Record<string, 'info' | 'success' | 'warning' | 'error' | 'secondary' | 'default'> = {
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
  sub_agent_spawn: 'warning',
  sub_agent_result: 'warning',
};

/* ---- JSON viewer ---- */

function JsonBlock({ label, data }: { label: string; data: Record<string, unknown> | undefined }) {
  const [open, setOpen] = useState(false);
  const theme = useTheme();

  if (!data) return null;

  return (
    <Box>
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 0.5,
          cursor: 'pointer',
          mb: 0.5,
        }}
        onClick={() => setOpen((prev) => !prev)}
      >
        {open ? (
          <ExpandLessIcon fontSize="small" sx={{ color: 'text.secondary' }} />
        ) : (
          <ExpandMoreIcon fontSize="small" sx={{ color: 'text.secondary' }} />
        )}
        <Typography variant="body2" sx={{ fontWeight: 600 }}>
          {label}
        </Typography>
      </Box>
      <Collapse in={open}>
        <Paper
          variant="outlined"
          sx={{
            p: 1.5,
            fontFamily: 'monospace',
            fontSize: '0.75rem',
            maxHeight: 200,
            overflow: 'auto',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-all',
            bgcolor:
              theme.palette.mode === 'dark'
                ? 'rgba(255, 255, 255, 0.03)'
                : 'rgba(0, 0, 0, 0.02)',
          }}
        >
          {JSON.stringify(data, null, 2)}
        </Paper>
      </Collapse>
    </Box>
  );
}

/* ---- Props ---- */

interface Props {
  interaction: AgentInteraction | null;
  onClose: () => void;
}

/* ---- Component ---- */

const InteractionDetail: React.FC<Props> = ({ interaction, onClose }) => {
  const theme = useTheme();
  const [copied, setCopied] = useState(false);

  const handleCopyTraceId = useCallback(() => {
    if (!interaction?.trace_id) return;
    navigator.clipboard.writeText(interaction.trace_id).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }, [interaction]);

  if (!interaction) return null;

  const chipColor = TYPE_CHIP_COLOR[interaction.type] ?? 'default';

  return (
    <Paper
      elevation={2}
      sx={{
        width: '100%',
        height: '100%',
        overflow: 'auto',
        bgcolor: 'background.paper',
        borderLeft: `1px solid ${theme.palette.divider}`,
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* Header */}
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          p: 2,
          borderBottom: `1px solid ${theme.palette.divider}`,
        }}
      >
        <Typography variant="h6" noWrap>
          Interaction Detail
        </Typography>
        <IconButton size="small" onClick={onClose}>
          <CloseIcon fontSize="small" />
        </IconButton>
      </Box>

      {/* Body */}
      <Box sx={{ p: 2.5, display: 'flex', flexDirection: 'column', gap: 2 }}>
        {/* From -> To */}
        <Box>
          <Typography variant="caption" sx={{ color: 'text.secondary' }}>
            Route
          </Typography>
          <Typography variant="body2" sx={{ fontWeight: 600 }}>
            {interaction.from_service} &rarr; {interaction.to_service}
          </Typography>
        </Box>

        {/* Type badge */}
        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
          <Chip
            label={interaction.type.replace(/_/g, ' ')}
            color={chipColor}
            size="small"
          />
        </Box>

        {/* Timestamp + Duration */}
        <Box sx={{ display: 'flex', gap: 3 }}>
          <Box>
            <Typography variant="caption" sx={{ color: 'text.secondary' }}>
              Timestamp
            </Typography>
            <Typography variant="body2">
              {new Date(interaction.timestamp).toLocaleString()}
            </Typography>
          </Box>
          {interaction.duration_ms != null && (
            <Box>
              <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                Duration
              </Typography>
              <Typography variant="body2">{interaction.duration_ms} ms</Typography>
            </Box>
          )}
        </Box>

        {/* Request payload */}
        <JsonBlock label="Request Payload" data={interaction.request_payload} />

        {/* Response payload */}
        <JsonBlock label="Response Payload" data={interaction.response_payload} />

        {/* Trace ID */}
        {interaction.trace_id && (
          <Box>
            <Typography variant="caption" sx={{ color: 'text.secondary' }}>
              Trace ID
            </Typography>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
              <Typography
                variant="body2"
                sx={{ fontFamily: 'monospace', fontSize: '0.75rem', wordBreak: 'break-all' }}
              >
                {interaction.trace_id}
              </Typography>
              <Tooltip title={copied ? 'Copied' : 'Copy'}>
                <IconButton size="small" onClick={handleCopyTraceId}>
                  <ContentCopyIcon sx={{ fontSize: 14 }} />
                </IconButton>
              </Tooltip>
            </Box>
          </Box>
        )}
      </Box>
    </Paper>
  );
};

export default InteractionDetail;
