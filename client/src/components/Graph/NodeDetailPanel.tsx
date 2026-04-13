import React from 'react';
import {
  Box,
  Typography,
  Chip,
  Divider,
  IconButton,
  Paper,
  useTheme,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import type { TaskNode, TaskNodeStatus } from '@/types';

interface Props {
  node: TaskNode | null;
  onClose: () => void;
}

function useStatusColor(status: TaskNodeStatus) {
  const theme = useTheme();
  const map: Record<TaskNodeStatus, string> = {
    PENDING: theme.palette.grey[500],
    RUNNING: theme.palette.info.main,
    SUCCESS: theme.palette.success.main,
    FAILED: theme.palette.error.main,
    CORRECTING: theme.palette.warning.main,
    SKIPPED: theme.palette.grey[400],
  };
  return map[status] ?? theme.palette.grey[500];
}

const ScoreBandBar: React.FC<{ score: number; low: number; high: number }> = ({
  score,
  low,
  high,
}) => {
  const theme = useTheme();
  const clamp = (v: number) => Math.max(0, Math.min(1, v));
  return (
    <Box sx={{ position: 'relative', height: 12, borderRadius: 1, bgcolor: 'action.hover', my: 1 }}>
      {/* Band region */}
      <Box
        sx={{
          position: 'absolute',
          left: `${clamp(low) * 100}%`,
          width: `${(clamp(high) - clamp(low)) * 100}%`,
          height: '100%',
          borderRadius: 1,
          bgcolor: theme.palette.success.light,
          opacity: 0.3,
        }}
      />
      {/* Low marker */}
      <Box
        sx={{
          position: 'absolute',
          left: `${clamp(low) * 100}%`,
          top: -2,
          width: 2,
          height: 16,
          bgcolor: theme.palette.warning.main,
        }}
      />
      {/* High marker */}
      <Box
        sx={{
          position: 'absolute',
          left: `${clamp(high) * 100}%`,
          top: -2,
          width: 2,
          height: 16,
          bgcolor: theme.palette.success.main,
        }}
      />
      {/* Score dot */}
      <Box
        sx={{
          position: 'absolute',
          left: `${clamp(score) * 100}%`,
          top: '50%',
          transform: 'translate(-50%, -50%)',
          width: 10,
          height: 10,
          borderRadius: '50%',
          bgcolor: 'primary.main',
          border: 2,
          borderColor: 'background.paper',
        }}
      />
    </Box>
  );
};

const NodeDetailPanel: React.FC<Props> = ({ node, onClose }) => {
  const statusColor = useStatusColor(node?.status ?? 'PENDING');

  if (!node) return null;

  return (
    <Paper
      elevation={4}
      sx={{
        width: 340,
        height: '100%',
        overflow: 'auto',
        borderLeft: 1,
        borderColor: 'divider',
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
          borderBottom: 1,
          borderColor: 'divider',
        }}
      >
        <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
          Task Details
        </Typography>
        <IconButton size="small" onClick={onClose}>
          <CloseIcon fontSize="small" />
        </IconButton>
      </Box>

      {/* Body */}
      <Box sx={{ p: 2, flex: 1 }}>
        {/* ID */}
        <Typography variant="caption" color="text.secondary">
          Task ID
        </Typography>
        <Typography variant="body2" sx={{ mb: 1.5, fontFamily: 'monospace' }}>
          {(() => {
            const id = node.task_id || node.node_id || '';
            return id.length > 24 ? id.slice(0, 12) + '...' + id.slice(-8) : id;
          })()}
        </Typography>

        {/* Description */}
        <Typography variant="caption" color="text.secondary">
          Description
        </Typography>
        <Typography variant="body2" sx={{ mb: 1.5 }}>
          {node.description}
        </Typography>

        {/* Status */}
        <Typography variant="caption" color="text.secondary">
          Status
        </Typography>
        <Box sx={{ mb: 1.5 }}>
          <Chip
            label={node.status}
            size="small"
            sx={{
              bgcolor: statusColor,
              color: '#fff',
              fontWeight: 600,
            }}
          />
        </Box>

        {/* Agent */}
        {(node.agent_name || node.assigned_agent_name) && (
          <>
            <Typography variant="caption" color="text.secondary">
              Assigned Agent
            </Typography>
            <Typography variant="body2" sx={{ mb: 1.5 }}>
              {node.agent_name || node.assigned_agent_name}
            </Typography>
          </>
        )}

        <Divider sx={{ my: 1.5 }} />

        {/* Score + band */}
        {node.score != null && (
          <>
            <Typography variant="caption" color="text.secondary">
              Score
            </Typography>
            <Typography variant="h6" sx={{ mb: 0.5 }}>
              {node.score.toFixed(3)}
            </Typography>
            {node.band && (
              <ScoreBandBar score={node.score} low={node.band.low} high={node.band.high} />
            )}
          </>
        )}

        {/* Criticality */}
        {node.criticality && (
          <>
            <Typography variant="caption" color="text.secondary" sx={{ mt: 1 }}>
              Criticality
            </Typography>
            <Box sx={{ mb: 1.5 }}>
              <Chip
                label={node.criticality.toUpperCase()}
                size="small"
                color={
                  node.criticality === 'critical'
                    ? 'error'
                    : node.criticality === 'high'
                      ? 'warning'
                      : 'default'
                }
                variant="outlined"
              />
            </Box>
          </>
        )}

        {/* Execution time */}
        {node.execution_time_ms != null && (
          <>
            <Typography variant="caption" color="text.secondary">
              Execution Time
            </Typography>
            <Typography variant="body2" sx={{ mb: 1.5 }}>
              {node.execution_time_ms}ms
            </Typography>
          </>
        )}

        {/* Iteration */}
        {node.iteration != null && (
          <>
            <Typography variant="caption" color="text.secondary">
              Iteration
            </Typography>
            <Typography variant="body2" sx={{ mb: 1.5 }}>
              {node.iteration}
            </Typography>
          </>
        )}

        {/* Correction history */}
        {node.correction_history && node.correction_history.length > 0 && (
          <>
            <Divider sx={{ my: 1.5 }} />
            <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>
              Correction History
            </Typography>
            {node.correction_history.map((entry, idx) => (
              <Box
                key={idx}
                sx={{
                  mt: 1,
                  p: 1,
                  borderRadius: 1,
                  bgcolor: 'action.hover',
                }}
              >
                <Typography variant="caption" color="text.secondary">
                  {new Date(entry.timestamp).toLocaleString()}
                </Typography>
                <Typography variant="body2">
                  {entry.from_agent} → {entry.to_agent}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {entry.reason}
                </Typography>
              </Box>
            ))}
          </>
        )}
      </Box>
    </Paper>
  );
};

export default NodeDetailPanel;
