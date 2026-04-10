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
import { useAgentExecutionHistory } from '@/api/agents';
import type { AgentExecutionResponse } from '@/api/agents';

interface HistoryTabProps {
  agentId: string | undefined;
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

function ExecutionRow({ execution }: { execution: AgentExecutionResponse }) {
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

        {execution.model && (
          <Chip
            label={execution.model}
            size="small"
            variant="outlined"
            sx={{ height: 22, fontSize: '0.72rem' }}
          />
        )}

        {execution.tokens_used && (
          <Chip
            label={`${execution.tokens_used} tok`}
            size="small"
            variant="outlined"
            sx={{ height: 22, fontSize: '0.72rem' }}
          />
        )}

        {execution.source && (
          <Chip
            label={execution.source}
            size="small"
            color={execution.source === 'pipeline' ? 'info' : 'default'}
            variant="outlined"
            sx={{ height: 22, fontSize: '0.72rem' }}
          />
        )}

        {execution.conversation_id && (
          <Chip
            label={`conv: ${execution.conversation_id.slice(0, 8)}`}
            size="small"
            variant="outlined"
            sx={{ height: 22, fontSize: '0.72rem', fontFamily: 'monospace' }}
          />
        )}

        <Box sx={{ ml: 'auto' }}>
          <IconButton size="small">
            {expanded ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
          </IconButton>
        </Box>
      </Box>

      {/* Expanded detail */}
      <Collapse in={expanded}>
        <Box sx={{ borderTop: 1, borderColor: 'divider' }}>
          {/* Context bar */}
          {(execution.team_name || execution.conversation_id) && (
            <Box
              sx={{
                display: 'flex',
                gap: 3,
                px: 2,
                py: 1,
                bgcolor: isDark ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.015)',
                borderBottom: 1,
                borderColor: 'divider',
              }}
            >
              {execution.team_name && (
                <Box>
                  <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>
                    Team:{' '}
                  </Typography>
                  <Typography variant="caption">{execution.team_name}</Typography>
                </Box>
              )}
              {execution.conversation_id && (
                <Box>
                  <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>
                    Conversation:{' '}
                  </Typography>
                  <Typography variant="caption" sx={{ fontFamily: 'monospace', fontSize: '0.72rem' }}>
                    {execution.conversation_id}
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
            {/* Prompt */}
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
                Prompt
              </Typography>
              <Editor
                height={180}
                language="markdown"
                theme={isDark ? 'vs-dark' : 'light'}
                value={execution.prompt || ''}
                options={{
                  readOnly: true,
                  minimap: { enabled: false },
                  fontSize: 12,
                  lineNumbers: 'off',
                  scrollBeyondLastLine: false,
                  wordWrap: 'on',
                  tabSize: 2,
                }}
              />
            </Box>

            {/* Response */}
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
                Response
              </Typography>
              <Editor
                height={180}
                language="markdown"
                theme={isDark ? 'vs-dark' : 'light'}
                value={
                  execution.response
                    || (execution.error_message ? `Error: ${execution.error_message}` : '')
                }
                options={{
                  readOnly: true,
                  minimap: { enabled: false },
                  fontSize: 12,
                  lineNumbers: 'off',
                  scrollBeyondLastLine: false,
                  wordWrap: 'on',
                  tabSize: 2,
                }}
              />
            </Box>
          </Stack>
        </Box>
      </Collapse>
    </Paper>
  );
}

export default function HistoryTab({ agentId }: HistoryTabProps) {
  const { data, isLoading, isError } = useAgentExecutionHistory(agentId);

  if (!agentId) {
    return (
      <Paper sx={{ p: 4, textAlign: 'center' }}>
        <Typography variant="body2" color="text.secondary">
          Save the agent first to see execution history.
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
          No execution history yet. Test the agent or wait for pipeline executions.
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
          Click a row to expand prompt/response details
        </Typography>
      </Stack>

      {executions.map((exec) => (
        <ExecutionRow key={exec.execution_id} execution={exec} />
      ))}
    </Stack>
  );
}
