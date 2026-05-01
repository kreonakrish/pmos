// Decomposition Timeline (Phase A.7)
//
// Renders a chronological timeline of pipeline events for a single
// conversation. Pinned at the top: the initial decomposition
// (decomposition.created). Each subsequent round shows the sufficiency
// verdict, the gap list, the revised sub-tasks, and per-node activity
// (bids, agent iterations, tool calls, scores). The final round is marked
// "Accepted as complete" (green) when the sufficiency judge returns
// sufficient=true; otherwise "Cap reached" (amber).
//
// Modes:
//   - Live: opens an SSE stream against the gateway and appends events.
//   - Replay: fetches the conversation's events from MySQL.
// The page selects live mode by default and falls back to replay if the
// stream closes within 5s without producing any events (i.e. the
// conversation has already finished).

import { useEffect, useMemo, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  Box,
  Typography,
  Paper,
  Chip,
  Stack,
  Divider,
  Alert,
  IconButton,
  Tooltip,
  Skeleton,
  useTheme,
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import HourglassTopIcon from '@mui/icons-material/HourglassTop';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import {
  replayTimeline,
  streamTimeline,
  type TimelineEvent,
  type StreamHandle,
} from '@/api/timeline';
import { listFeedback, type FeedbackRow } from '@/api/feedback';

// ──────────────────────────────────────────────────────────────────────────────
// Status → color mapping per the observability contract in the plan.
// ──────────────────────────────────────────────────────────────────────────────

function statusToColor(
  status: string,
): 'default' | 'info' | 'warning' | 'success' | 'error' {
  const s = (status || '').toUpperCase();
  if (s === 'COMPLETE' || s === 'SUCCESS') return 'success';
  if (s === 'BELOW_BAND') return 'warning';
  if (s === 'DEVIATED') return 'info';
  if (s === 'ERROR') return 'error';
  return 'default';
}

function kindLabel(kind: string): string {
  // Make event kinds human-readable for headers.
  return kind
    .replace('decomposition.created', 'Initial decomposition')
    .replace('decomposition.revised', 'Decomposition revised')
    .replace('sufficiency.checked', 'Sufficiency check')
    .replace('pipeline.completed', 'Pipeline completed')
    .replace('bid.opened', 'Bid opened')
    .replace('bid.closed', 'Bid closed')
    .replace('agent.iteration', 'Agent iteration')
    .replace('tool.call', 'Tool call')
    .replace('tool.result', 'Tool result')
    .replace('score.evaluated', 'Score evaluated')
    .replace('memory.refreshed', 'Memory refresh')
    .replace('auto_correct.triggered', 'Auto-correct triggered')
    .replace('auto_correct.completed', 'Auto-correct completed')
    .replace('subagent.spawned', 'Sub-agent spawned')
    .replace('subagent.refused', 'Sub-agent refused')
    .replace('memory.written', 'Memory written')
    .replace('ml.rationale', 'ML rationale');
}

// ──────────────────────────────────────────────────────────────────────────────
// Group events by round so the timeline can stack rounds vertically.
// Round 1 = initial decomposition + initial execution.
// Round N>1 = sufficiency.checked → decomposition.revised → bids → executions.
// ──────────────────────────────────────────────────────────────────────────────

interface Round {
  roundN: number;
  events: TimelineEvent[];
  initial?: TimelineEvent;
  sufficiency?: TimelineEvent;
  revision?: TimelineEvent;
}

function groupByRound(events: TimelineEvent[]): Round[] {
  const map = new Map<number, Round>();
  for (const e of events) {
    if (e.kind === 'pipeline.completed') continue; // rendered separately
    const r = e.round ?? (e.kind === 'decomposition.created' ? 1 : 1);
    if (!map.has(r)) map.set(r, { roundN: r, events: [] });
    const round = map.get(r)!;
    round.events.push(e);
    if (e.kind === 'decomposition.created') round.initial = e;
    if (e.kind === 'sufficiency.checked') round.sufficiency = e;
    if (e.kind === 'decomposition.revised') round.revision = e;
  }
  return Array.from(map.values()).sort((a, b) => a.roundN - b.roundN);
}

// ──────────────────────────────────────────────────────────────────────────────
// Sub-views
// ──────────────────────────────────────────────────────────────────────────────

function InitialDecompositionPanel({ ev }: { ev: TimelineEvent }) {
  const subtasks = (ev.payload?.subtasks as string[]) ?? [];
  const intent = (ev.payload?.intent as string) ?? '';
  return (
    <Paper variant="outlined" sx={{ p: 2, borderLeft: 4, borderLeftColor: 'primary.main' }}>
      <Stack direction="row" alignItems="center" spacing={1}>
        <Chip
          label="INITIAL"
          size="small"
          color="primary"
          sx={{ fontWeight: 700 }}
        />
        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
          {kindLabel(ev.kind)}
        </Typography>
        {intent && (
          <Chip
            label={`intent: ${intent}`}
            size="small"
            variant="outlined"
          />
        )}
      </Stack>
      <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>
        Pinned — this is the team's original plan. Later rounds extend or revise it.
      </Typography>
      <Box sx={{ mt: 1.5 }}>
        {subtasks.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            (no sub-tasks recorded)
          </Typography>
        ) : (
          <Stack spacing={0.5}>
            {subtasks.map((s, i) => (
              <Box key={i} sx={{ display: 'flex', gap: 1 }}>
                <Typography variant="caption" sx={{ minWidth: 24, color: 'text.secondary' }}>
                  {i + 1}.
                </Typography>
                <Typography variant="body2">{s}</Typography>
              </Box>
            ))}
          </Stack>
        )}
      </Box>
    </Paper>
  );
}

function SufficiencyPanel({ ev }: { ev: TimelineEvent }) {
  const sufficient = Boolean(ev.payload?.sufficient);
  const gaps = (ev.payload?.gaps as string[]) ?? [];
  const reason = (ev.payload?.reason as string) ?? '';
  const avg = ev.payload?.avg_score as number | undefined;
  const below = ev.payload?.below_band_count as number | undefined;
  return (
    <Paper
      variant="outlined"
      sx={{
        p: 1.5,
        borderLeft: 4,
        borderLeftColor: sufficient ? 'success.main' : 'info.main',
      }}
    >
      <Stack direction="row" alignItems="center" spacing={1}>
        <Chip
          label={sufficient ? 'ACCEPTED AS COMPLETE' : 'INSUFFICIENT'}
          size="small"
          color={sufficient ? 'success' : 'info'}
          sx={{ fontWeight: 700 }}
          icon={sufficient ? <CheckCircleIcon /> : <HourglassTopIcon />}
        />
        <Typography variant="caption" color="text.secondary">
          Sufficiency judge
        </Typography>
        {avg !== undefined && (
          <Chip
            label={`avg score ${avg?.toFixed?.(2) ?? avg}`}
            size="small"
            variant="outlined"
          />
        )}
        {below !== undefined && below > 0 && (
          <Chip
            label={`${below} below band`}
            size="small"
            color="warning"
            variant="outlined"
          />
        )}
      </Stack>
      {reason && (
        <Typography variant="body2" sx={{ mt: 1 }}>
          {reason}
        </Typography>
      )}
      {gaps.length > 0 && (
        <Box sx={{ mt: 1 }}>
          <Typography variant="caption" color="text.secondary">
            Gaps identified:
          </Typography>
          <Stack spacing={0.25} sx={{ mt: 0.5 }}>
            {gaps.map((g, i) => (
              <Typography key={i} variant="body2" sx={{ pl: 1 }}>
                • {g}
              </Typography>
            ))}
          </Stack>
        </Box>
      )}
    </Paper>
  );
}

function RevisionPanel({ ev }: { ev: TimelineEvent }) {
  const newSubtasks = (ev.payload?.new_subtasks as string[]) ?? [];
  const reason = (ev.payload?.reason as string) ?? '';
  return (
    <Paper variant="outlined" sx={{ p: 1.5, borderLeft: 4, borderLeftColor: 'info.main' }}>
      <Stack direction="row" alignItems="center" spacing={1}>
        <Chip
          label="DEVIATION"
          size="small"
          color="info"
          sx={{ fontWeight: 700 }}
          icon={<WarningAmberIcon />}
        />
        <Typography variant="subtitle2">Revised decomposition (round {ev.round ?? '?'})</Typography>
      </Stack>
      {reason && (
        <Typography variant="body2" sx={{ mt: 1, fontStyle: 'italic', color: 'text.secondary' }}>
          Why: {reason}
        </Typography>
      )}
      {newSubtasks.length > 0 && (
        <Box sx={{ mt: 1 }}>
          <Typography variant="caption" color="text.secondary">
            New sub-tasks added to close the gaps:
          </Typography>
          <Stack spacing={0.5} sx={{ mt: 0.5 }}>
            {newSubtasks.map((s, i) => (
              <Box key={i} sx={{ display: 'flex', gap: 1 }}>
                <Typography variant="caption" sx={{ minWidth: 24, color: 'info.main', fontWeight: 600 }}>
                  +{i + 1}
                </Typography>
                <Typography variant="body2">{s}</Typography>
              </Box>
            ))}
          </Stack>
        </Box>
      )}
    </Paper>
  );
}

function ActivityRow({ ev }: { ev: TimelineEvent }) {
  const status = ev.status || '';
  const color = statusToColor(status);
  let summary = '';
  let icon: React.ReactNode = null;

  if (ev.kind === 'bid.opened') {
    const n = ev.payload?.n_candidates as number | undefined;
    summary = `bid opened with ${n ?? '?'} candidates: "${(ev.payload?.description as string)?.slice(0, 80) ?? ''}"`;
  } else if (ev.kind === 'bid.closed') {
    const w = ev.payload?.winner as { agent_name?: string; confidence?: number } | undefined;
    if (w) {
      summary = `winner: ${w.agent_name ?? '?'} (conf ${w.confidence?.toFixed?.(2) ?? w.confidence ?? '?'})`;
    } else {
      summary = 'no winner';
    }
  } else if (ev.kind === 'agent.iteration') {
    const a = ev.payload?.agent_name as string | undefined;
    summary = `${a ?? 'agent'} — iteration ${ev.iteration ?? '?'}`;
  } else if (ev.kind === 'tool.call') {
    const t = ev.payload?.tool_name as string | undefined;
    summary = `→ ${t ?? '(tool)'}: ${(ev.payload?.args_preview as string)?.slice(0, 100) ?? ''}`;
  } else if (ev.kind === 'tool.result') {
    const t = ev.payload?.tool_name as string | undefined;
    const ms = ev.payload?.latency_ms as number | undefined;
    summary = `← ${t ?? '(tool)'} ${ms ?? '?'}ms — ${(ev.payload?.preview as string)?.slice(0, 100) ?? ''}`;
    icon = ev.payload?.success ? <CheckCircleIcon fontSize="small" color="success" /> : <ErrorIcon fontSize="small" color="error" />;
  } else if (ev.kind === 'score.evaluated') {
    const s = ev.payload?.score as number | undefined;
    const bl = ev.payload?.band_low as number | undefined;
    const a = ev.payload?.agent_name as string | undefined;
    const h = ev.payload?.heuristic_score as number | undefined;
    const l = ev.payload?.learned_score as number | undefined;
    const w = ev.payload?.w7_learned as number | undefined;
    let blendNote = '';
    if (l != null && w != null && w > 0 && h != null) {
      blendNote = ` [heuristic ${h.toFixed?.(2) ?? h} + ${w}×learned ${l.toFixed?.(2) ?? l}]`;
    }
    summary = `score ${s?.toFixed?.(2) ?? s} (band ≥ ${bl?.toFixed?.(2) ?? bl}) — ${a ?? 'agent'}${blendNote}`;
  } else if (ev.kind === 'ml.rationale') {
    const src = ev.payload?.source as string | undefined;
    if (src === 'bandit') {
      const pick = ev.payload?.pick_agent_name as string | undefined;
      const overrode = Boolean(ev.payload?.overrode_bid_winner);
      const prior = ev.payload?.prior_bid_winner as string | undefined;
      summary = overrode
        ? `bandit overrode bid winner ${prior ?? '?'} → ${pick ?? '?'}`
        : `bandit confirmed bid winner ${pick ?? '?'}`;
    } else if (src === 'learned_scorer') {
      const w = ev.payload?.w7 as number | undefined;
      const h = ev.payload?.heuristic_score as number | undefined;
      const l = ev.payload?.learned_score as number | undefined;
      const b = ev.payload?.blended_score as number | undefined;
      summary = `learned-scorer blend w7=${w}: ${h?.toFixed?.(2) ?? h} → ${b?.toFixed?.(2) ?? b} (learned ${l?.toFixed?.(2) ?? l})`;
    } else {
      summary = `ml: ${JSON.stringify(ev.payload).slice(0, 120)}`;
    }
  } else if (ev.kind === 'memory.refreshed') {
    const ents = (ev.payload?.entities as string[]) ?? [];
    summary = `memory refresh on entities: ${ents.slice(0, 4).join(', ')}${ents.length > 4 ? '…' : ''}`;
  } else if (ev.kind === 'auto_correct.triggered') {
    const a = ev.payload?.agent_name as string | undefined;
    const ps = ev.payload?.prior_score as number | undefined;
    const bl = ev.payload?.band_low as number | undefined;
    summary = `↻ ${a ?? 'agent'} below band — re-prompting (prior ${ps?.toFixed?.(2) ?? ps} < ${bl?.toFixed?.(2) ?? bl})`;
    icon = <WarningAmberIcon fontSize="small" color="warning" />;
  } else if (ev.kind === 'auto_correct.completed') {
    const a = ev.payload?.agent_name as string | undefined;
    const fs = ev.payload?.final_score as number | undefined;
    const improved = Boolean(ev.payload?.improved);
    const retried = Boolean(ev.payload?.retried);
    if (!retried) {
      summary = `${a ?? 'agent'} — auto_correct logged (no retry context)`;
    } else if (improved) {
      summary = `✓ ${a ?? 'agent'} retry passed (final ${fs?.toFixed?.(2) ?? fs})`;
      icon = <CheckCircleIcon fontSize="small" color="success" />;
    } else {
      summary = `✗ ${a ?? 'agent'} retry still below band (final ${fs?.toFixed?.(2) ?? fs})`;
      icon = <ErrorIcon fontSize="small" color="error" />;
    }
  } else if (ev.kind === 'subagent.spawned') {
    const parent = ev.payload?.parent_agent_name as string | undefined;
    const td = (ev.payload?.task_description as string) ?? '';
    const depth = ev.payload?.depth as number | undefined;
    summary = `${parent ?? 'agent'} → sub-agent (depth ${depth ?? '?'}): ${td.slice(0, 120)}`;
  } else if (ev.kind === 'subagent.refused') {
    const reason = (ev.payload?.reason as string) ?? '';
    summary = `sub-agent refused: ${reason}`;
    icon = <WarningAmberIcon fontSize="small" color="warning" />;
  } else if (ev.kind === 'memory.written') {
    const kind = (ev.payload?.artifact_kind as string) ?? '';
    const key = (ev.payload?.key as string) ?? '';
    summary = `learned: ${kind} ${key ? `(${key})` : ''}`;
  } else {
    summary = JSON.stringify(ev.payload).slice(0, 120);
  }

  return (
    <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1, py: 0.25 }}>
      <Chip
        label={kindLabel(ev.kind)}
        size="small"
        variant="outlined"
        color={color}
        sx={{ minWidth: 130, fontSize: '0.7rem' }}
      />
      {icon}
      <Typography
        variant="body2"
        sx={{
          flex: 1,
          fontFamily: 'ui-monospace, SFMono-Regular, monospace',
          fontSize: '0.8rem',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
        }}
      >
        {summary}
      </Typography>
      <Typography variant="caption" color="text.secondary">
        {ev.ts?.slice(11, 23) ?? ''}
      </Typography>
    </Box>
  );
}

function RoundCard({ round, isLast }: { round: Round; isLast: boolean }) {
  const theme = useTheme();
  // Activity events to show in chronological order. Skip the "header"
  // events which are rendered as their own dedicated panels above.
  const activity = round.events.filter(
    (e) =>
      e.kind !== 'decomposition.created' &&
      e.kind !== 'decomposition.revised' &&
      e.kind !== 'sufficiency.checked',
  );
  return (
    <Box
      sx={{
        mb: 2,
        position: 'relative',
        pl: 3,
        '&::before': {
          content: '""',
          position: 'absolute',
          left: 9,
          top: 12,
          bottom: isLast ? 12 : -8,
          width: 2,
          bgcolor: theme.palette.divider,
        },
        '&::after': {
          content: '""',
          position: 'absolute',
          left: 4,
          top: 8,
          width: 12,
          height: 12,
          borderRadius: '50%',
          bgcolor: 'primary.main',
        },
      }}
    >
      <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600, letterSpacing: 1 }}>
        ROUND {round.roundN}
      </Typography>
      <Stack spacing={1} sx={{ mt: 0.5 }}>
        {round.initial && <InitialDecompositionPanel ev={round.initial} />}
        {round.revision && <RevisionPanel ev={round.revision} />}
        {round.sufficiency && <SufficiencyPanel ev={round.sufficiency} />}
        {activity.length > 0 && (
          <Paper variant="outlined" sx={{ p: 1 }}>
            <Typography variant="caption" color="text.secondary" sx={{ pl: 1 }}>
              Activity ({activity.length})
            </Typography>
            <Divider sx={{ my: 0.5 }} />
            <Stack divider={<Divider />} spacing={0.25}>
              {activity.map((e) => (
                <ActivityRow key={e.event_id} ev={e} />
              ))}
            </Stack>
          </Paper>
        )}
      </Stack>
    </Box>
  );
}

function CarryingForwardPanel({ items }: { items: FeedbackRow[] }) {
  if (!items || items.length === 0) return null;
  const lastFew = items.slice(0, 4);
  return (
    <Paper
      variant="outlined"
      sx={{
        p: 1.5,
        mb: 2,
        borderLeft: 4,
        borderLeftColor: 'info.main',
        bgcolor: 'background.paper',
      }}
    >
      <Stack direction="row" alignItems="center" spacing={1}>
        <Chip
          label="CARRYING FORWARD"
          size="small"
          color="info"
          sx={{ fontWeight: 700, letterSpacing: 0.5 }}
        />
        <Typography variant="subtitle2">
          User feedback from prior turns is being injected into the team's prompt
        </Typography>
      </Stack>
      <Stack spacing={0.5} sx={{ mt: 1, pl: 1 }}>
        {lastFew.map((f) => {
          const symbol = f.rating === 'UP' ? '👍' : f.rating === 'DOWN' ? '👎' : '•';
          return (
            <Typography key={f.id} variant="body2" sx={{ color: 'text.secondary' }}>
              {symbol} <b>{f.rating}</b>
              {f.comment ? ` — ${f.comment.slice(0, 200)}` : ''}
            </Typography>
          );
        })}
        {items.length > lastFew.length && (
          <Typography variant="caption" color="text.secondary">
            …and {items.length - lastFew.length} more
          </Typography>
        )}
      </Stack>
    </Paper>
  );
}

function CompletedBanner({ ev }: { ev: TimelineEvent }) {
  const sufficient = Boolean(ev.payload?.sufficient);
  const rounds = ev.payload?.rounds as number | undefined;
  const avg = ev.payload?.avg_score as number | undefined;
  return (
    <Paper
      variant="outlined"
      sx={{
        p: 2,
        bgcolor: sufficient ? 'success.dark' : 'warning.dark',
        color: sufficient ? 'success.contrastText' : 'warning.contrastText',
      }}
    >
      <Stack direction="row" alignItems="center" spacing={1}>
        {sufficient ? <CheckCircleIcon /> : <WarningAmberIcon />}
        <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
          {sufficient ? 'Accepted as complete' : 'Cap reached — answer returned with remaining gaps'}
        </Typography>
      </Stack>
      <Typography variant="body2" sx={{ mt: 0.5 }}>
        {rounds ?? 1} round(s) executed
        {avg !== undefined && `, average score ${avg?.toFixed?.(2) ?? avg}`}.
      </Typography>
    </Paper>
  );
}

// ──────────────────────────────────────────────────────────────────────────────
// Main page
// ──────────────────────────────────────────────────────────────────────────────

export default function TimelinePage() {
  const { id } = useParams<{ id: string }>();
  const conversationId = id ?? '';

  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [feedbackRows, setFeedbackRows] = useState<FeedbackRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<'live' | 'replay'>('live');
  const seenRef = useRef<Set<string>>(new Set());
  const streamRef = useRef<StreamHandle | null>(null);
  const fallbackTimerRef = useRef<number | null>(null);
  const eventCountAtFallbackStartRef = useRef<number>(0);

  const append = (e: TimelineEvent) => {
    if (!e?.event_id) return;
    if (seenRef.current.has(e.event_id)) return;
    seenRef.current.add(e.event_id);
    setEvents((prev) => [...prev, e]);
  };

  // Phase A.7: open the live stream first, fall back to MySQL replay if no
  // events arrive within 5s (i.e. the conversation has already finished).
  const reloadFromReplay = async () => {
    try {
      setMode('replay');
      const all = await replayTimeline(conversationId);
      seenRef.current = new Set(all.map((e) => e.event_id));
      setEvents(all);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  // Phase C.5: pull prior feedback so the timeline can render the
  // "Carrying forward" panel above the round list. This is a one-shot
  // fetch — we don't need it to be live.
  useEffect(() => {
    if (!conversationId) return;
    let cancelled = false;
    void (async () => {
      try {
        const items = await listFeedback(conversationId, 20);
        if (!cancelled) setFeedbackRows(items);
      } catch {
        // best-effort; absence of feedback is the common case
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [conversationId]);

  useEffect(() => {
    if (!conversationId) return;

    // Open SSE
    streamRef.current = streamTimeline(
      conversationId,
      (ev) => {
        // Cancel the fallback timer once any event arrives.
        if (fallbackTimerRef.current !== null) {
          window.clearTimeout(fallbackTimerRef.current);
          fallbackTimerRef.current = null;
        }
        append(ev);
      },
      (reason) => {
        // If the upstream closed without producing events, fall back to replay.
        if (reason && reason !== 'aborted') {
          // best-effort: still try replay so user sees historical events
          if (events.length === 0) {
            void reloadFromReplay();
          }
        }
      },
    );

    // Fallback to replay if nothing arrives in 5s.
    eventCountAtFallbackStartRef.current = 0;
    fallbackTimerRef.current = window.setTimeout(() => {
      if (seenRef.current.size === eventCountAtFallbackStartRef.current) {
        void reloadFromReplay();
      }
    }, 5000);

    return () => {
      if (fallbackTimerRef.current !== null) {
        window.clearTimeout(fallbackTimerRef.current);
        fallbackTimerRef.current = null;
      }
      streamRef.current?.abort();
      streamRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId]);

  const rounds = useMemo(() => groupByRound(events), [events]);
  const completed = useMemo(
    () => events.find((e) => e.kind === 'pipeline.completed'),
    [events],
  );

  if (!conversationId) {
    return (
      <Box>
        <Alert severity="error">No conversation_id in route.</Alert>
      </Box>
    );
  }

  return (
    <Box>
      <Stack direction="row" alignItems="center" spacing={2} sx={{ mb: 2 }}>
        <Typography variant="h5" sx={{ fontWeight: 600 }}>
          Decomposition Timeline
        </Typography>
        <Chip
          label={mode === 'live' ? 'Live' : 'Replay'}
          color={mode === 'live' ? 'success' : 'default'}
          size="small"
        />
        <Typography variant="caption" color="text.secondary" sx={{ flex: 1 }}>
          conversation: {conversationId}
        </Typography>
        <Tooltip title="Reload from replay">
          <IconButton size="small" onClick={() => void reloadFromReplay()}>
            <RefreshIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Stack>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      <CarryingForwardPanel items={feedbackRows} />

      {events.length === 0 ? (
        <Stack spacing={1}>
          <Skeleton variant="rectangular" height={120} />
          <Skeleton variant="rectangular" height={80} />
          <Skeleton variant="rectangular" height={80} />
        </Stack>
      ) : (
        <Box>
          {rounds.map((r, idx) => (
            <RoundCard
              key={r.roundN}
              round={r}
              isLast={!completed && idx === rounds.length - 1}
            />
          ))}
          {completed && (
            <Box sx={{ pl: 3, mt: 1 }}>
              <CompletedBanner ev={completed} />
            </Box>
          )}
        </Box>
      )}
    </Box>
  );
}
