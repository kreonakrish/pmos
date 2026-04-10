import { useState } from 'react';
import {
  Box,
  Typography,
  Paper,
  Chip,
  Stack,
  Skeleton,
  Alert,
  IconButton,
  Tooltip,
  LinearProgress,
  useTheme,
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import HourglassTopIcon from '@mui/icons-material/HourglassTop';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import { useJobs, useJobDetail } from '@/api/jobs';
import type { Job } from '@/api/jobs';

const STATUS_CONFIG: Record<string, { color: 'success' | 'error' | 'warning' | 'info' | 'default'; icon: React.ReactNode }> = {
  COMPLETED: { color: 'success', icon: <CheckCircleIcon fontSize="small" /> },
  COMPLETED_PARTIAL: { color: 'warning', icon: <WarningAmberIcon fontSize="small" /> },
  EXECUTING: { color: 'info', icon: <PlayArrowIcon fontSize="small" /> },
  CONSTRUCTING: { color: 'info', icon: <HourglassTopIcon fontSize="small" /> },
  FAILED: { color: 'error', icon: <ErrorIcon fontSize="small" /> },
  INTERRUPTED: { color: 'warning', icon: <WarningAmberIcon fontSize="small" /> },
};

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit',
    });
  } catch {
    return iso;
  }
}

function JobRow({ job }: { job: Job }) {
  const theme = useTheme();
  const isDark = theme.palette.mode === 'dark';
  const [expanded, setExpanded] = useState(false);
  const { data: detail } = useJobDetail(expanded ? job.graph_id : null);

  const statusCfg = STATUS_CONFIG[job.status] ?? { color: 'default' as const, icon: null };
  const total = job.total_nodes || 1;
  const progress = ((job.success_nodes + job.failed_nodes) / total) * 100;

  return (
    <Paper
      variant="outlined"
      sx={{
        borderLeft: 3,
        borderLeftColor: job.status === 'COMPLETED' ? 'success.main'
          : job.status === 'FAILED' ? 'error.main'
          : job.status === 'EXECUTING' ? 'info.main'
          : 'warning.main',
        overflow: 'hidden',
      }}
    >
      {/* Summary row */}
      <Box
        sx={{
          display: 'flex', alignItems: 'center', gap: 1.5,
          px: 2, py: 1.5, cursor: 'pointer',
          '&:hover': { bgcolor: isDark ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.015)' },
        }}
        onClick={() => setExpanded(!expanded)}
      >
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="body2" sx={{ fontWeight: 600 }} noWrap>
            {job.user_request || 'Untitled Job'}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {formatTime(job.created_at)}
            {job.conversation_id && ` | conv: ${job.conversation_id.slice(0, 8)}...`}
          </Typography>
        </Box>

        <Stack direction="row" spacing={0.5} alignItems="center" flexShrink={0}>
          <Chip icon={statusCfg.icon as React.ReactElement} label={job.status} size="small"
            color={statusCfg.color} variant="outlined" sx={{ height: 24, fontSize: '0.7rem' }} />
          <Chip label={`${job.success_nodes}/${job.total_nodes} tasks`} size="small"
            variant="outlined" sx={{ height: 24, fontSize: '0.7rem' }} />
          {job.avg_score != null && (
            <Chip label={`score: ${job.avg_score.toFixed(2)}`} size="small"
              variant="outlined" sx={{ height: 24, fontSize: '0.7rem' }} />
          )}
          {job.agents_used.length > 0 && (
            <Chip label={`${job.agents_used.length} agent${job.agents_used.length !== 1 ? 's' : ''}`}
              size="small" variant="outlined" color="primary" sx={{ height: 24, fontSize: '0.7rem' }} />
          )}
        </Stack>

        <IconButton size="small">
          {expanded ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
        </IconButton>
      </Box>

      {/* Progress bar */}
      {job.status === 'EXECUTING' && (
        <LinearProgress variant="determinate" value={progress}
          sx={{ height: 3, bgcolor: 'action.hover' }} />
      )}

      {/* Expanded detail */}
      {expanded && (
        <Box sx={{ borderTop: 1, borderColor: 'divider', p: 2 }}>
          {/* Agents used */}
          {job.agents_used.length > 0 && (
            <Box sx={{ mb: 2 }}>
              <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>
                Agents Used
              </Typography>
              <Stack direction="row" spacing={0.5} sx={{ mt: 0.5 }} flexWrap="wrap" useFlexGap>
                {job.agents_used.map((a) => (
                  <Chip key={a} label={a} size="small" color="primary" variant="outlined" />
                ))}
              </Stack>
            </Box>
          )}

          {/* Recovery note */}
          {job.recovery_note && (
            <Alert severity="warning" variant="outlined" sx={{ mb: 2, fontSize: '0.82rem' }}>
              {job.recovery_note}
            </Alert>
          )}

          {/* Task nodes table */}
          {detail?.nodes && detail.nodes.length > 0 && (
            <Box>
              <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600, mb: 1, display: 'block' }}>
                Task Nodes ({detail.nodes.length})
              </Typography>
              <Box sx={{ overflow: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
                  <thead>
                    <tr>
                      {['Status', 'Agent', 'Description', 'Confidence', 'Score', 'Duration'].map((h) => (
                        <th key={h} style={{
                          textAlign: 'left', padding: '6px 10px', fontWeight: 600,
                          borderBottom: `1px solid ${theme.palette.divider}`,
                          color: theme.palette.text.secondary, fontSize: '0.72rem',
                        }}>
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {detail.nodes.map((node) => {
                      const nStatusCfg = STATUS_CONFIG[node.status];
                      return (
                        <tr key={node.node_id}>
                          <td style={{ padding: '6px 10px' }}>
                            <Chip label={node.status} size="small"
                              color={nStatusCfg?.color ?? 'default'} variant="outlined"
                              sx={{ height: 20, fontSize: '0.65rem' }} />
                          </td>
                          <td style={{ padding: '6px 10px', fontWeight: 500 }}>
                            {node.assigned_agent_name || '-'}
                          </td>
                          <td style={{ padding: '6px 10px', maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {node.description}
                          </td>
                          <td style={{ padding: '6px 10px', fontFamily: 'monospace' }}>
                            {node.bid_confidence != null ? `${(node.bid_confidence * 100).toFixed(0)}%` : '-'}
                          </td>
                          <td style={{ padding: '6px 10px', fontFamily: 'monospace' }}>
                            {node.score != null ? node.score.toFixed(3) : '-'}
                          </td>
                          <td style={{ padding: '6px 10px', fontFamily: 'monospace' }}>
                            {node.execution_time_ms != null ? `${node.execution_time_ms}ms` : '-'}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </Box>
            </Box>
          )}

          {/* Stats summary */}
          <Stack direction="row" spacing={3} sx={{ mt: 2 }}>
            <Box>
              <Typography variant="caption" color="text.secondary">Success</Typography>
              <Typography variant="body2" sx={{ fontWeight: 600, color: 'success.main' }}>
                {job.success_nodes}
              </Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">Failed</Typography>
              <Typography variant="body2" sx={{ fontWeight: 600, color: 'error.main' }}>
                {job.failed_nodes}
              </Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">Pending</Typography>
              <Typography variant="body2" sx={{ fontWeight: 600, color: 'text.secondary' }}>
                {job.pending_nodes}
              </Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">Graph ID</Typography>
              <Typography variant="caption" sx={{ fontFamily: 'monospace' }}>
                {job.graph_id.slice(0, 12)}...
              </Typography>
            </Box>
          </Stack>
        </Box>
      )}
    </Paper>
  );
}

export default function JobsPage() {
  const { data: jobs, isLoading, isError, refetch } = useJobs();

  return (
    <Box sx={{ maxWidth: 1000, mx: 'auto' }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 3 }}>
        <Box>
          <Typography variant="h5" sx={{ fontWeight: 700 }}>
            Pipeline Jobs
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Execution history of all pipeline runs. Click to expand task details.
          </Typography>
        </Box>
        <Tooltip title="Refresh">
          <IconButton onClick={() => refetch()}>
            <RefreshIcon />
          </IconButton>
        </Tooltip>
      </Stack>

      {isLoading && (
        <Stack spacing={1.5}>
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} variant="rounded" height={64} />
          ))}
        </Stack>
      )}

      {isError && (
        <Alert severity="error" variant="outlined">
          Failed to load pipeline jobs.
        </Alert>
      )}

      {!isLoading && !isError && (!jobs || jobs.length === 0) && (
        <Paper sx={{ p: 4, textAlign: 'center' }}>
          <Typography color="text.secondary">
            No pipeline executions yet. Start a conversation to see jobs here.
          </Typography>
        </Paper>
      )}

      <Stack spacing={1}>
        {jobs?.map((job) => (
          <JobRow key={job.graph_id} job={job} />
        ))}
      </Stack>
    </Box>
  );
}
