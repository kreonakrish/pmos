import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  Typography,
  Paper,
  Grid,
  Tabs,
  Tab,
  Chip,
  Stack,
  Skeleton,
  Alert,
  Table,
  TableHead,
  TableRow,
  TableCell,
  TableBody,
  TextField,
  InputAdornment,
  Divider,
  Tooltip,
  Link as MuiLink,
} from '@mui/material';
import PsychologyIcon from '@mui/icons-material/Psychology';
import HubIcon from '@mui/icons-material/Hub';
import SearchIcon from '@mui/icons-material/Search';
import ScienceIcon from '@mui/icons-material/Science';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import ModelTrainingIcon from '@mui/icons-material/ModelTraining';
import RuleIcon from '@mui/icons-material/Rule';
import CheckIcon from '@mui/icons-material/Check';
import CloseIcon from '@mui/icons-material/Close';
import { Button } from '@mui/material';
import {
  useBanditSummary,
  useBanditState,
  useBanditDecisions,
  useBanditConvergence,
  useEmbeddingSummary,
  useEmbeddingProjection,
  useEmbeddingSimilar,
  useLearnedScorerSummary,
  useLearnedScorerPredictions,
  useSOPProposals,
  usePromoteSOP,
  useRejectSOP,
  BanditStateRow,
  BanditDecisionRow,
  EmbeddingProjectionPoint,
  LearnedScorerPrediction,
  SOPProposal,
} from '@/api/mlInsights';

const NODE_TYPE_COLOR: Record<string, string> = {
  ROOT: '#1976d2',
  SUBTASK: '#7b1fa2',
  SUB_AGENT: '#388e3c',
  RESPONSE: '#ed6c02',
  '': '#757575',
};

function fmt(n: number | null | undefined, digits = 3): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  return Number(n).toFixed(digits);
}

function fmtTs(ts: string | null | undefined): string {
  if (!ts) return '';
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return String(ts);
  }
}

export default function MLInsightsPage() {
  const [tab, setTab] = useState(0);

  return (
    <Box>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
        <ScienceIcon color="primary" />
        <Typography variant="h5" fontWeight={600}>
          ML Insights
        </Typography>
        <Chip label="Learning loop observability" size="small" variant="outlined" />
      </Stack>

      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Live view of the learning components embedded in PMOS: the contextual
        bandit that picks agents, and the graph-neighborhood embeddings of
        TaskNodes that feed downstream models. All data is read directly from
        MySQL — decisions flow here from every pipeline run.
      </Typography>

      <Paper sx={{ mb: 2 }}>
        <Tabs value={tab} onChange={(_, v) => setTab(v)}>
          <Tab icon={<PsychologyIcon />} iconPosition="start" label="Contextual Bandits" />
          <Tab icon={<HubIcon />} iconPosition="start" label="Graph Embeddings" />
          <Tab icon={<ModelTrainingIcon />} iconPosition="start" label="Learned Scorer" />
          <Tab icon={<RuleIcon />} iconPosition="start" label="SOP Discovery" />
        </Tabs>
      </Paper>

      {tab === 0 && <BanditsTab />}
      {tab === 1 && <EmbeddingsTab />}
      {tab === 2 && <LearnedScorerTab />}
      {tab === 3 && <SOPDiscoveryTab />}
    </Box>
  );
}

// ---------------------------------------------------------------------------
// Bandits tab
// ---------------------------------------------------------------------------
function BanditsTab() {
  const summaryQ = useBanditSummary();
  const stateQ = useBanditState(undefined, 200);
  const decisionsQ = useBanditDecisions({ limit: 100 });

  const [selectedRow, setSelectedRow] = useState<{ agentId: string; bucket: string } | null>(null);
  const convergenceQ = useBanditConvergence(
    selectedRow?.agentId ?? null,
    selectedRow?.bucket ?? null,
  );

  const summary = summaryQ.data;
  const state = stateQ.data?.state ?? [];
  const decisions = decisionsQ.data?.decisions ?? [];

  return (
    <Box>
      {/* Summary cards */}
      <Grid container spacing={2} sx={{ mb: 2 }}>
        <StatCard label="Total decisions" value={summary?.decisions.total} loading={summaryQ.isLoading} />
        <StatCard label="Rewarded" value={summary?.decisions.rewarded} loading={summaryQ.isLoading} />
        <StatCard
          label="Shadow / Live"
          value={summary ? `${summary.decisions.shadow} / ${summary.decisions.live}` : undefined}
          loading={summaryQ.isLoading}
        />
        <StatCard
          label="Disagreements"
          value={summary?.decisions.disagreements}
          loading={summaryQ.isLoading}
          highlight={!!summary && summary.decisions.disagreements > 0}
        />
        <StatCard label="Agents tracked" value={summary?.state.agents_tracked} loading={summaryQ.isLoading} />
        <StatCard label="Contexts" value={summary?.state.contexts_tracked} loading={summaryQ.isLoading} />
        <StatCard label="Max pulls" value={summary?.state.max_pulls} loading={summaryQ.isLoading} />
        <StatCard label="Prior mean" value={summary ? fmt(summary.prior.mean, 2) : undefined} loading={summaryQ.isLoading} />
      </Grid>

      {/* Readiness */}
      <Paper sx={{ p: 2, mb: 2 }}>
        <Typography variant="subtitle2" sx={{ mb: 1 }}>
          Context readiness for LIVE mode
          <Tooltip title={`A bucket is READY when every arm has at least ${summary?.min_pulls_for_live ?? 20} pulls. WARMING when the slowest arm is at least half that. Otherwise COLD.`}>
            <Chip label="?" size="small" sx={{ ml: 1, height: 18, fontSize: 10 }} />
          </Tooltip>
        </Typography>
        {summary?.readiness.length ? (
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            {summary.readiness.map((r) => (
              <Chip
                key={r.context_bucket}
                label={`${r.context_bucket} · ${r.arms} arm${r.arms === 1 ? '' : 's'} · min=${r.min_pulls}`}
                size="small"
                color={r.state === 'READY' ? 'success' : r.state === 'WARMING' ? 'warning' : 'default'}
                variant={r.state === 'READY' ? 'filled' : 'outlined'}
              />
            ))}
          </Stack>
        ) : (
          <Typography variant="body2" color="text.secondary">
            No bandit state yet. Run a few team-bound conversations to populate.
          </Typography>
        )}
      </Paper>

      <Grid container spacing={2}>
        {/* State table */}
        <Grid item xs={12} md={7}>
          <Paper sx={{ p: 2, height: 420, overflow: 'auto' }}>
            <Typography variant="subtitle2" sx={{ mb: 1 }}>
              Bandit arm state ({state.length})
            </Typography>
            {stateQ.isLoading ? (
              <Skeleton height={300} />
            ) : state.length === 0 ? (
              <Alert severity="info">
                No (agent, context) state rows yet. Each time a team-bound conversation
                runs, a row will be created here with the agent's current Beta(α, β).
              </Alert>
            ) : (
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Agent</TableCell>
                    <TableCell>Context</TableCell>
                    <TableCell align="right">Pulls</TableCell>
                    <TableCell align="right">Mean</TableCell>
                    <TableCell>95% CI</TableCell>
                    <TableCell align="right">α / β</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {state.map((r) => (
                    <StateRow
                      key={`${r.agent_id}|${r.context_bucket}`}
                      row={r}
                      selected={
                        selectedRow?.agentId === r.agent_id &&
                        selectedRow?.bucket === r.context_bucket
                      }
                      onSelect={() =>
                        setSelectedRow({ agentId: r.agent_id, bucket: r.context_bucket })
                      }
                    />
                  ))}
                </TableBody>
              </Table>
            )}
          </Paper>
        </Grid>

        {/* Convergence chart */}
        <Grid item xs={12} md={5}>
          <Paper sx={{ p: 2, height: 420, display: 'flex', flexDirection: 'column' }}>
            <Typography variant="subtitle2" sx={{ mb: 1 }}>
              Posterior mean over time
            </Typography>
            {!selectedRow ? (
              <Alert severity="info">Click an arm in the table to see its reward trajectory.</Alert>
            ) : convergenceQ.isLoading ? (
              <Skeleton height={300} />
            ) : (
              <ConvergenceChart
                points={convergenceQ.data?.series ?? []}
                label={`${selectedRow.agentId.slice(0, 8)}… / ${selectedRow.bucket}`}
              />
            )}
          </Paper>
        </Grid>
      </Grid>

      {/* Decision log */}
      <Paper sx={{ p: 2, mt: 2 }}>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
          <Typography variant="subtitle2">Recent decisions ({decisions.length})</Typography>
          <Chip label="Click a trace to open the governance reasoning chain" size="small" variant="outlined" />
        </Stack>
        {decisionsQ.isLoading ? (
          <Skeleton height={200} />
        ) : decisions.length === 0 ? (
          <Alert severity="info">No decisions logged yet.</Alert>
        ) : (
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Time</TableCell>
                <TableCell>Mode</TableCell>
                <TableCell>Context</TableCell>
                <TableCell>Selected</TableCell>
                <TableCell>Bandit pick</TableCell>
                <TableCell align="right">Reward</TableCell>
                <TableCell>Trace</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {decisions.map((d) => (
                <DecisionRow key={d.decision_id} d={d} />
              ))}
            </TableBody>
          </Table>
        )}
      </Paper>
    </Box>
  );
}

function StateRow({
  row,
  selected,
  onSelect,
}: {
  row: BanditStateRow;
  selected: boolean;
  onSelect: () => void;
}) {
  const ciWidth = Math.max(0, (row.credible_high - row.credible_low) * 100);
  const ciLeft = row.credible_low * 100;
  return (
    <TableRow
      hover
      selected={selected}
      onClick={onSelect}
      sx={{ cursor: 'pointer' }}
    >
      <TableCell sx={{ fontWeight: selected ? 600 : 400 }}>
        {row.agent_name || row.agent_id.slice(0, 8)}
      </TableCell>
      <TableCell>
        <Typography variant="caption" sx={{ fontFamily: 'monospace' }}>
          {row.context_bucket}
        </Typography>
      </TableCell>
      <TableCell align="right">
        <Chip
          label={row.pulls}
          size="small"
          color={row.ready ? 'success' : 'default'}
          sx={{ height: 18, fontSize: 10 }}
        />
      </TableCell>
      <TableCell align="right">{fmt(row.posterior_mean)}</TableCell>
      <TableCell sx={{ minWidth: 120 }}>
        <Box sx={{ position: 'relative', height: 8, bgcolor: 'action.hover', borderRadius: 1 }}>
          <Box
            sx={{
              position: 'absolute',
              left: `${ciLeft}%`,
              width: `${ciWidth}%`,
              top: 0,
              bottom: 0,
              bgcolor: 'primary.main',
              borderRadius: 1,
              opacity: 0.7,
            }}
          />
        </Box>
        <Typography variant="caption" color="text.secondary">
          [{fmt(row.credible_low, 2)}, {fmt(row.credible_high, 2)}]
        </Typography>
      </TableCell>
      <TableCell align="right">
        <Typography variant="caption" sx={{ fontFamily: 'monospace' }}>
          {fmt(row.alpha, 2)} / {fmt(row.beta, 2)}
        </Typography>
      </TableCell>
    </TableRow>
  );
}

function DecisionRow({ d }: { d: BanditDecisionRow }) {
  const navigate = useNavigate();
  const modeColor =
    d.mode === 'LIVE'
      ? 'success'
      : d.mode === 'SHADOW'
      ? 'default'
      : d.mode === 'EXPLORATION'
      ? 'warning'
      : 'error';
  return (
    <TableRow sx={{ bgcolor: d.disagreement ? 'warning.lighter' : undefined }}>
      <TableCell>
        <Typography variant="caption">{fmtTs(d.created_at)}</Typography>
      </TableCell>
      <TableCell>
        <Chip label={d.mode} size="small" color={modeColor as any} sx={{ height: 18, fontSize: 10 }} />
      </TableCell>
      <TableCell>
        <Typography variant="caption" sx={{ fontFamily: 'monospace' }}>
          {d.context_bucket}
        </Typography>
      </TableCell>
      <TableCell>
        {d.selected_agent_name || d.selected_agent_id.slice(0, 8)}
      </TableCell>
      <TableCell>
        <Stack direction="row" spacing={0.5} alignItems="center">
          <span>{d.bandit_pick_agent_name || d.bandit_pick_agent_id?.slice(0, 8)}</span>
          {d.disagreement && (
            <Chip
              label="differs"
              size="small"
              color="warning"
              sx={{ height: 16, fontSize: 9 }}
            />
          )}
        </Stack>
      </TableCell>
      <TableCell align="right">
        {d.reward === null ? (
          <Chip label="pending" size="small" sx={{ height: 16, fontSize: 9 }} />
        ) : (
          <Chip
            label={fmt(d.reward, 2)}
            size="small"
            color={d.reward >= 0.7 ? 'success' : d.reward >= 0.5 ? 'warning' : 'error'}
            sx={{ height: 18, fontSize: 10 }}
          />
        )}
      </TableCell>
      <TableCell>
        {d.trace_id ? (
          <MuiLink
            component="button"
            onClick={() => navigate(`/model-governance?trace=${d.trace_id}`)}
            underline="hover"
            sx={{ fontSize: 11, fontFamily: 'monospace' }}
          >
            {d.trace_id.slice(0, 8)}…
            <OpenInNewIcon sx={{ fontSize: 11, ml: 0.25, verticalAlign: 'middle' }} />
          </MuiLink>
        ) : (
          '—'
        )}
      </TableCell>
    </TableRow>
  );
}

function ConvergenceChart({
  points,
  label,
}: {
  points: Array<{ i: number; posterior_mean: number; reward: number }>;
  label: string;
}) {
  if (points.length === 0) {
    return (
      <Alert severity="info" sx={{ flex: 1 }}>
        No rewarded decisions yet for this arm.
      </Alert>
    );
  }

  const W = 420;
  const H = 300;
  const pad = 32;

  const xs = points.map((p) => p.i);
  const maxX = Math.max(...xs, 1);
  const minY = 0;
  const maxY = 1;

  const xScale = (x: number) => pad + ((x - 1) / Math.max(1, maxX - 1)) * (W - 2 * pad);
  const yScale = (y: number) => H - pad - ((y - minY) / (maxY - minY)) * (H - 2 * pad);

  const path = points
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${xScale(p.i)},${yScale(p.posterior_mean)}`)
    .join(' ');

  return (
    <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
      <Typography variant="caption" color="text.secondary" sx={{ mb: 1, fontFamily: 'monospace' }}>
        {label}
      </Typography>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ flex: 1, width: '100%' }}>
        {/* Axes */}
        <line x1={pad} y1={H - pad} x2={W - pad} y2={H - pad} stroke="#888" />
        <line x1={pad} y1={pad} x2={pad} y2={H - pad} stroke="#888" />
        {/* Prior reference line at 0.6 */}
        <line
          x1={pad}
          x2={W - pad}
          y1={yScale(0.6)}
          y2={yScale(0.6)}
          stroke="#ed6c02"
          strokeDasharray="4 4"
        />
        <text x={W - pad - 4} y={yScale(0.6) - 4} fontSize="9" textAnchor="end" fill="#ed6c02">
          prior 0.6
        </text>
        {/* Y gridlines */}
        {[0.25, 0.5, 0.75, 1.0].map((y) => (
          <g key={y}>
            <line
              x1={pad}
              x2={W - pad}
              y1={yScale(y)}
              y2={yScale(y)}
              stroke="#ddd"
              strokeDasharray="2 3"
            />
            <text x={pad - 4} y={yScale(y) + 3} fontSize="9" textAnchor="end" fill="#666">
              {y.toFixed(2)}
            </text>
          </g>
        ))}
        {/* Raw rewards */}
        {points.map((p, i) => (
          <circle
            key={`r${i}`}
            cx={xScale(p.i)}
            cy={yScale(p.reward)}
            r={2}
            fill="#1976d2"
            opacity={0.4}
          />
        ))}
        {/* Posterior mean line */}
        <path d={path} fill="none" stroke="#1976d2" strokeWidth={2} />
        {/* Points on line */}
        {points.map((p, i) => (
          <circle
            key={`m${i}`}
            cx={xScale(p.i)}
            cy={yScale(p.posterior_mean)}
            r={3}
            fill="#1976d2"
          />
        ))}
      </svg>
    </Box>
  );
}

// ---------------------------------------------------------------------------
// Embeddings tab
// ---------------------------------------------------------------------------
function EmbeddingsTab() {
  const summaryQ = useEmbeddingSummary();
  const projQ = useEmbeddingProjection(500);
  const [nodeId, setNodeId] = useState('');
  const [lookupNodeId, setLookupNodeId] = useState<string | null>(null);
  const similarQ = useEmbeddingSimilar(lookupNodeId, 10);

  const summary = summaryQ.data;
  const points = projQ.data?.points ?? [];

  return (
    <Box>
      <Grid container spacing={2} sx={{ mb: 2 }}>
        <StatCard label="Total nodes" value={summary?.total} loading={summaryQ.isLoading} />
        <StatCard label="Graphs" value={summary?.graphs} loading={summaryQ.isLoading} />
        <StatCard label="Dimension" value={summary?.dim} loading={summaryQ.isLoading} />
        <StatCard label="Algorithm" value={summary?.algorithm} loading={summaryQ.isLoading} />
        <StatCard label="Last refresh" value={summary ? fmtTs(summary.last_computed) : undefined} loading={summaryQ.isLoading} />
      </Grid>

      {summary?.by_node_type?.length ? (
        <Stack direction="row" spacing={1} sx={{ mb: 2 }} flexWrap="wrap" useFlexGap>
          <Typography variant="caption" color="text.secondary" sx={{ alignSelf: 'center' }}>
            By node type:
          </Typography>
          {summary.by_node_type.map((t) => (
            <Chip
              key={t.node_type}
              label={`${t.node_type}: ${t.n}`}
              size="small"
              variant="outlined"
              sx={{
                borderColor: NODE_TYPE_COLOR[t.node_type] ?? '#888',
                color: NODE_TYPE_COLOR[t.node_type] ?? 'inherit',
              }}
            />
          ))}
        </Stack>
      ) : null}

      <Grid container spacing={2}>
        <Grid item xs={12} md={8}>
          <Paper sx={{ p: 2, height: 520, display: 'flex', flexDirection: 'column' }}>
            <Typography variant="subtitle2" sx={{ mb: 1 }}>
              2D PCA projection ({points.length} nodes)
            </Typography>
            {projQ.isLoading ? (
              <Skeleton height={460} />
            ) : points.length === 0 ? (
              <Alert severity="info">
                No embeddings yet. Run <code>python scripts/compute_node2vec.py</code>{' '}
                to populate.
              </Alert>
            ) : (
              <ScatterPlot
                points={points}
                onNodeClick={(p) => {
                  setNodeId(p.node_id);
                  setLookupNodeId(p.node_id);
                }}
              />
            )}
          </Paper>
        </Grid>
        <Grid item xs={12} md={4}>
          <Paper sx={{ p: 2, height: 520, display: 'flex', flexDirection: 'column' }}>
            <Typography variant="subtitle2" sx={{ mb: 1 }}>
              Find similar nodes
            </Typography>
            <TextField
              size="small"
              fullWidth
              placeholder="Paste a node_id or click a scatter point"
              value={nodeId}
              onChange={(e) => setNodeId(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && nodeId.trim()) setLookupNodeId(nodeId.trim());
              }}
              InputProps={{
                startAdornment: (
                  <InputAdornment position="start">
                    <SearchIcon fontSize="small" />
                  </InputAdornment>
                ),
              }}
              sx={{ mb: 1 }}
            />
            <Divider sx={{ mb: 1 }} />
            <Box sx={{ flex: 1, overflowY: 'auto' }}>
              {!lookupNodeId ? (
                <Typography variant="body2" color="text.secondary">
                  Enter a node_id to see its 10 nearest neighbors by cosine similarity.
                </Typography>
              ) : similarQ.isLoading ? (
                <Skeleton height={300} />
              ) : similarQ.isError ? (
                <Alert severity="warning">{(similarQ.error as Error)?.message}</Alert>
              ) : !similarQ.data ? null : (
                <Box>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                    Reference: <code>{similarQ.data.reference.node_id.slice(0, 12)}…</code>{' '}
                    <Chip label={similarQ.data.reference.node_type || ''} size="small" sx={{ height: 16, fontSize: 9 }} />
                  </Typography>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>Node</TableCell>
                        <TableCell>Type</TableCell>
                        <TableCell align="right">Cosine</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {similarQ.data.neighbors.map((n) => (
                        <TableRow key={n.node_id} hover>
                          <TableCell>
                            <Typography variant="caption" sx={{ fontFamily: 'monospace' }}>
                              {n.node_id.slice(0, 12)}…
                            </Typography>
                          </TableCell>
                          <TableCell>
                            <Chip
                              label={n.node_type || ''}
                              size="small"
                              sx={{ height: 16, fontSize: 9 }}
                            />
                          </TableCell>
                          <TableCell align="right">{fmt(n.similarity, 3)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </Box>
              )}
            </Box>
          </Paper>
        </Grid>
      </Grid>
    </Box>
  );
}

function ScatterPlot({
  points,
  onNodeClick,
}: {
  points: EmbeddingProjectionPoint[];
  onNodeClick: (p: EmbeddingProjectionPoint) => void;
}) {
  const W = 720;
  const H = 440;
  const pad = 24;

  const xs = points.map((p) => p.x);
  const ysCoords = points.map((p) => p.y);
  const minX = Math.min(...xs, 0);
  const maxX = Math.max(...xs, 1);
  const minY = Math.min(...ysCoords, 0);
  const maxY = Math.max(...ysCoords, 1);
  const rangeX = maxX - minX || 1;
  const rangeY = maxY - minY || 1;

  const sx = (x: number) => pad + ((x - minX) / rangeX) * (W - 2 * pad);
  const sy = (y: number) => H - pad - ((y - minY) / rangeY) * (H - 2 * pad);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ flex: 1, width: '100%', cursor: 'default' }}>
      {/* Axes */}
      <line x1={pad} y1={H - pad} x2={W - pad} y2={H - pad} stroke="#888" />
      <line x1={pad} y1={pad} x2={pad} y2={H - pad} stroke="#888" />
      {points.map((p) => (
        <circle
          key={p.node_id}
          cx={sx(p.x)}
          cy={sy(p.y)}
          r={4}
          fill={NODE_TYPE_COLOR[p.node_type] ?? '#888'}
          opacity={0.7}
          style={{ cursor: 'pointer' }}
          onClick={() => onNodeClick(p)}
        >
          <title>{`${p.node_type || 'TASK'} ${p.node_id.slice(0, 12)}…`}</title>
        </circle>
      ))}
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Learned Scorer tab (1B)
// ---------------------------------------------------------------------------
function LearnedScorerTab() {
  const navigate = useNavigate();
  const summaryQ = useLearnedScorerSummary();
  const [labeledOnly, setLabeledOnly] = useState(false);
  const predsQ = useLearnedScorerPredictions(100, labeledOnly);

  const summary = summaryQ.data;
  const active = summary?.active_model;
  const preds = predsQ.data?.predictions ?? [];

  return (
    <Box>
      {/* Top cards */}
      <Grid container spacing={2} sx={{ mb: 2 }}>
        <StatCard
          label="Mode"
          value={summary ? summary.w7_learned_quality.mode : undefined}
          loading={summaryQ.isLoading}
          highlight={summary?.w7_learned_quality.mode === 'LIVE'}
        />
        <StatCard
          label="w7 weight"
          value={summary ? fmt(summary.w7_learned_quality.value, 3) : undefined}
          loading={summaryQ.isLoading}
        />
        <StatCard label="Val accuracy" value={active ? fmt(active.val_accuracy, 3) : undefined} loading={summaryQ.isLoading} />
        <StatCard label="Val AUC" value={active ? fmt(active.val_auc, 3) : undefined} loading={summaryQ.isLoading} />
        <StatCard label="Samples" value={active?.n_samples} loading={summaryQ.isLoading} />
        <StatCard label="Real labels" value={active?.n_real} loading={summaryQ.isLoading} />
        <StatCard label="Synthetic" value={active?.n_synthetic} loading={summaryQ.isLoading} />
        <StatCard label="Predictions" value={summary?.prediction_stats.total} loading={summaryQ.isLoading} />
      </Grid>

      {/* Active model card */}
      <Paper sx={{ p: 2, mb: 2 }}>
        <Typography variant="subtitle2" sx={{ mb: 1 }}>
          Active model
        </Typography>
        {summaryQ.isLoading ? (
          <Skeleton height={40} />
        ) : !active ? (
          <Alert severity="info">
            No active model yet. Run <code>python scripts/train_learned_scorer.py</code>{' '}
            to bootstrap one.
          </Alert>
        ) : (
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            <Chip
              label={active.model_version}
              size="small"
              color="primary"
              sx={{ fontFamily: 'monospace' }}
            />
            <Chip label={active.algorithm} size="small" variant="outlined" />
            <Chip
              label={`${active.n_features} features`}
              size="small"
              variant="outlined"
            />
            <Chip
              label={`MAE vs heuristic: ${fmt(summary?.prediction_stats.mae_vs_heuristic, 3)}`}
              size="small"
              variant="outlined"
            />
            <Chip
              label={`avg learned: ${fmt(summary?.prediction_stats.avg_learned, 3)}`}
              size="small"
              variant="outlined"
            />
            <Chip
              label={`avg heuristic: ${fmt(summary?.prediction_stats.avg_heuristic, 3)}`}
              size="small"
              variant="outlined"
            />
          </Stack>
        )}
      </Paper>

      {/* Predictions log */}
      <Paper sx={{ p: 2 }}>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
          <Typography variant="subtitle2">
            Shadow predictions ({preds.length})
          </Typography>
          <Chip
            label={labeledOnly ? 'labeled only' : 'all'}
            size="small"
            onClick={() => setLabeledOnly(!labeledOnly)}
            variant="outlined"
            sx={{ cursor: 'pointer' }}
          />
          <Chip label="Click a trace to open governance view" size="small" variant="outlined" />
        </Stack>
        {predsQ.isLoading ? (
          <Skeleton height={200} />
        ) : preds.length === 0 ? (
          <Alert severity="info">
            No predictions yet. They're logged every time the pipeline runs a scored node.
          </Alert>
        ) : (
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Time</TableCell>
                <TableCell>Agent</TableCell>
                <TableCell align="right">Heuristic</TableCell>
                <TableCell align="right">Learned</TableCell>
                <TableCell align="right">Δ</TableCell>
                <TableCell>Feedback</TableCell>
                <TableCell>Trace</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {preds.map((p) => (
                <PredictionRow key={p.prediction_id} p={p} onOpenTrace={(t) => navigate(`/model-governance?trace=${t}`)} />
              ))}
            </TableBody>
          </Table>
        )}
      </Paper>
    </Box>
  );
}

function PredictionRow({
  p,
  onOpenTrace,
}: {
  p: LearnedScorerPrediction;
  onOpenTrace: (traceId: string) => void;
}) {
  const delta = p.delta ?? 0;
  const deltaColor =
    Math.abs(delta) < 0.1 ? 'default' : delta > 0 ? 'success' : 'error';
  return (
    <TableRow>
      <TableCell>
        <Typography variant="caption">{fmtTs(p.created_at)}</Typography>
      </TableCell>
      <TableCell>{p.agent_name || (p.agent_id ?? '').slice(0, 8) || '—'}</TableCell>
      <TableCell align="right">
        {p.heuristic_score !== null ? (
          <Chip
            label={fmt(p.heuristic_score, 2)}
            size="small"
            color={p.heuristic_score >= 0.7 ? 'success' : p.heuristic_score >= 0.5 ? 'warning' : 'error'}
            sx={{ height: 18, fontSize: 10 }}
          />
        ) : '—'}
      </TableCell>
      <TableCell align="right">
        <Chip
          label={fmt(p.learned_score, 2)}
          size="small"
          color={p.learned_score >= 0.7 ? 'success' : p.learned_score >= 0.5 ? 'warning' : 'error'}
          sx={{ height: 18, fontSize: 10 }}
        />
      </TableCell>
      <TableCell align="right">
        <Chip
          label={(delta >= 0 ? '+' : '') + fmt(delta, 2)}
          size="small"
          color={deltaColor as any}
          sx={{ height: 18, fontSize: 10 }}
        />
      </TableCell>
      <TableCell>
        {p.user_feedback ? (
          <Chip
            label={p.user_feedback}
            size="small"
            color={p.user_feedback === 'positive' ? 'success' : 'error'}
            sx={{ height: 16, fontSize: 9 }}
          />
        ) : (
          '—'
        )}
      </TableCell>
      <TableCell>
        {p.trace_id ? (
          <MuiLink
            component="button"
            onClick={() => onOpenTrace(p.trace_id!)}
            underline="hover"
            sx={{ fontSize: 11, fontFamily: 'monospace' }}
          >
            {p.trace_id.slice(0, 8)}…
            <OpenInNewIcon sx={{ fontSize: 11, ml: 0.25, verticalAlign: 'middle' }} />
          </MuiLink>
        ) : '—'}
      </TableCell>
    </TableRow>
  );
}

// ---------------------------------------------------------------------------
// SOP Discovery tab (2D)
// ---------------------------------------------------------------------------
function SOPDiscoveryTab() {
  const [statusFilter, setStatusFilter] = useState<string>('PENDING');
  const proposalsQ = useSOPProposals(statusFilter || undefined, 50);
  const promote = usePromoteSOP();
  const reject = useRejectSOP();

  const proposals = proposalsQ.data?.proposals ?? [];

  return (
    <Box>
      <Paper sx={{ p: 2, mb: 2 }}>
        <Stack direction="row" spacing={1} alignItems="center">
          <Typography variant="subtitle2">Filter:</Typography>
          {(['PENDING', 'PROMOTED', 'REJECTED', ''] as const).map((s) => (
            <Chip
              key={s || 'ALL'}
              label={s || 'ALL'}
              size="small"
              onClick={() => setStatusFilter(s)}
              color={statusFilter === s ? 'primary' : 'default'}
              variant={statusFilter === s ? 'filled' : 'outlined'}
              sx={{ cursor: 'pointer' }}
            />
          ))}
          <Box sx={{ flex: 1 }} />
          <Typography variant="caption" color="text.secondary">
            Run <code>python scripts/discover_sops.py</code> weekly to refresh.
          </Typography>
        </Stack>
      </Paper>

      {proposalsQ.isLoading ? (
        <Skeleton height={300} />
      ) : proposals.length === 0 ? (
        <Alert severity="info">
          No {statusFilter.toLowerCase() || ''} proposals yet. The discovery script
          produced zero clusters in the current window.
        </Alert>
      ) : (
        <Grid container spacing={2}>
          {proposals.map((p) => (
            <Grid item xs={12} md={6} key={p.proposal_id}>
              <SOPProposalCard
                p={p}
                onPromote={() => promote.mutate(p.proposal_id)}
                onReject={() => reject.mutate(p.proposal_id)}
                promoting={promote.isPending}
                rejecting={reject.isPending}
              />
            </Grid>
          ))}
        </Grid>
      )}
    </Box>
  );
}

function SOPProposalCard({
  p,
  onPromote,
  onReject,
  promoting,
  rejecting,
}: {
  p: SOPProposal;
  onPromote: () => void;
  onReject: () => void;
  promoting: boolean;
  rejecting: boolean;
}) {
  const statusColor =
    p.status === 'PROMOTED' ? 'success' : p.status === 'REJECTED' ? 'error' : 'default';
  return (
    <Paper sx={{ p: 2, height: '100%', display: 'flex', flexDirection: 'column' }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
        <Chip label={p.status} size="small" color={statusColor as any} />
        <Chip label={`cluster size ${p.cluster_size}`} size="small" variant="outlined" />
        {p.avg_score !== null && (
          <Chip
            label={`avg score ${fmt(p.avg_score, 2)}`}
            size="small"
            variant="outlined"
            color={p.avg_score >= 0.7 ? 'success' : 'warning'}
          />
        )}
        {p.best_agent_name && (
          <Chip label={`best: ${p.best_agent_name}`} size="small" variant="outlined" />
        )}
      </Stack>

      <Typography variant="body2" sx={{ mb: 1, fontWeight: 500 }}>
        {p.summary}
      </Typography>

      {p.keywords.length > 0 && (
        <Stack direction="row" spacing={0.5} sx={{ mb: 1, flexWrap: 'wrap' }} useFlexGap>
          {p.keywords.slice(0, 8).map((k) => (
            <Chip
              key={k}
              label={k}
              size="small"
              variant="outlined"
              sx={{ height: 18, fontSize: 10 }}
            />
          ))}
        </Stack>
      )}

      <Box sx={{ flex: 1, overflow: 'auto', mb: 1 }}>
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
          Sample messages ({p.sample_messages.length}):
        </Typography>
        {p.sample_messages.slice(0, 3).map((m, i) => (
          <Paper
            key={i}
            variant="outlined"
            sx={{
              p: 1,
              mb: 0.5,
              fontSize: 11,
              color: 'text.secondary',
              maxHeight: 60,
              overflow: 'hidden',
            }}
          >
            {m.slice(0, 180)}
            {m.length > 180 ? '…' : ''}
          </Paper>
        ))}
      </Box>

      {p.status === 'PENDING' ? (
        <Stack direction="row" spacing={1}>
          <Button
            size="small"
            variant="contained"
            color="success"
            startIcon={<CheckIcon />}
            onClick={onPromote}
            disabled={promoting || rejecting}
          >
            Promote
          </Button>
          <Button
            size="small"
            variant="outlined"
            color="error"
            startIcon={<CloseIcon />}
            onClick={onReject}
            disabled={promoting || rejecting}
          >
            Reject
          </Button>
        </Stack>
      ) : (
        <Typography variant="caption" color="text.secondary">
          {p.status === 'PROMOTED' && p.promoted_sop_id && (
            <>Promoted to SOP <code>{p.promoted_sop_id}</code></>
          )}
          {p.reviewed_by && ` by ${p.reviewed_by}`}
          {p.reviewed_at && ` at ${fmtTs(p.reviewed_at)}`}
        </Typography>
      )}
    </Paper>
  );
}

// ---------------------------------------------------------------------------
// Shared
// ---------------------------------------------------------------------------
function StatCard({
  label,
  value,
  loading,
  highlight,
}: {
  label: string;
  value: number | string | undefined;
  loading?: boolean;
  highlight?: boolean;
}) {
  return (
    <Grid item xs={6} sm={3} md={1.5}>
      <Paper
        variant="outlined"
        sx={{
          p: 1,
          textAlign: 'center',
          borderColor: highlight ? 'warning.main' : undefined,
        }}
      >
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
          {label}
        </Typography>
        {loading ? (
          <Skeleton height={24} />
        ) : (
          <Typography variant="h6" fontWeight={600} sx={{ fontSize: 16 }}>
            {value ?? '—'}
          </Typography>
        )}
      </Paper>
    </Grid>
  );
}
