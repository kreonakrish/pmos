import { useState } from 'react';
import {
  Box,
  Paper,
  Typography,
  Chip,
  Stack,
  Skeleton,
  IconButton,
  Collapse,
  Alert,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import Editor from '@monaco-editor/react';
import { useTheme } from '@mui/material/styles';
import { useToolExecutionHistory } from '@/api/tools';
import type { ToolExecutionResponse } from '@/api/tools';

interface HistoryPanelProps {
  toolId: string | undefined;
}

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function ExecutionRow({ execution }: { execution: ToolExecutionResponse }) {
  const theme = useTheme();
  const isDark = theme.palette.mode === 'dark';
  const [expanded, setExpanded] = useState(false);
  const isSuccess = execution.status === 'success';

  return (
    <Paper
      variant="outlined"
      sx={{
        borderLeft: 3,
        borderLeftColor: isSuccess ? 'success.main' : 'error.main',
        overflow: 'hidden',
      }}
    >
      {/* Summary row */}
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 1.5,
          px: 2,
          py: 1.2,
          cursor: 'pointer',
          '&:hover': { bgcolor: isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.02)' },
        }}
        onClick={() => setExpanded(!expanded)}
      >
        {isSuccess ? (
          <CheckCircleOutlineIcon sx={{ color: 'success.main', fontSize: 20 }} />
        ) : (
          <ErrorOutlineIcon sx={{ color: 'error.main', fontSize: 20 }} />
        )}

        <Typography variant="body2" sx={{ fontWeight: 500, minWidth: 140 }}>
          {formatTimestamp(execution.created_at)}
        </Typography>

        <Chip
          label={execution.status}
          size="small"
          color={isSuccess ? 'success' : 'error'}
          variant="outlined"
          sx={{ height: 22, fontSize: '0.72rem' }}
        />

        <Chip
          label={`${execution.latency_ms}ms`}
          size="small"
          variant="outlined"
          sx={{ height: 22, fontSize: '0.72rem' }}
        />

        <Chip
          label={execution.tool_type}
          size="small"
          variant="outlined"
          sx={{ height: 22, fontSize: '0.72rem' }}
        />

        {execution.agent_name && (
          <Chip
            label={execution.agent_name}
            size="small"
            color="primary"
            variant="outlined"
            sx={{ height: 22, fontSize: '0.72rem' }}
          />
        )}

        {execution.team_name && (
          <Chip
            label={execution.team_name}
            size="small"
            color="secondary"
            variant="outlined"
            sx={{ height: 22, fontSize: '0.72rem' }}
          />
        )}

        {execution.source && execution.source !== 'manual' && (
          <Chip
            label={execution.source}
            size="small"
            color="info"
            variant="outlined"
            sx={{ height: 22, fontSize: '0.72rem' }}
          />
        )}

        {!execution.agent_name && (
          <Chip
            label="manual"
            size="small"
            variant="outlined"
            sx={{ height: 22, fontSize: '0.72rem', color: 'text.secondary', borderColor: 'divider' }}
          />
        )}

        {execution.trace_id && (
          <Typography
            variant="caption"
            color="text.secondary"
            sx={{ ml: 'auto', fontFamily: 'monospace', fontSize: '0.7rem' }}
          >
            {execution.trace_id.slice(0, 8)}
          </Typography>
        )}

        <IconButton size="small" sx={{ ml: expanded ? 0 : 'auto' }}>
          {expanded ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
        </IconButton>
      </Box>

      {/* Expanded detail */}
      <Collapse in={expanded}>
        <Box sx={{ borderTop: 1, borderColor: 'divider' }}>
          {/* Tracing context bar */}
          {(execution.agent_name || execution.team_name || execution.conversation_id) && (
            <Box
              sx={{
                display: 'flex',
                gap: 3,
                px: 2,
                py: 1,
                bgcolor: isDark ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.015)',
                borderBottom: 1,
                borderColor: 'divider',
                fontSize: '0.8rem',
              }}
            >
              {execution.agent_name && (
                <Box>
                  <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>
                    Agent:{' '}
                  </Typography>
                  <Typography variant="caption">
                    {execution.agent_name}
                    {execution.agent_id && (
                      <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 0.5, fontFamily: 'monospace', fontSize: '0.68rem' }}>
                        ({execution.agent_id.slice(0, 8)})
                      </Typography>
                    )}
                  </Typography>
                </Box>
              )}
              {execution.team_name && (
                <Box>
                  <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>
                    Team:{' '}
                  </Typography>
                  <Typography variant="caption">
                    {execution.team_name}
                    {execution.team_id && (
                      <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 0.5, fontFamily: 'monospace', fontSize: '0.68rem' }}>
                        ({execution.team_id.slice(0, 8)})
                      </Typography>
                    )}
                  </Typography>
                </Box>
              )}
              {execution.conversation_id && (
                <Box>
                  <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>
                    Conversation:{' '}
                  </Typography>
                  <Typography variant="caption" sx={{ fontFamily: 'monospace', fontSize: '0.72rem' }}>
                    {execution.conversation_id.slice(0, 12)}...
                  </Typography>
                </Box>
              )}
            </Box>
          )}

          {execution.error_message && (
            <Alert severity="error" variant="outlined" sx={{ m: 1.5, fontSize: '0.82rem' }}>
              {execution.error_message}
            </Alert>
          )}

          <Stack direction={{ xs: 'column', md: 'row' }} spacing={0} sx={{ minHeight: 200 }}>
            {/* Inputs */}
            <Box sx={{ flex: 1, borderRight: { md: 1 }, borderColor: 'divider' }}>
              <Typography
                variant="caption"
                sx={{
                  display: 'block',
                  px: 2,
                  py: 0.75,
                  bgcolor: isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.03)',
                  fontWeight: 600,
                  textTransform: 'uppercase',
                  letterSpacing: 0.5,
                }}
              >
                Input
              </Typography>
              <Editor
                height={180}
                language="json"
                theme={isDark ? 'vs-dark' : 'light'}
                value={JSON.stringify(execution.inputs, null, 2) || '{}'}
                options={{
                  readOnly: true,
                  minimap: { enabled: false },
                  fontSize: 12,
                  lineNumbers: 'off',
                  scrollBeyondLastLine: false,
                  wordWrap: 'on',
                  tabSize: 2,
                  folding: true,
                }}
              />
            </Box>

            {/* Output */}
            <Box sx={{ flex: 1 }}>
              <Typography
                variant="caption"
                sx={{
                  display: 'block',
                  px: 2,
                  py: 0.75,
                  bgcolor: isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.03)',
                  fontWeight: 600,
                  textTransform: 'uppercase',
                  letterSpacing: 0.5,
                }}
              >
                Output
              </Typography>
              <Editor
                height={180}
                language="json"
                theme={isDark ? 'vs-dark' : 'light'}
                value={
                  execution.output
                    ? JSON.stringify(execution.output, null, 2)
                    : execution.error_message
                      ? JSON.stringify({ error: execution.error_message }, null, 2)
                      : '{}'
                }
                options={{
                  readOnly: true,
                  minimap: { enabled: false },
                  fontSize: 12,
                  lineNumbers: 'off',
                  scrollBeyondLastLine: false,
                  wordWrap: 'on',
                  tabSize: 2,
                  folding: true,
                }}
              />
            </Box>
          </Stack>
        </Box>
      </Collapse>
    </Paper>
  );
}

export default function HistoryPanel({ toolId }: HistoryPanelProps) {
  const { data, isLoading, isError } = useToolExecutionHistory(toolId);

  if (!toolId) {
    return (
      <Paper sx={{ p: 4, textAlign: 'center' }}>
        <Typography variant="body2" color="text.secondary">
          Save the tool first to see execution history.
        </Typography>
      </Paper>
    );
  }

  if (isLoading) {
    return (
      <Stack spacing={1.5}>
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} variant="rounded" height={52} />
        ))}
      </Stack>
    );
  }

  if (isError) {
    return (
      <Alert severity="error" variant="outlined">
        Failed to load execution history.
      </Alert>
    );
  }

  const executions = data?.executions ?? [];

  if (executions.length === 0) {
    return (
      <Paper sx={{ p: 4, textAlign: 'center' }}>
        <Typography variant="body2" color="text.secondary">
          No execution history yet. Run a test from the Test Panel to see results here.
        </Typography>
      </Paper>
    );
  }

  return (
    <Stack spacing={1}>
      <Stack direction="row" justifyContent="space-between" alignItems="center">
        <Typography variant="subtitle2">
          {data?.total ?? executions.length} execution{(data?.total ?? executions.length) !== 1 ? 's' : ''}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          Click a row to expand input/output details
        </Typography>
      </Stack>

      {executions.map((exec) => (
        <ExecutionRow key={exec.execution_id} execution={exec} />
      ))}
    </Stack>
  );
}
