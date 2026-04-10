import React from 'react';
import {
  Box,
  Typography,
  Chip,
  Paper,
  Divider,
  IconButton,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  Skeleton,
  useTheme,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  LinearProgress,
  Tooltip,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty';
import WarningIcon from '@mui/icons-material/Warning';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import EmojiEventsIcon from '@mui/icons-material/EmojiEvents';
import GavelIcon from '@mui/icons-material/Gavel';
import PersonSearchIcon from '@mui/icons-material/PersonSearch';
import type { TaskNodeDetail, TaskNode, MemoryHits, ScoreBand } from '@/types';
import { useTaskNodeDetail, useTaskBids, type TaskBid } from '@/api/decomposition';

/* ---- Status helpers ---- */

const STATUS_MAP: Record<string, { label: string; color: 'default' | 'info' | 'success' | 'error' | 'warning' }> = {
  PENDING: { label: 'Pending', color: 'default' },
  RUNNING: { label: 'Running', color: 'info' },
  SUCCESS: { label: 'Complete', color: 'success' },
  FAILED: { label: 'Failed', color: 'error' },
  CORRECTING: { label: 'Corrected', color: 'warning' },
  SKIPPED: { label: 'Skipped', color: 'default' },
};

const CRITICALITY_COLOR: Record<string, 'default' | 'info' | 'warning' | 'error'> = {
  low: 'default',
  medium: 'info',
  high: 'warning',
  critical: 'error',
};

interface Props {
  node: TaskNode | null;
  conversationId: string;
  onClose: () => void;
}

/* ---- Score band inline viz ---- */

function ScoreBandBar({ score, band }: { score: number; band: ScoreBand }) {
  const theme = useTheme();
  const bandWidth = band.high - band.low;
  const leftPct = band.low * 100;
  const widthPct = bandWidth * 100;
  const scorePct = score * 100;

  return (
    <Box sx={{ position: 'relative', height: 24, mt: 1, mb: 1 }}>
      <Box
        sx={{
          position: 'absolute',
          inset: 0,
          borderRadius: 1,
          bgcolor: theme.palette.action.hover,
        }}
      />
      <Box
        sx={{
          position: 'absolute',
          top: 0,
          bottom: 0,
          left: `${leftPct}%`,
          width: `${widthPct}%`,
          borderRadius: 1,
          bgcolor: theme.palette.primary.dark,
          opacity: 0.35,
        }}
      />
      <Box
        sx={{
          position: 'absolute',
          top: '50%',
          left: `${scorePct}%`,
          transform: 'translate(-50%, -50%)',
          width: 14,
          height: 14,
          borderRadius: '50%',
          bgcolor: theme.palette.primary.main,
          border: `2px solid ${theme.palette.background.paper}`,
          boxShadow: 1,
        }}
      />
      <Typography
        variant="caption"
        sx={{
          position: 'absolute',
          left: `${leftPct}%`,
          bottom: -16,
          transform: 'translateX(-50%)',
          color: 'text.secondary',
        }}
      >
        {band.low.toFixed(2)}
      </Typography>
      <Typography
        variant="caption"
        sx={{
          position: 'absolute',
          left: `${leftPct + widthPct}%`,
          bottom: -16,
          transform: 'translateX(-50%)',
          color: 'text.secondary',
        }}
      >
        {band.high.toFixed(2)}
      </Typography>
    </Box>
  );
}

/* ---- Memory hits chips ---- */

function MemoryHitsChips({ hits }: { hits: MemoryHits }) {
  const theme = useTheme();
  const tiers: Array<{ key: keyof MemoryHits; label: string }> = [
    { key: 'short_term', label: 'Short-term' },
    { key: 'long_term', label: 'Long-term' },
    { key: 'reasoning', label: 'Reasoning' },
    { key: 'episodic', label: 'Episodic' },
  ];

  return (
    <Box sx={{ display: 'flex', gap: 0.75, flexWrap: 'wrap' }}>
      {tiers.map((t) => (
        <Chip
          key={t.key}
          label={`${t.label}: ${hits[t.key]}`}
          size="small"
          variant="outlined"
          sx={{
            borderColor: theme.palette.divider,
            color: theme.palette.text.secondary,
            fontSize: '0.75rem',
          }}
        />
      ))}
    </Box>
  );
}

/* ---- Tool call status icon ---- */

function ToolStatusIcon({ status }: { status: string }) {
  switch (status) {
    case 'success':
      return <CheckCircleIcon color="success" fontSize="small" />;
    case 'error':
      return <ErrorIcon color="error" fontSize="small" />;
    default:
      return <HourglassEmptyIcon color="info" fontSize="small" />;
  }
}

/* ---- Negotiation / Bids section ---- */

function NegotiationSection({ bids, isLoading }: { bids: TaskBid[]; isLoading: boolean }) {
  const theme = useTheme();

  if (isLoading) {
    return (
      <Box>
        <Skeleton variant="text" width="60%" height={20} />
        <Skeleton variant="rectangular" width="100%" height={60} sx={{ mt: 1, borderRadius: 1 }} />
      </Box>
    );
  }

  if (bids.length === 0) {
    return (
      <Box>
        <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5, display: 'flex', alignItems: 'center', gap: 0.5 }}>
          <GavelIcon fontSize="small" /> Capability Negotiation
        </Typography>
        <Typography variant="body2" sx={{ color: 'text.secondary', fontStyle: 'italic' }}>
          No bid data available for this task.
        </Typography>
      </Box>
    );
  }

  // Separate winner(s) from other bids
  const winners = bids.filter((b) => b.event_type === 'BID_WON' || b.interaction_type === 'BID_WON');
  const submissions = bids.filter((b) => b.event_type !== 'BID_WON' && b.interaction_type !== 'BID_WON'
    && b.event_type !== 'BID_ACCURACY' && b.interaction_type !== 'BID_ACCURACY');
  const accuracyChecks = bids.filter((b) => b.event_type === 'BID_ACCURACY' || b.interaction_type === 'BID_ACCURACY');

  // Find max confidence for the bar scaling
  const maxConf = Math.max(
    ...bids.map((b) => b.confidence ?? b.bid_confidence ?? b.rank_score ?? 0),
    0.01,
  );

  return (
    <Box>
      <Typography variant="body2" sx={{ fontWeight: 600, mb: 1, display: 'flex', alignItems: 'center', gap: 0.5 }}>
        <GavelIcon fontSize="small" /> Capability Negotiation
      </Typography>

      {/* Winner */}
      {winners.map((w, i) => {
        const name = w.assigned_agent_name || w.agent_name || `Agent ${w.agent_id}`;
        const conf = w.confidence ?? w.bid_confidence ?? 0;
        return (
          <Box
            key={`winner-${i}`}
            sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 1,
              p: 1,
              mb: 1,
              borderRadius: 1,
              bgcolor: theme.palette.success.main + '18',
              border: `1px solid ${theme.palette.success.main}40`,
            }}
          >
            <EmojiEventsIcon fontSize="small" sx={{ color: theme.palette.warning.main }} />
            <Box sx={{ flex: 1 }}>
              <Typography variant="body2" sx={{ fontWeight: 600 }}>
                {name}
              </Typography>
              <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                Won with {(conf * 100).toFixed(0)}% confidence
              </Typography>
            </Box>
            <Chip label="Winner" size="small" color="success" />
          </Box>
        );
      })}

      {/* All bids */}
      {submissions.length > 0 && (
        <Accordion
          disableGutters
          elevation={0}
          defaultExpanded
          sx={{ bgcolor: 'transparent', '&:before': { display: 'none' } }}
        >
          <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ px: 0, minHeight: 32 }}>
            <Typography variant="body2" sx={{ fontWeight: 600, display: 'flex', alignItems: 'center', gap: 0.5 }}>
              <PersonSearchIcon fontSize="small" /> Agent Bids ({submissions.length})
            </Typography>
          </AccordionSummary>
          <AccordionDetails sx={{ px: 0, pt: 0 }}>
            {submissions.map((bid, i) => {
              const name = bid.assigned_agent_name || bid.agent_name || `Agent ${bid.agent_id}`;
              const conf = bid.confidence ?? bid.bid_confidence ?? bid.rank_score ?? 0;
              const isWinner = winners.some(
                (w) => (w.agent_id && w.agent_id === bid.agent_id) ||
                  (w.agent_name && w.agent_name === bid.agent_name),
              );

              return (
                <Box
                  key={`bid-${i}`}
                  sx={{
                    mb: 1,
                    p: 1,
                    borderRadius: 1,
                    bgcolor: isWinner ? theme.palette.success.main + '10' : theme.palette.action.hover,
                    border: isWinner ? `1px solid ${theme.palette.success.main}30` : 'none',
                  }}
                >
                  <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 0.5 }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                      <SmartToyIcon fontSize="small" sx={{ color: 'text.secondary' }} />
                      <Typography variant="body2" sx={{ fontWeight: 500 }}>
                        {name}
                      </Typography>
                      {isWinner && (
                        <EmojiEventsIcon sx={{ fontSize: 14, color: theme.palette.warning.main }} />
                      )}
                    </Box>
                    <Typography variant="caption" sx={{ fontWeight: 600 }}>
                      {(conf * 100).toFixed(0)}%
                    </Typography>
                  </Box>

                  {/* Confidence bar */}
                  <Tooltip title={`Confidence: ${(conf * 100).toFixed(1)}%`}>
                    <LinearProgress
                      variant="determinate"
                      value={(conf / maxConf) * 100}
                      sx={{
                        height: 6,
                        borderRadius: 3,
                        bgcolor: theme.palette.action.disabledBackground,
                        '& .MuiLinearProgress-bar': {
                          borderRadius: 3,
                          bgcolor: isWinner ? theme.palette.success.main : theme.palette.info.main,
                        },
                      }}
                    />
                  </Tooltip>

                  {/* Extra bid details */}
                  <Box sx={{ display: 'flex', gap: 1.5, mt: 0.5, flexWrap: 'wrap' }}>
                    {bid.can_solve != null && (
                      <Typography variant="caption" sx={{ color: bid.can_solve ? 'success.main' : 'error.main' }}>
                        {bid.can_solve ? 'Can solve' : 'Cannot solve'}
                      </Typography>
                    )}
                    {bid.memory_hits != null && (
                      <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                        Memory: {bid.memory_hits}
                      </Typography>
                    )}
                    {bid.estimated_latency_ms != null && (
                      <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                        Est. {bid.estimated_latency_ms}ms
                      </Typography>
                    )}
                  </Box>

                  {bid.approach && (
                    <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block', mt: 0.5 }}>
                      Approach: {String(bid.approach).slice(0, 120)}
                    </Typography>
                  )}

                  {bid.tools_needed && Array.isArray(bid.tools_needed) && bid.tools_needed.length > 0 && (
                    <Box sx={{ display: 'flex', gap: 0.5, mt: 0.5, flexWrap: 'wrap' }}>
                      {bid.tools_needed.map((t, ti) => (
                        <Chip key={ti} label={t} size="small" variant="outlined" sx={{ fontSize: '0.7rem', height: 20 }} />
                      ))}
                    </Box>
                  )}
                </Box>
              );
            })}
          </AccordionDetails>
        </Accordion>
      )}

      {/* Accuracy tracking */}
      {accuracyChecks.length > 0 && (
        <Box sx={{ mt: 1 }}>
          <Typography variant="caption" sx={{ color: 'text.secondary', fontWeight: 600 }}>
            Bid Accuracy Check
          </Typography>
          {accuracyChecks.map((ac, i) => (
            <Typography key={`acc-${i}`} variant="caption" sx={{ display: 'block', color: 'text.secondary' }}>
              {String(ac.action_taken || `Agent ${ac.agent_id}: predicted=${ac.bid_confidence}, actual=${ac.score}`)}
            </Typography>
          ))}
        </Box>
      )}
    </Box>
  );
}

/* ---- Main panel ---- */

const TaskDetailPanel: React.FC<Props> = ({ node, conversationId, onClose }) => {
  const theme = useTheme();
  const { data: detail, isLoading } = useTaskNodeDetail(
    conversationId,
    node?.task_id,
  );
  const { data: bids, isLoading: bidsLoading } = useTaskBids(node?.task_id);

  const merged: TaskNodeDetail | null = detail ?? (node as TaskNodeDetail | null);

  if (!node) {
    return (
      <Paper
        elevation={0}
        sx={{
          width: '100%',
          height: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          bgcolor: 'background.paper',
          borderLeft: `1px solid ${theme.palette.divider}`,
        }}
      >
        <Box sx={{ textAlign: 'center', p: 3 }}>
          <PersonSearchIcon sx={{ fontSize: 48, color: 'text.disabled', mb: 1 }} />
          <Typography color="text.secondary" variant="body2">
            Click a task node to view details
          </Typography>
          <Typography color="text.disabled" variant="caption" sx={{ display: 'block', mt: 0.5 }}>
            Drag nodes to rearrange. Double-click to unpin.
          </Typography>
        </Box>
      </Paper>
    );
  }

  if (isLoading) {
    return (
      <Paper
        elevation={0}
        sx={{
          width: '100%',
          height: '100%',
          p: 2.5,
          bgcolor: 'background.paper',
          borderLeft: `1px solid ${theme.palette.divider}`,
          overflow: 'auto',
        }}
      >
        <Skeleton variant="text" width="60%" height={28} />
        <Skeleton variant="text" width="80%" height={20} sx={{ mt: 1 }} />
        <Skeleton variant="rectangular" width="100%" height={120} sx={{ mt: 2, borderRadius: 1 }} />
        <Skeleton variant="rectangular" width="100%" height={80} sx={{ mt: 2, borderRadius: 1 }} />
      </Paper>
    );
  }

  if (!merged) return null;

  const statusInfo = STATUS_MAP[merged.status] ?? { label: merged.status, color: 'default' as const };
  const extNode = merged as unknown as Record<string, unknown>;
  const assignedAgent = (extNode.assigned_agent_name || merged.agent_name || '') as string;

  return (
    <Paper
      elevation={0}
      sx={{
        width: '100%',
        height: '100%',
        overflow: 'auto',
        bgcolor: 'background.paper',
        borderLeft: `1px solid ${theme.palette.divider}`,
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
        <Typography variant="h6" noWrap sx={{ flex: 1 }}>
          Task Detail
        </Typography>
        <IconButton size="small" onClick={onClose}>
          <CloseIcon fontSize="small" />
        </IconButton>
      </Box>

      <Box sx={{ p: 2.5, display: 'flex', flexDirection: 'column', gap: 2 }}>
        {/* Task ID + Status */}
        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
          <Chip label={statusInfo.label} color={statusInfo.color} size="small" />
          <Chip label={`Depth ${merged.depth}`} size="small" variant="outlined" />
          {merged.criticality && (
            <Chip
              label={merged.criticality.toUpperCase()}
              color={CRITICALITY_COLOR[merged.criticality] ?? 'default'}
              size="small"
            />
          )}
        </Box>

        <Typography variant="caption" sx={{ color: 'text.secondary', fontFamily: 'monospace' }}>
          {merged.task_id}
        </Typography>

        {/* Description */}
        <Box>
          <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5 }}>
            Description
          </Typography>
          <Typography variant="body2" sx={{ color: 'text.secondary' }}>
            {merged.description}
          </Typography>
        </Box>

        {/* Assigned Agent */}
        {assignedAgent && (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <SmartToyIcon fontSize="small" sx={{ color: 'text.secondary' }} />
            <Box>
              <Typography variant="body2" sx={{ fontWeight: 500 }}>
                {assignedAgent}
              </Typography>
              <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                Assigned agent
              </Typography>
            </Box>
          </Box>
        )}

        {/* Fallback agents */}
        {merged.fallback_agents && merged.fallback_agents.length > 0 && (
          <Box>
            <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5 }}>
              Fallback Agents
            </Typography>
            <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
              {merged.fallback_agents.map((fa) => (
                <Chip key={fa.id} label={fa.name} size="small" variant="outlined" />
              ))}
            </Box>
          </Box>
        )}

        <Divider />

        {/* Negotiation / Bids */}
        <NegotiationSection bids={bids ?? []} isLoading={bidsLoading} />

        <Divider />

        {/* Score + Band */}
        {merged.score != null && merged.band && (
          <Box>
            <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5 }}>
              Score: {merged.score.toFixed(3)}
            </Typography>
            <ScoreBandBar score={merged.score} band={merged.band} />
          </Box>
        )}

        {/* Timing */}
        <Box sx={{ display: 'flex', gap: 3 }}>
          {merged.execution_time_ms != null && (
            <Box>
              <Typography variant="caption" sx={{ color: 'text.secondary' }}>Duration</Typography>
              <Typography variant="body2">{merged.execution_time_ms} ms</Typography>
            </Box>
          )}
          {merged.retry_count != null && (
            <Box>
              <Typography variant="caption" sx={{ color: 'text.secondary' }}>Retries</Typography>
              <Typography variant="body2">{merged.retry_count}</Typography>
            </Box>
          )}
        </Box>

        <Typography variant="caption" sx={{ color: 'text.secondary' }}>
          Created {merged.created_at}
        </Typography>

        <Divider />

        {/* Course corrections */}
        {merged.correction_history && merged.correction_history.length > 0 && (
          <Box>
            <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5 }}>
              Course Corrections
            </Typography>
            <List dense disablePadding>
              {merged.correction_history.map((c, i) => (
                <ListItem key={i} disablePadding sx={{ py: 0.25 }}>
                  <ListItemIcon sx={{ minWidth: 28 }}>
                    <WarningIcon fontSize="small" color="warning" />
                  </ListItemIcon>
                  <ListItemText
                    primary={c.reason}
                    secondary={`${c.from_agent} -> ${c.to_agent} (${c.severity})`}
                    primaryTypographyProps={{ variant: 'body2' }}
                    secondaryTypographyProps={{ variant: 'caption' }}
                  />
                </ListItem>
              ))}
            </List>
          </Box>
        )}

        {/* Tool calls */}
        {merged.tool_calls && merged.tool_calls.length > 0 && (
          <Box>
            <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5 }}>
              Tool Calls
            </Typography>
            <List dense disablePadding>
              {merged.tool_calls.map((tc) => (
                <ListItem key={tc.id} disablePadding sx={{ py: 0.25 }}>
                  <ListItemIcon sx={{ minWidth: 28 }}>
                    <ToolStatusIcon status={tc.status} />
                  </ListItemIcon>
                  <ListItemText
                    primary={tc.tool_name}
                    secondary={`${tc.latency_ms} ms`}
                    primaryTypographyProps={{ variant: 'body2' }}
                    secondaryTypographyProps={{ variant: 'caption' }}
                  />
                </ListItem>
              ))}
            </List>
          </Box>
        )}

        {/* Memory hits */}
        {merged.memory_hits && (
          <Box>
            <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5 }}>
              Memory Hits
            </Typography>
            <MemoryHitsChips hits={merged.memory_hits} />
          </Box>
        )}
      </Box>
    </Paper>
  );
};

export default TaskDetailPanel;
