import React, { useState } from 'react';
import {
  Box,
  Typography,
  Chip,
  Collapse,
  IconButton,
  useTheme,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import CancelIcon from '@mui/icons-material/Cancel';
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty';
import type { ToolCall } from '@/types';

interface Props {
  toolCall: ToolCall;
}

const ToolCallCard: React.FC<Props> = ({ toolCall }) => {
  const theme = useTheme();
  const [expanded, setExpanded] = useState(false);

  const statusIcon =
    toolCall.status === 'success' ? (
      <CheckCircleIcon fontSize="small" sx={{ color: theme.palette.success.main }} />
    ) : toolCall.status === 'error' ? (
      <CancelIcon fontSize="small" sx={{ color: theme.palette.error.main }} />
    ) : (
      <HourglassEmptyIcon
        fontSize="small"
        sx={{
          color: theme.palette.info.main,
          animation: 'spin 1.5s linear infinite',
          '@keyframes spin': { '100%': { transform: 'rotate(360deg)' } },
        }}
      />
    );

  return (
    <Box
      sx={{
        border: 1,
        borderColor: 'divider',
        borderRadius: 1,
        mb: 1,
        overflow: 'hidden',
      }}
    >
      {/* Header */}
      <Box
        onClick={() => setExpanded((p) => !p)}
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 1,
          px: 1.5,
          py: 0.75,
          cursor: 'pointer',
          bgcolor: 'action.hover',
          '&:hover': { bgcolor: 'action.selected' },
        }}
      >
        {statusIcon}
        <Typography variant="body2" sx={{ fontWeight: 600, flex: 1 }}>
          {toolCall.tool_name}
        </Typography>
        <Chip label={toolCall.tool_type} size="small" variant="outlined" />
        <Typography variant="caption" sx={{ color: 'text.secondary' }}>
          {toolCall.latency_ms}ms
        </Typography>
        <IconButton
          size="small"
          sx={{
            transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)',
            transition: 'transform 0.2s',
          }}
        >
          <ExpandMoreIcon fontSize="small" />
        </IconButton>
      </Box>

      {/* Body */}
      <Collapse in={expanded}>
        <Box sx={{ px: 1.5, py: 1 }}>
          <Typography variant="caption" sx={{ fontWeight: 600, color: 'text.secondary' }}>
            Inputs
          </Typography>
          <Box
            component="pre"
            sx={{
              fontSize: '0.8rem',
              fontFamily: 'monospace',
              p: 1,
              borderRadius: 1,
              bgcolor: 'action.hover',
              overflow: 'auto',
              maxHeight: 200,
              my: 0.5,
            }}
          >
            {JSON.stringify(toolCall.inputs, null, 2)}
          </Box>

          <Typography variant="caption" sx={{ fontWeight: 600, color: 'text.secondary' }}>
            Outputs
          </Typography>
          <Box
            component="pre"
            sx={{
              fontSize: '0.8rem',
              fontFamily: 'monospace',
              p: 1,
              borderRadius: 1,
              bgcolor: 'action.hover',
              overflow: 'auto',
              maxHeight: 200,
              my: 0.5,
            }}
          >
            {JSON.stringify(toolCall.outputs, null, 2)}
          </Box>
        </Box>
      </Collapse>
    </Box>
  );
};

export default ToolCallCard;
