import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  Box,
  Breadcrumbs,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Drawer,
  FormControl,
  Grid,
  IconButton,
  InputLabel,
  Link as MuiLink,
  MenuItem,
  Paper,
  Select,
  Skeleton,
  Snackbar,
  Stack,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tabs,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import AttachMoneyIcon from '@mui/icons-material/AttachMoney';
import LaunchIcon from '@mui/icons-material/Launch';
import RefreshIcon from '@mui/icons-material/Refresh';
import SwapHorizIcon from '@mui/icons-material/SwapHoriz';
import CloseIcon from '@mui/icons-material/Close';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip as RTooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  FinOpsBreakdownFilters,
  FinOpsBreakdownRow,
  FinOpsConversationRow,
  FinOpsGroupBy,
  FinOpsPeriod,
  FinOpsSummary,
  PricingRow,
  PricingUpsertBody,
  useFinOpsBreakdown,
  useFinOpsConversationDetail,
  useFinOpsConversations,
  useFinOpsPricing,
  useFinOpsSummary,
  useFinOpsWhatIf,
  useUpsertPricing,
} from '@/api/finops';
import { useAgents, useUpdateAgent } from '@/api/agents';

const PERIODS: FinOpsPeriod[] = ['24h', '7d', '30d', '90d', 'all'];
const PIE_COLORS = ['#1976d2', '#388e3c', '#ed6c02', '#7b1fa2', '#c62828', '#0288d1', '#5d4037'];

function fmtMoney(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '$0.00';
  if (Math.abs(n) >= 1000) return `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  if (Math.abs(n) >= 1) return `$${n.toFixed(2)}`;
  return `$${n.toFixed(4)}`;
}

function fmtInt(n: number | null | undefined): string {
  if (n === null || n === undefined) return '0';
  return Math.round(Number(n)).toLocaleString();
}

function fmtPct(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  return `${n.toFixed(1)}%`;
}

function fmtTs(s: string | null | undefined): string {
  if (!s) return '—';
  try {
    return new Date(s).toLocaleString();
  } catch {
    return String(s);
  }
}

// ---------------------------------------------------------------------------
// Page shell
// ---------------------------------------------------------------------------
export default function FinancialGovernancePage() {
  const [tab, setTab] = useState(0);
  const [period, setPeriod] = useState<FinOpsPeriod>('7d');

  return (
    <Box>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
        <AttachMoneyIcon color="primary" />
        <Typography variant="h5" fontWeight={600}>
          Financial Governance
        </Typography>
        <Chip label="LLM cost & attribution" size="small" variant="outlined" />
        <Box sx={{ flex: 1 }} />
        <FormControl size="small" sx={{ minWidth: 140 }}>
          <InputLabel>Period</InputLabel>
          <Select label="Period" value={period} onChange={(e) => setPeriod(e.target.value as FinOpsPeriod)}>
            {PERIODS.map((p) => (
              <MenuItem key={p} value={p}>
                {p === 'all' ? 'All time' : `Last ${p}`}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      </Stack>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Token cost across every LLM call made by the orchestrator, translator, and
        meta-assembly services. Drill from service → team → agent → tool →
        conversation, deep-link any conversation to its full reasoning trace, and
        simulate model-swap savings before flipping an agent to a cheaper provider.
      </Typography>

      <Paper sx={{ mb: 2 }}>
        <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="scrollable" scrollButtons="auto">
          <Tab label="Overview" />
          <Tab label="Drill-Down" />
          <Tab label="Conversations" />
          <Tab label="Users" />
          <Tab label="Model What-If" />
          <Tab label="Pricing Admin" />
        </Tabs>
      </Paper>

      {tab === 0 && <OverviewTab period={period} />}
      {tab === 1 && <DrillDownTab period={period} />}
      {tab === 2 && <ConversationsTab period={period} />}
      {tab === 3 && <UsersTab period={period} />}
      {tab === 4 && <WhatIfTab />}
      {tab === 5 && <PricingTab />}
    </Box>
  );
}

// ---------------------------------------------------------------------------
// Overview tab
// ---------------------------------------------------------------------------
function OverviewTab({ period }: { period: FinOpsPeriod }) {
  const q = useFinOpsSummary(period);
  if (q.isLoading) return <Skeleton variant="rectangular" height={500} />;
  if (q.isError) return <Alert severity="error">{(q.error as Error)?.message}</Alert>;
  const s: FinOpsSummary | undefined = q.data;
  if (!s) return <Alert severity="info">No data yet — send a chat to start tracking cost.</Alert>;
  const t = s.totals;

  const providerData = (s.by_provider || []).map((r, i) => ({
    name: r.provider, value: Number(r.cost_usd) || 0, fill: PIE_COLORS[i % PIE_COLORS.length],
  }));
  const serviceData = (s.by_service || []).map((r) => ({
    name: r.service_name, cost: Number(r.cost_usd) || 0, calls: r.n_calls,
  }));
  const trendData = (s.daily_trend || []).map((p) => ({
    d: (p.d || '').slice(5, 10), cost: Number(p.cost_usd) || 0, tokens: p.tokens,
  }));

  return (
    <Box>
      <Grid container spacing={2} sx={{ mb: 2 }}>
        <KPI label="Total cost" value={fmtMoney(t.cost_usd)} highlight />
        <KPI label="Total tokens" value={fmtInt(t.total_tokens)} />
        <KPI label="LLM calls" value={fmtInt(t.n_calls)} />
        <KPI label="Avg $ / call" value={t.n_calls > 0 ? fmtMoney(t.cost_usd / t.n_calls) : '—'} />
        <KPI label="Conversations" value={fmtInt(t.n_conversations)} />
        <KPI label="Active users" value={fmtInt(t.n_users)} />
        <KPI label="Active agents" value={fmtInt(t.n_agents)} />
        <KPI label="Avg latency (ms)" value={fmtInt(t.avg_latency_ms)} />
      </Grid>

      <Grid container spacing={2} sx={{ mb: 2 }}>
        <Grid item xs={12} md={8}>
          <Paper sx={{ p: 2, height: 320 }}>
            <Typography variant="subtitle2" sx={{ mb: 1 }}>Daily cost trend (last 30 days)</Typography>
            <ResponsiveContainer width="100%" height="90%">
              <LineChart data={trendData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="d" />
                <YAxis tickFormatter={(v) => fmtMoney(v)} />
                <RTooltip formatter={(v: number) => fmtMoney(v)} />
                <Line type="monotone" dataKey="cost" stroke="#1976d2" strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </Paper>
        </Grid>
        <Grid item xs={12} md={4}>
          <Paper sx={{ p: 2, height: 320 }}>
            <Typography variant="subtitle2" sx={{ mb: 1 }}>Cost by provider</Typography>
            <ResponsiveContainer width="100%" height="90%">
              <PieChart>
                <Pie data={providerData} dataKey="value" nameKey="name" outerRadius={90} label={(e) => e.name}>
                  {providerData.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
                </Pie>
                <RTooltip formatter={(v: number) => fmtMoney(v)} />
              </PieChart>
            </ResponsiveContainer>
          </Paper>
        </Grid>
      </Grid>

      <Grid container spacing={2} sx={{ mb: 2 }}>
        <Grid item xs={12}>
          <Paper sx={{ p: 2, height: 280 }}>
            <Typography variant="subtitle2" sx={{ mb: 1 }}>Cost by service</Typography>
            <ResponsiveContainer width="100%" height="90%">
              <BarChart data={serviceData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" />
                <YAxis tickFormatter={(v) => fmtMoney(v)} />
                <RTooltip formatter={(v: number) => fmtMoney(v)} />
                <Legend />
                <Bar dataKey="cost" fill="#388e3c" name="Cost ($)" />
              </BarChart>
            </ResponsiveContainer>
          </Paper>
        </Grid>
      </Grid>

      <Grid container spacing={2}>
        <Grid item xs={12} md={4}>
          <TopTable
            title="Top agents by cost"
            rows={s.top_agents.map((a) => ({
              label: a.agent_name, sub: a.foundation_model || '', cost_usd: a.cost_usd, n_calls: a.n_calls,
            }))}
          />
        </Grid>
        <Grid item xs={12} md={4}>
          <TopTable
            title="Top models by cost"
            rows={s.top_models.map((m) => ({
              label: m.model, sub: m.provider, cost_usd: m.cost_usd, n_calls: m.n_calls,
            }))}
          />
        </Grid>
        <Grid item xs={12} md={4}>
          <TopTable
            title="Top users by cost"
            rows={s.top_users.map((u) => ({
              label: u.user_id, sub: `${u.n_conversations} conversations`, cost_usd: u.cost_usd, n_calls: u.n_calls,
            }))}
          />
        </Grid>
      </Grid>
    </Box>
  );
}

function KPI({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <Grid item xs={6} sm={3} md={1.5}>
      <Paper variant="outlined" sx={{ p: 1.25, textAlign: 'center', borderColor: highlight ? 'primary.main' : undefined }}>
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>{label}</Typography>
        <Typography variant="h6" fontWeight={600} noWrap>{value}</Typography>
      </Paper>
    </Grid>
  );
}

function TopTable({ title, rows }: { title: string; rows: Array<{ label: string; sub: string; cost_usd: number; n_calls: number }> }) {
  return (
    <Paper sx={{ p: 1.5 }}>
      <Typography variant="subtitle2" sx={{ mb: 1 }}>{title}</Typography>
      {rows.length === 0 ? (
        <Typography variant="caption" color="text.secondary">No data</Typography>
      ) : (
        <Table size="small">
          <TableBody>
            {rows.map((r, i) => (
              <TableRow key={i}>
                <TableCell sx={{ maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  <Tooltip title={r.label}><span>{r.label}</span></Tooltip>
                  {r.sub && (
                    <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }} noWrap>
                      {r.sub}
                    </Typography>
                  )}
                </TableCell>
                <TableCell align="right">{fmtMoney(r.cost_usd)}</TableCell>
                <TableCell align="right" sx={{ color: 'text.secondary', fontSize: 11 }}>
                  {fmtInt(r.n_calls)} calls
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Paper>
  );
}

// ---------------------------------------------------------------------------
// Drill-Down tab — service → team → agent → tool/model → conversation
// ---------------------------------------------------------------------------
const DRILL_ORDER: FinOpsGroupBy[] = ['service', 'team', 'agent', 'model', 'conversation'];

function DrillDownTab({ period }: { period: FinOpsPeriod }) {
  const navigate = useNavigate();
  const [crumbs, setCrumbs] = useState<Array<{ group_by: FinOpsGroupBy; key: string; label: string }>>([]);
  const groupBy = DRILL_ORDER[Math.min(crumbs.length, DRILL_ORDER.length - 1)];

  const filters: FinOpsBreakdownFilters = useMemo(() => {
    const f: FinOpsBreakdownFilters = {};
    for (const c of crumbs) {
      if (c.group_by === 'service') f.service_name = c.key;
      if (c.group_by === 'team') f.team_id = c.key;
      if (c.group_by === 'agent') f.agent_id = c.key;
      if (c.group_by === 'model') f.model = c.key;
      if (c.group_by === 'user') f.user_id = c.key;
    }
    return f;
  }, [crumbs]);

  const q = useFinOpsBreakdown(groupBy, period, filters);
  const rows = q.data?.rows || [];

  return (
    <Box>
      <Stack direction="row" spacing={1} sx={{ mb: 2 }} alignItems="center" flexWrap="wrap" useFlexGap>
        <Typography variant="caption" color="text.secondary">Drill:</Typography>
        <Breadcrumbs separator="›" sx={{ flex: 1 }}>
          <MuiLink component="button" onClick={() => setCrumbs([])} underline="hover">All services</MuiLink>
          {crumbs.map((c, i) => (
            <MuiLink
              key={i}
              component="button"
              onClick={() => setCrumbs(crumbs.slice(0, i + 1))}
              underline="hover"
            >
              {c.label || c.key}
            </MuiLink>
          ))}
        </Breadcrumbs>
        <Chip label={`Group by: ${groupBy}`} size="small" />
      </Stack>

      {q.isLoading ? (
        <Skeleton height={300} />
      ) : rows.length === 0 ? (
        <Alert severity="info">No data at this level.</Alert>
      ) : (
        <Paper>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{capitalize(groupBy)}</TableCell>
                <TableCell align="right">Cost</TableCell>
                <TableCell align="right">Tokens</TableCell>
                <TableCell align="right">Calls</TableCell>
                <TableCell align="right">Avg latency</TableCell>
                <TableCell align="right">Action</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.key} hover>
                  <TableCell sx={{ fontFamily: groupBy === 'conversation' ? 'monospace' : undefined, fontSize: 12 }}>
                    <Tooltip title={r.key}><span>{r.label || r.key}</span></Tooltip>
                  </TableCell>
                  <TableCell align="right" sx={{ fontWeight: 600 }}>{fmtMoney(r.cost_usd)}</TableCell>
                  <TableCell align="right">{fmtInt(r.tokens)}</TableCell>
                  <TableCell align="right">{fmtInt(r.n_calls)}</TableCell>
                  <TableCell align="right">{r.avg_latency_ms ? `${Math.round(r.avg_latency_ms)} ms` : '—'}</TableCell>
                  <TableCell align="right">
                    {groupBy === 'conversation' && (
                      <Button
                        size="small"
                        startIcon={<LaunchIcon />}
                        onClick={() => navigate(`/model-governance?trace=${encodeURIComponent(r.key)}`)}
                      >
                        Trace
                      </Button>
                    )}
                    {groupBy !== 'conversation' && (
                      <Button
                        size="small"
                        onClick={() =>
                          setCrumbs([
                            ...crumbs,
                            { group_by: groupBy, key: r.key, label: r.label || r.key },
                          ])
                        }
                      >
                        Drill ▸
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Paper>
      )}
    </Box>
  );
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// ---------------------------------------------------------------------------
// Conversations tab
// ---------------------------------------------------------------------------
function ConversationsTab({ period }: { period: FinOpsPeriod }) {
  const navigate = useNavigate();
  const [orderBy, setOrderBy] = useState<'cost' | 'tokens' | 'calls'>('cost');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const q = useFinOpsConversations(period, orderBy);
  const rows = q.data?.rows || [];

  return (
    <Box>
      <Stack direction="row" spacing={1} sx={{ mb: 1 }} alignItems="center">
        <Typography variant="caption" color="text.secondary">Order by:</Typography>
        {(['cost', 'tokens', 'calls'] as const).map((o) => (
          <Chip
            key={o} label={o} size="small"
            color={orderBy === o ? 'primary' : 'default'}
            variant={orderBy === o ? 'filled' : 'outlined'}
            onClick={() => setOrderBy(o)}
            sx={{ cursor: 'pointer' }}
          />
        ))}
        <Box sx={{ flex: 1 }} />
        <IconButton size="small" onClick={() => q.refetch()}><RefreshIcon fontSize="small" /></IconButton>
      </Stack>

      {q.isLoading ? <Skeleton height={400} /> : rows.length === 0 ? (
        <Alert severity="info">No conversations recorded in this period.</Alert>
      ) : (
        <Paper>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Conversation</TableCell>
                <TableCell>User</TableCell>
                <TableCell>Team</TableCell>
                <TableCell align="right">Calls</TableCell>
                <TableCell align="right">Tokens</TableCell>
                <TableCell align="right">Cost</TableCell>
                <TableCell>Last call</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((r: FinOpsConversationRow) => (
                <TableRow key={r.conversation_id} hover sx={{ cursor: 'pointer' }} onClick={() => setSelectedId(r.conversation_id)}>
                  <TableCell sx={{ fontFamily: 'monospace', fontSize: 12, maxWidth: 220 }}>
                    <Tooltip title={r.title || r.conversation_id}>
                      <span>{(r.title || r.conversation_id).slice(0, 30)}…</span>
                    </Tooltip>
                  </TableCell>
                  <TableCell>{r.user_id || '—'}</TableCell>
                  <TableCell>{r.team_id || '—'}</TableCell>
                  <TableCell align="right">{fmtInt(r.n_calls)}</TableCell>
                  <TableCell align="right">{fmtInt(r.tokens)}</TableCell>
                  <TableCell align="right" sx={{ fontWeight: 600 }}>{fmtMoney(r.cost_usd)}</TableCell>
                  <TableCell sx={{ fontSize: 11 }}>{fmtTs(r.last_call_ts)}</TableCell>
                  <TableCell align="right" onClick={(e) => e.stopPropagation()}>
                    {r.sample_trace_id && (
                      <Tooltip title="Open in Model Governance">
                        <IconButton size="small" onClick={() => navigate(`/model-governance?trace=${encodeURIComponent(r.sample_trace_id!)}`)}>
                          <LaunchIcon fontSize="inherit" />
                        </IconButton>
                      </Tooltip>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Paper>
      )}

      <ConversationDrawer conversationId={selectedId} onClose={() => setSelectedId(null)} />
    </Box>
  );
}

function ConversationDrawer({ conversationId, onClose }: { conversationId: string | null; onClose: () => void }) {
  const navigate = useNavigate();
  const q = useFinOpsConversationDetail(conversationId);
  const data = q.data;

  return (
    <Drawer anchor="right" open={!!conversationId} onClose={onClose} PaperProps={{ sx: { width: 640 } }}>
      <Box sx={{ p: 2, height: '100%', display: 'flex', flexDirection: 'column' }}>
        <Stack direction="row" alignItems="center" sx={{ mb: 1 }}>
          <Typography variant="subtitle1" fontWeight={600} sx={{ flex: 1 }}>
            Conversation cost detail
          </Typography>
          <IconButton size="small" onClick={onClose}><CloseIcon fontSize="small" /></IconButton>
        </Stack>
        {q.isLoading ? <Skeleton height={300} /> : !data ? (
          <Alert severity="warning">Conversation not found.</Alert>
        ) : (
          <Box sx={{ flex: 1, overflowY: 'auto' }}>
            <Stack direction="row" spacing={1} sx={{ mb: 2 }}>
              <Chip label={`Cost: ${fmtMoney(data.summary.cost_usd)}`} color="primary" />
              <Chip label={`${fmtInt(data.summary.total_tokens)} tokens`} variant="outlined" />
              <Chip label={`${fmtInt(data.summary.n_calls)} calls`} variant="outlined" />
              <Chip label={`${data.summary.n_services} services`} variant="outlined" />
            </Stack>

            <Typography variant="subtitle2" sx={{ mb: 0.5 }}>Cost by service</Typography>
            <Table size="small" sx={{ mb: 2 }}>
              <TableBody>
                {data.by_service.map((b) => (
                  <TableRow key={b.service_name}>
                    <TableCell>{b.service_name}</TableCell>
                    <TableCell align="right">{fmtInt(b.n_calls)} calls</TableCell>
                    <TableCell align="right" sx={{ fontWeight: 600 }}>{fmtMoney(b.cost_usd)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>

            <Typography variant="subtitle2" sx={{ mb: 0.5 }}>Cost by agent</Typography>
            <Table size="small" sx={{ mb: 2 }}>
              <TableBody>
                {data.by_agent.map((b) => (
                  <TableRow key={b.agent_id}>
                    <TableCell>{b.agent_name}</TableCell>
                    <TableCell align="right">{fmtInt(b.n_calls)} calls</TableCell>
                    <TableCell align="right" sx={{ fontWeight: 600 }}>{fmtMoney(b.cost_usd)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>

            <Typography variant="subtitle2" sx={{ mb: 0.5 }}>LLM call timeline</Typography>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Time</TableCell>
                  <TableCell>Service</TableCell>
                  <TableCell>Agent</TableCell>
                  <TableCell>Model</TableCell>
                  <TableCell align="right">Tokens</TableCell>
                  <TableCell align="right">Cost</TableCell>
                  <TableCell align="right">Trace</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {data.calls.map((c) => (
                  <TableRow key={c.call_id}>
                    <TableCell sx={{ fontSize: 11 }}>{fmtTs(c.ts)}</TableCell>
                    <TableCell><Chip size="small" label={c.service_name} /></TableCell>
                    <TableCell sx={{ fontSize: 12 }}>{c.agent_name || '—'}</TableCell>
                    <TableCell sx={{ fontSize: 12 }}>{c.provider}/{c.model}</TableCell>
                    <TableCell align="right">{fmtInt(c.total_tokens)}</TableCell>
                    <TableCell align="right" sx={{ fontWeight: 600 }}>{fmtMoney(c.cost_usd)}</TableCell>
                    <TableCell align="right">
                      {c.trace_id && (
                        <IconButton size="small" onClick={() => navigate(`/model-governance?trace=${encodeURIComponent(c.trace_id!)}`)}>
                          <LaunchIcon fontSize="inherit" />
                        </IconButton>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Box>
        )}
      </Box>
    </Drawer>
  );
}

// ---------------------------------------------------------------------------
// Users tab
// ---------------------------------------------------------------------------
function UsersTab({ period }: { period: FinOpsPeriod }) {
  const q = useFinOpsBreakdown('user', period, {}, 100);
  const rows = q.data?.rows || [];
  const [drillUser, setDrillUser] = useState<string | null>(null);

  if (q.isLoading) return <Skeleton height={300} />;
  if (rows.length === 0) return <Alert severity="info">No user attribution recorded yet. Make sure the gateway is forwarding x-user-id.</Alert>;

  return (
    <Box>
      <Paper>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>User</TableCell>
              <TableCell align="right">Calls</TableCell>
              <TableCell align="right">Tokens</TableCell>
              <TableCell align="right">Cost</TableCell>
              <TableCell align="right">Action</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((r: FinOpsBreakdownRow) => (
              <TableRow key={r.key} hover>
                <TableCell sx={{ fontFamily: 'monospace', fontSize: 12 }}>{r.label}</TableCell>
                <TableCell align="right">{fmtInt(r.n_calls)}</TableCell>
                <TableCell align="right">{fmtInt(r.tokens)}</TableCell>
                <TableCell align="right" sx={{ fontWeight: 600 }}>{fmtMoney(r.cost_usd)}</TableCell>
                <TableCell align="right">
                  <Button size="small" onClick={() => setDrillUser(r.key)}>Conversations</Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Paper>
      <UserConversationsDrawer userId={drillUser} period={period} onClose={() => setDrillUser(null)} />
    </Box>
  );
}

function UserConversationsDrawer({ userId, period, onClose }: { userId: string | null; period: FinOpsPeriod; onClose: () => void }) {
  const navigate = useNavigate();
  const q = useFinOpsConversations(period, 'cost', userId || undefined, 50);
  const rows = q.data?.rows || [];

  return (
    <Drawer anchor="right" open={!!userId} onClose={onClose} PaperProps={{ sx: { width: 640 } }}>
      <Box sx={{ p: 2 }}>
        <Stack direction="row" alignItems="center" sx={{ mb: 1 }}>
          <Typography variant="subtitle1" fontWeight={600} sx={{ flex: 1 }}>
            Conversations for {userId}
          </Typography>
          <IconButton size="small" onClick={onClose}><CloseIcon fontSize="small" /></IconButton>
        </Stack>
        {q.isLoading ? <Skeleton height={200} /> : rows.length === 0 ? (
          <Alert severity="info">No conversations.</Alert>
        ) : (
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Conversation</TableCell>
                <TableCell align="right">Calls</TableCell>
                <TableCell align="right">Cost</TableCell>
                <TableCell />
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.conversation_id} hover>
                  <TableCell sx={{ fontFamily: 'monospace', fontSize: 12 }}>
                    {(r.title || r.conversation_id).slice(0, 30)}…
                  </TableCell>
                  <TableCell align="right">{fmtInt(r.n_calls)}</TableCell>
                  <TableCell align="right" sx={{ fontWeight: 600 }}>{fmtMoney(r.cost_usd)}</TableCell>
                  <TableCell align="right">
                    {r.sample_trace_id && (
                      <IconButton size="small" onClick={() => navigate(`/model-governance?trace=${encodeURIComponent(r.sample_trace_id!)}`)}>
                        <LaunchIcon fontSize="inherit" />
                      </IconButton>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Box>
    </Drawer>
  );
}

// ---------------------------------------------------------------------------
// Model What-If tab
// ---------------------------------------------------------------------------
function WhatIfTab() {
  const agentsQ = useAgents();
  const pricingQ = useFinOpsPricing();
  const updateAgent = useUpdateAgent();
  const [agentId, setAgentId] = useState<string>('');
  const [candidate, setCandidate] = useState<string>('');
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [snack, setSnack] = useState<{ open: boolean; msg: string; sev: 'success' | 'error' | 'info' }>({ open: false, msg: '', sev: 'success' });
  const whatIfQ = useFinOpsWhatIf(agentId || null, candidate || null, '30d');
  const result = whatIfQ.data;

  const agents = agentsQ.data || [];
  const pricingRows = pricingQ.data?.rows || [];
  const selectedAgent = agents.find((a: any) => a.agent_id === agentId);

  const handleApply = () => {
    if (!agentId || !candidate) return;
    updateAgent.mutate(
      { agentId, payload: { foundation_model: candidate } as any },
      {
        onSuccess: () => {
          setSnack({ open: true, msg: `Agent now uses ${candidate}`, sev: 'success' });
          setConfirmOpen(false);
        },
        onError: (err) => setSnack({ open: true, msg: `Update failed: ${err?.message ?? 'unknown'}`, sev: 'error' }),
      },
    );
  };

  return (
    <Box>
      <Grid container spacing={2}>
        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="subtitle2" sx={{ mb: 1 }}>1. Pick an agent</Typography>
            <FormControl fullWidth size="small" sx={{ mb: 2 }}>
              <InputLabel>Agent</InputLabel>
              <Select value={agentId} label="Agent" onChange={(e) => setAgentId(e.target.value)}>
                {agents.map((a: any) => (
                  <MenuItem key={a.agent_id} value={a.agent_id}>
                    {a.name} <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>({a.foundation_model})</Typography>
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <Typography variant="subtitle2" sx={{ mb: 1 }}>2. Candidate model</Typography>
            <FormControl fullWidth size="small">
              <InputLabel>Candidate model</InputLabel>
              <Select value={candidate} label="Candidate model" onChange={(e) => setCandidate(e.target.value)}>
                {pricingRows.map((p) => (
                  <MenuItem key={p.pricing_id} value={p.model}>
                    {p.model} <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>(${p.input_per_mtok}/{p.output_per_mtok} per Mtok)</Typography>
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </Paper>
        </Grid>
        <Grid item xs={12} md={6}>
          <Paper sx={{ p: 2, minHeight: 240 }}>
            <Typography variant="subtitle2" sx={{ mb: 1 }}>3. Projected impact (last 30 days)</Typography>
            {!agentId || !candidate ? (
              <Alert severity="info">Pick an agent and a candidate model to see projected savings.</Alert>
            ) : whatIfQ.isLoading ? (
              <Skeleton height={160} />
            ) : whatIfQ.isError ? (
              <Alert severity="error">{(whatIfQ.error as Error)?.message}</Alert>
            ) : result ? (
              <>
                <Stack direction="row" spacing={2} sx={{ mb: 2 }}>
                  <Box sx={{ flex: 1 }}>
                    <Typography variant="caption" color="text.secondary">Current ({result.current.model})</Typography>
                    <Typography variant="h6">{fmtMoney(result.current.projected_cost_usd)}</Typography>
                  </Box>
                  <SwapHorizIcon sx={{ alignSelf: 'center' }} />
                  <Box sx={{ flex: 1 }}>
                    <Typography variant="caption" color="text.secondary">Candidate ({result.candidate.model})</Typography>
                    <Typography variant="h6">{fmtMoney(result.candidate.projected_cost_usd)}</Typography>
                  </Box>
                </Stack>
                <Alert severity={result.savings_usd > 0 ? 'success' : 'warning'} sx={{ mb: 2 }}>
                  {result.savings_usd > 0
                    ? `Saves ${fmtMoney(result.savings_usd)} (${fmtPct(result.savings_pct)}) over the last 30 days`
                    : `Costs ${fmtMoney(-result.savings_usd)} more — not a savings`}
                  <br />
                  <Typography variant="caption" color="text.secondary">
                    Based on {fmtInt(result.n_calls_basis)} calls
                    ({fmtInt(result.prompt_tokens_basis)} prompt + {fmtInt(result.completion_tokens_basis)} completion tokens).
                  </Typography>
                </Alert>
                <Button
                  variant="contained"
                  startIcon={<SwapHorizIcon />}
                  disabled={updateAgent.isPending || candidate === selectedAgent?.foundation_model}
                  onClick={() => setConfirmOpen(true)}
                >
                  Apply this swap
                </Button>
              </>
            ) : null}
          </Paper>
        </Grid>
      </Grid>

      <Dialog open={confirmOpen} onClose={() => setConfirmOpen(false)}>
        <DialogTitle>Switch agent to {candidate}?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Agent <strong>{selectedAgent?.name}</strong> will use <code>{candidate}</code> for all
            future LLM calls. The change is immediate and reversible.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={handleApply} disabled={updateAgent.isPending}>
            {updateAgent.isPending ? 'Applying…' : 'Apply'}
          </Button>
        </DialogActions>
      </Dialog>

      <Snackbar
        open={snack.open}
        autoHideDuration={4000}
        onClose={() => setSnack((s) => ({ ...s, open: false }))}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      >
        <Alert severity={snack.sev} variant="filled" onClose={() => setSnack((s) => ({ ...s, open: false }))}>
          {snack.msg}
        </Alert>
      </Snackbar>
    </Box>
  );
}

// ---------------------------------------------------------------------------
// Pricing Admin tab
// ---------------------------------------------------------------------------
function PricingTab() {
  const q = useFinOpsPricing();
  const upsert = useUpsertPricing();
  const [editId, setEditId] = useState<number | null>(null);
  const [form, setForm] = useState<PricingUpsertBody>({ provider: '', model: '', input_per_mtok: 0, output_per_mtok: 0 });
  const [snack, setSnack] = useState<{ open: boolean; msg: string }>({ open: false, msg: '' });

  const rows = q.data?.rows || [];

  const startEdit = (r: PricingRow) => {
    setEditId(r.pricing_id);
    setForm({
      provider: r.provider, model: r.model,
      input_per_mtok: r.input_per_mtok, output_per_mtok: r.output_per_mtok,
      notes: r.notes || undefined,
    });
  };
  const startAdd = () => {
    setEditId(null);
    setForm({ provider: '', model: '', input_per_mtok: 0, output_per_mtok: 0 });
  };
  const submit = () => {
    upsert.mutate(
      { pricing_id: editId || undefined, body: form },
      {
        onSuccess: () => {
          setSnack({ open: true, msg: editId ? 'Pricing updated' : 'Pricing added' });
          startAdd();
        },
        onError: (err) => setSnack({ open: true, msg: `Failed: ${(err as Error)?.message}` }),
      },
    );
  };

  return (
    <Grid container spacing={2}>
      <Grid item xs={12} md={8}>
        <Paper>
          {q.isLoading ? <Skeleton height={300} /> : (
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Provider</TableCell>
                  <TableCell>Model</TableCell>
                  <TableCell align="right">$ / Mtok in</TableCell>
                  <TableCell align="right">$ / Mtok out</TableCell>
                  <TableCell>Effective from</TableCell>
                  <TableCell />
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((r) => (
                  <TableRow key={r.pricing_id} hover>
                    <TableCell>{r.provider}</TableCell>
                    <TableCell sx={{ fontFamily: 'monospace', fontSize: 12 }}>{r.model}</TableCell>
                    <TableCell align="right">${Number(r.input_per_mtok).toFixed(4)}</TableCell>
                    <TableCell align="right">${Number(r.output_per_mtok).toFixed(4)}</TableCell>
                    <TableCell sx={{ fontSize: 11 }}>{fmtTs(r.effective_from)}</TableCell>
                    <TableCell><Button size="small" onClick={() => startEdit(r)}>Edit</Button></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </Paper>
      </Grid>
      <Grid item xs={12} md={4}>
        <Paper sx={{ p: 2 }}>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>{editId ? `Edit pricing #${editId}` : 'Add new pricing'}</Typography>
          <Stack spacing={1}>
            <TextField size="small" label="Provider" value={form.provider} onChange={(e) => setForm({ ...form, provider: e.target.value })} />
            <TextField size="small" label="Model" value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} />
            <TextField size="small" label="Input $ per 1M tokens" type="number" inputProps={{ step: 0.0001 }}
              value={form.input_per_mtok} onChange={(e) => setForm({ ...form, input_per_mtok: Number(e.target.value) })} />
            <TextField size="small" label="Output $ per 1M tokens" type="number" inputProps={{ step: 0.0001 }}
              value={form.output_per_mtok} onChange={(e) => setForm({ ...form, output_per_mtok: Number(e.target.value) })} />
            <TextField size="small" label="Notes (optional)" value={form.notes ?? ''} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
            <Stack direction="row" spacing={1}>
              <Button variant="contained" onClick={submit} disabled={upsert.isPending || !form.provider || !form.model}>
                {upsert.isPending ? 'Saving…' : editId ? 'Save changes' : 'Add pricing'}
              </Button>
              {editId && <Button onClick={startAdd}>Cancel</Button>}
            </Stack>
          </Stack>
        </Paper>
      </Grid>
      <Snackbar
        open={snack.open}
        autoHideDuration={3500}
        onClose={() => setSnack({ open: false, msg: '' })}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      >
        <Alert severity="info" variant="filled" onClose={() => setSnack({ open: false, msg: '' })}>
          {snack.msg}
        </Alert>
      </Snackbar>
    </Grid>
  );
}
