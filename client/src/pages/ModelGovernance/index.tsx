import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Box,
  Typography,
  Paper,
  Grid,
  TextField,
  InputAdornment,
  List,
  ListItemButton,
  ListItemText,
  Chip,
  Divider,
  Stack,
  Skeleton,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Tooltip,
  Alert,
} from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import VerifiedUserIcon from '@mui/icons-material/VerifiedUser';
import PolicyIcon from '@mui/icons-material/Policy';
import {
  useGovernanceTraces,
  useGovernanceTrace,
  TimelineEntry,
} from '@/api/governance';

const LAYER_COLORS: Record<TimelineEntry['layer'], string> = {
  USER_MESSAGE: '#1976d2',
  TASK_NODE: '#7b1fa2',
  PIPELINE_STEP: '#0288d1',
  TOOL_CALL: '#388e3c',
  SCORING: '#ed6c02',
  RL_FEEDBACK: '#c62828',
  AGENT_INTERACTION: '#5d4037',
  ASSISTANT_RESPONSE: '#2e7d32',
};

const LAYER_LABEL: Record<TimelineEntry['layer'], string> = {
  USER_MESSAGE: 'User',
  TASK_NODE: 'TaskNode',
  PIPELINE_STEP: 'Pipeline',
  TOOL_CALL: 'Tool',
  SCORING: 'Score',
  RL_FEEDBACK: 'RL',
  AGENT_INTERACTION: 'Interaction',
  ASSISTANT_RESPONSE: 'Response',
};

function fmtScore(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—';
  return Number(n).toFixed(2);
}

function fmtTs(ts: string | null | undefined): string {
  if (!ts) return '';
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return String(ts);
  }
}

function renderDetail(detail: unknown): JSX.Element {
  if (detail === null || detail === undefined) return <span style={{ opacity: 0.6 }}>(empty)</span>;
  if (typeof detail === 'string') {
    return (
      <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit' }}>
        {detail}
      </Typography>
    );
  }
  return (
    <Box
      component="pre"
      sx={{
        m: 0,
        p: 1,
        fontSize: 11.5,
        bgcolor: (t) => (t.palette.mode === 'dark' ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)'),
        borderRadius: 1,
        overflowX: 'auto',
        maxHeight: 400,
      }}
    >
      {JSON.stringify(detail, null, 2)}
    </Box>
  );
}

export default function ModelGovernancePage() {
  const [searchParams] = useSearchParams();
  const [search, setSearch] = useState('');
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);
  const [manualTraceId, setManualTraceId] = useState('');

  // Deep-link support: /model-governance?trace=<uuid> auto-selects the trace.
  useEffect(() => {
    const t = searchParams.get('trace');
    if (t && t !== selectedTraceId) {
      setSelectedTraceId(t);
      setManualTraceId(t);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  const tracesQuery = useGovernanceTraces(50);
  const traces = tracesQuery.data?.traces ?? [];

  const filteredTraces = useMemo(() => {
    if (!search.trim()) return traces;
    const q = search.trim().toLowerCase();
    return traces.filter((t) => {
      return (
        (t.trace_id || '').toLowerCase().includes(q) ||
        (t.conversation_id || '').toLowerCase().includes(q) ||
        (t.user_request || '').toLowerCase().includes(q) ||
        (t.assistant_response || '').toLowerCase().includes(q)
      );
    });
  }, [traces, search]);

  const effectiveTraceId =
    selectedTraceId ?? (filteredTraces.length > 0 ? filteredTraces[0].trace_id : null);

  const traceQuery = useGovernanceTrace(effectiveTraceId);
  const trace = traceQuery.data;

  return (
    <Box>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
        <PolicyIcon color="primary" />
        <Typography variant="h5" fontWeight={600}>
          Model Governance
        </Typography>
        <Chip label="Inference traceability" size="small" variant="outlined" />
      </Stack>

      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        For any answer the system has produced, drill into how it was derived: the user
        request, the agents that bid and were selected, the tools they invoked, the RAG
        retrievals, the scoring decisions and band checks, the reinforcement-learning
        feedback, and the resulting Neo4j TaskGraph hops — all aligned on a single timeline.
      </Typography>

      <Grid container spacing={2}>
        {/* Left rail — trace list */}
        <Grid item xs={12} md={4}>
          <Paper sx={{ p: 2, height: 'calc(100vh - 220px)', display: 'flex', flexDirection: 'column' }}>
            <TextField
              fullWidth
              size="small"
              placeholder="Search traces…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              InputProps={{
                startAdornment: (
                  <InputAdornment position="start">
                    <SearchIcon fontSize="small" />
                  </InputAdornment>
                ),
              }}
              sx={{ mb: 1 }}
            />
            <TextField
              fullWidth
              size="small"
              placeholder="Or paste a specific trace_id…"
              value={manualTraceId}
              onChange={(e) => setManualTraceId(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && manualTraceId.trim()) {
                  setSelectedTraceId(manualTraceId.trim());
                }
              }}
              sx={{ mb: 1 }}
            />
            <Divider sx={{ mb: 1 }} />
            <Box sx={{ flex: 1, overflowY: 'auto' }}>
              {tracesQuery.isLoading ? (
                <>
                  <Skeleton height={56} />
                  <Skeleton height={56} />
                  <Skeleton height={56} />
                </>
              ) : filteredTraces.length === 0 ? (
                <Typography variant="body2" color="text.secondary" sx={{ p: 2 }}>
                  No traces found. Once a conversation runs through the orchestrator, it
                  will show up here.
                </Typography>
              ) : (
                <List dense disablePadding>
                  {filteredTraces.map((t) => {
                    const active = effectiveTraceId === t.trace_id;
                    return (
                      <ListItemButton
                        key={t.trace_id}
                        selected={active}
                        onClick={() => setSelectedTraceId(t.trace_id)}
                        sx={{ borderRadius: 1, mb: 0.5 }}
                      >
                        <ListItemText
                          primary={
                            <Stack direction="row" spacing={1} alignItems="center">
                              <Typography
                                variant="body2"
                                sx={{ fontFamily: 'monospace', fontSize: 11 }}
                              >
                                {t.trace_id?.slice(0, 8)}…
                              </Typography>
                              {t.avg_score !== null && t.avg_score !== undefined && (
                                <Chip
                                  size="small"
                                  label={fmtScore(t.avg_score)}
                                  sx={{ height: 18, fontSize: 10 }}
                                />
                              )}
                              {t.tool_call_count ? (
                                <Chip
                                  size="small"
                                  variant="outlined"
                                  label={`${t.tool_call_count} tools`}
                                  sx={{ height: 18, fontSize: 10 }}
                                />
                              ) : null}
                            </Stack>
                          }
                          secondary={
                            <Tooltip title={t.user_request ?? ''} placement="right">
                              <Typography
                                variant="caption"
                                color="text.secondary"
                                sx={{
                                  display: '-webkit-box',
                                  WebkitLineClamp: 2,
                                  WebkitBoxOrient: 'vertical',
                                  overflow: 'hidden',
                                }}
                              >
                                {t.user_request ?? '(no user message)'}
                              </Typography>
                            </Tooltip>
                          }
                        />
                      </ListItemButton>
                    );
                  })}
                </List>
              )}
            </Box>
          </Paper>
        </Grid>

        {/* Right pane — trace detail */}
        <Grid item xs={12} md={8}>
          <Paper sx={{ p: 2, height: 'calc(100vh - 220px)', overflowY: 'auto' }}>
            {!effectiveTraceId ? (
              <Alert severity="info">Select a trace from the left to see its reasoning chain.</Alert>
            ) : traceQuery.isLoading ? (
              <>
                <Skeleton height={120} />
                <Skeleton height={60} />
                <Skeleton height={60} />
                <Skeleton height={60} />
              </>
            ) : traceQuery.isError ? (
              <Alert severity="error">
                Failed to load trace: {(traceQuery.error as Error)?.message}
              </Alert>
            ) : !trace ? (
              <Alert severity="warning">No data for this trace.</Alert>
            ) : (
              <TraceDetailView trace={trace} />
            )}
          </Paper>
        </Grid>
      </Grid>
    </Box>
  );
}

function TraceDetailView({ trace }: { trace: NonNullable<ReturnType<typeof useGovernanceTrace>['data']> }) {
  const s = trace.summary;
  return (
    <Box>
      {/* Summary banner */}
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
        <VerifiedUserIcon color="success" fontSize="small" />
        <Typography variant="subtitle1" fontWeight={600}>
          Reasoning chain
        </Typography>
        <Chip
          size="small"
          label={`trace ${s.trace_id.slice(0, 8)}…`}
          sx={{ fontFamily: 'monospace', fontSize: 11 }}
        />
        {s.final_score !== null && s.final_score !== undefined && (
          <Chip
            size="small"
            color={s.final_score >= 0.7 ? 'success' : s.final_score >= 0.5 ? 'warning' : 'error'}
            label={`final score ${fmtScore(s.final_score)}`}
          />
        )}
      </Stack>

      <Grid container spacing={1} sx={{ mb: 2 }}>
        <SummaryStat label="Messages" value={s.n_messages} />
        <SummaryStat label="Task nodes" value={s.n_task_nodes} />
        <SummaryStat label="Pipeline steps" value={s.n_pipeline_steps} />
        <SummaryStat label="Tool calls" value={s.n_tool_calls} />
        <SummaryStat label="Score records" value={s.n_score_records} />
        <SummaryStat label="RL feedback" value={s.n_rl_feedback} />
      </Grid>

      {(s.tools_used.length > 0 || s.agents_involved.length > 0) && (
        <Box sx={{ mb: 2 }}>
          {s.agents_involved.length > 0 && (
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5, flexWrap: 'wrap' }}>
              <Typography variant="caption" color="text.secondary">
                Agents:
              </Typography>
              {s.agents_involved.map((a) => (
                <Chip key={a} size="small" label={a} sx={{ height: 20, fontSize: 11 }} />
              ))}
            </Stack>
          )}
          {s.tools_used.length > 0 && (
            <Stack direction="row" spacing={1} alignItems="center" sx={{ flexWrap: 'wrap' }}>
              <Typography variant="caption" color="text.secondary">
                Tools:
              </Typography>
              {s.tools_used.map((t) => (
                <Chip
                  key={t}
                  size="small"
                  variant="outlined"
                  color="success"
                  label={t}
                  sx={{ height: 20, fontSize: 11 }}
                />
              ))}
            </Stack>
          )}
        </Box>
      )}

      <Divider sx={{ mb: 2 }} />

      {/* Timeline */}
      <Typography variant="subtitle2" sx={{ mb: 1 }}>
        Timeline ({trace.timeline.length} hops)
      </Typography>

      {trace.timeline.length === 0 ? (
        <Alert severity="info">
          No hops recorded for this trace. The conversation may have failed before any
          agent ran, or the trace_id is from a flow that bypassed the orchestrator pipeline.
        </Alert>
      ) : (
        trace.timeline.map((entry, idx) => <TimelineRow key={idx} entry={entry} index={idx} />)
      )}
    </Box>
  );
}

function SummaryStat({ label, value }: { label: string; value: number }) {
  return (
    <Grid item xs={6} sm={4} md={2}>
      <Paper variant="outlined" sx={{ p: 1, textAlign: 'center' }}>
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
          {label}
        </Typography>
        <Typography variant="h6" fontWeight={600}>
          {value}
        </Typography>
      </Paper>
    </Grid>
  );
}

function TimelineRow({ entry, index }: { entry: TimelineEntry; index: number }) {
  const color = LAYER_COLORS[entry.layer] || '#666';
  return (
    <Accordion
      defaultExpanded={index < 3}
      disableGutters
      sx={{
        mb: 1,
        borderLeft: `3px solid ${color}`,
        '&:before': { display: 'none' },
      }}
    >
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Stack direction="row" spacing={1} alignItems="center" sx={{ width: '100%' }}>
          <Chip
            label={LAYER_LABEL[entry.layer]}
            size="small"
            sx={{
              bgcolor: color,
              color: 'white',
              fontWeight: 600,
              fontSize: 10,
              height: 20,
              minWidth: 70,
            }}
          />
          <Typography variant="body2" sx={{ flex: 1, fontWeight: 500 }}>
            {entry.title}
          </Typography>
          {entry.agent && (
            <Chip
              size="small"
              variant="outlined"
              label={entry.agent}
              sx={{ height: 20, fontSize: 10 }}
            />
          )}
          {entry.score !== null && entry.score !== undefined && (
            <Chip
              size="small"
              color={entry.score >= 0.7 ? 'success' : entry.score >= 0.5 ? 'warning' : 'error'}
              label={fmtScore(entry.score)}
              sx={{ height: 20, fontSize: 10 }}
            />
          )}
          {entry.latency_ms !== undefined && entry.latency_ms !== null && (
            <Chip
              size="small"
              variant="outlined"
              label={`${entry.latency_ms}ms`}
              sx={{ height: 20, fontSize: 10 }}
            />
          )}
          <Typography variant="caption" color="text.secondary" sx={{ minWidth: 130, textAlign: 'right' }}>
            {fmtTs(entry.ts)}
          </Typography>
        </Stack>
      </AccordionSummary>
      <AccordionDetails>
        <Stack direction="row" spacing={1} sx={{ mb: 1 }}>
          <Chip
            size="small"
            variant="outlined"
            label={`source: ${entry.source}`}
            sx={{ height: 18, fontSize: 10 }}
          />
          {entry.ref_id && (
            <Chip
              size="small"
              variant="outlined"
              label={`ref: ${entry.ref_id}`}
              sx={{ height: 18, fontSize: 10, fontFamily: 'monospace' }}
            />
          )}
          {entry.status && (
            <Chip
              size="small"
              variant="outlined"
              label={entry.status}
              sx={{ height: 18, fontSize: 10 }}
            />
          )}
        </Stack>
        {renderDetail(entry.detail)}
      </AccordionDetails>
    </Accordion>
  );
}
