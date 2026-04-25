import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Divider,
  Drawer,
  FormControl,
  Grid,
  IconButton,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Skeleton,
  Snackbar,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import ReportProblemIcon from '@mui/icons-material/ReportProblem';
import RefreshIcon from '@mui/icons-material/Refresh';
import CloseIcon from '@mui/icons-material/Close';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import LaunchIcon from '@mui/icons-material/Launch';
import {
  AuditorIssue,
  AuditorIssueKind,
  AuditorIssueSeverity,
  AuditorIssueStatus,
  useAuditorIssue,
  useAuditorIssues,
  useAuditorIssuesSummary,
  useResolveAuditorIssue,
} from '@/api/auditorIssues';
import { useAuthStore } from '@/store/authStore';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
const STATUS_OPTIONS: Array<AuditorIssueStatus | ''> = [
  '',
  'OPEN',
  'IN_REVIEW',
  'RESOLVED',
  'REJECTED',
  'SUPERSEDED',
];

const KIND_OPTIONS: Array<AuditorIssueKind | ''> = [
  '',
  'SYNONYM_AMBIGUITY',
  'COLUMN_AMBIGUITY',
  'NO_RESOLUTION',
  'ORPHAN_ENTITY',
  'MAPPING_LOW_CONFIDENCE',
  'OTHER',
];

const SEVERITY_OPTIONS: Array<AuditorIssueSeverity | ''> = [
  '',
  'LOW',
  'MEDIUM',
  'HIGH',
  'CRITICAL',
];

const SEVERITY_COLOR: Record<
  AuditorIssueSeverity,
  'default' | 'info' | 'warning' | 'error'
> = {
  LOW: 'default',
  MEDIUM: 'info',
  HIGH: 'warning',
  CRITICAL: 'error',
};

const STATUS_COLOR: Record<
  AuditorIssueStatus,
  'default' | 'info' | 'success' | 'warning' | 'error'
> = {
  OPEN: 'warning',
  IN_REVIEW: 'info',
  RESOLVED: 'success',
  REJECTED: 'error',
  SUPERSEDED: 'default',
};

const KIND_COLOR: Record<
  AuditorIssueKind,
  'default' | 'info' | 'warning' | 'error' | 'primary' | 'secondary'
> = {
  SYNONYM_AMBIGUITY: 'primary',
  COLUMN_AMBIGUITY: 'secondary',
  NO_RESOLUTION: 'error',
  ORPHAN_ENTITY: 'warning',
  MAPPING_LOW_CONFIDENCE: 'info',
  OTHER: 'default',
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function fmtRelative(ts: string | null): string {
  if (!ts) return '—';
  try {
    const then = new Date(ts).getTime();
    const now = Date.now();
    const sec = Math.max(0, Math.floor((now - then) / 1000));
    if (sec < 60) return `${sec}s ago`;
    const min = Math.floor(sec / 60);
    if (min < 60) return `${min}m ago`;
    const hr = Math.floor(min / 60);
    if (hr < 24) return `${hr}h ago`;
    const days = Math.floor(hr / 24);
    if (days < 7) return `${days}d ago`;
    return new Date(ts).toLocaleDateString();
  } catch {
    return String(ts);
  }
}

function fmtTs(ts: string | null): string {
  if (!ts) return '—';
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return String(ts);
  }
}

function truncate(s: string | null, n = 60): string {
  if (!s) return '';
  return s.length > n ? `${s.slice(0, n)}…` : s;
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export default function AuditorIssuesPage() {
  const navigate = useNavigate();
  const username = useAuthStore((s) => s.user?.username) ?? 'auditor';

  const [statusFilter, setStatusFilter] = useState<AuditorIssueStatus | ''>('OPEN');
  const [kindFilter, setKindFilter] = useState<AuditorIssueKind | ''>('');
  const [severityFilter, setSeverityFilter] = useState<AuditorIssueSeverity | ''>('');
  const [search, setSearch] = useState('');

  const [selectedIssueId, setSelectedIssueId] = useState<string | null>(null);
  const [resolveOpen, setResolveOpen] = useState(false);
  const [resolveText, setResolveText] = useState('');
  const [resolveBy, setResolveBy] = useState('');
  const [rejectConfirmOpen, setRejectConfirmOpen] = useState(false);
  const [snack, setSnack] = useState<{
    open: boolean;
    message: string;
    severity: 'success' | 'error' | 'info';
  }>({ open: false, message: '', severity: 'success' });

  const summaryQ = useAuditorIssuesSummary();
  const listQ = useAuditorIssues({
    status: statusFilter,
    kind: kindFilter,
    severity: severityFilter,
    limit: 200,
  });
  const detailQ = useAuditorIssue(selectedIssueId);
  const resolve = useResolveAuditorIssue();

  const issues = listQ.data?.issues ?? [];
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return issues;
    return issues.filter((i) => i.title.toLowerCase().includes(q));
  }, [issues, search]);

  const summary = summaryQ.data;
  const summaryByKind = useMemo(() => {
    const out: Partial<Record<AuditorIssueKind, number>> = {};
    if (!summary) return out;
    for (const b of summary.buckets) {
      if (b.status !== 'OPEN' && b.status !== 'IN_REVIEW') continue;
      out[b.kind] = (out[b.kind] ?? 0) + b.n;
    }
    return out;
  }, [summary]);

  const showSnack = (
    message: string,
    severity: 'success' | 'error' | 'info' = 'success',
  ) => setSnack({ open: true, message, severity });

  const closeDrawer = () => {
    setSelectedIssueId(null);
    setResolveOpen(false);
    setRejectConfirmOpen(false);
    setResolveText('');
    setResolveBy('');
  };

  const handleMarkInReview = (issue: AuditorIssue) => {
    resolve.mutate(
      {
        issueId: issue.issue_id,
        status: 'IN_REVIEW',
        assigned_to: username,
      },
      {
        onSuccess: () => showSnack('Issue marked in review'),
        onError: (err) =>
          showSnack(`Failed: ${err?.message ?? 'unknown error'}`, 'error'),
      },
    );
  };

  const handleResolveSubmit = () => {
    if (!selectedIssueId) return;
    resolve.mutate(
      {
        issueId: selectedIssueId,
        status: 'RESOLVED',
        resolution: resolveText.trim() || undefined,
        resolved_by: resolveBy.trim() || username,
      },
      {
        onSuccess: () => {
          showSnack('Issue resolved');
          closeDrawer();
        },
        onError: (err) =>
          showSnack(`Failed: ${err?.message ?? 'unknown error'}`, 'error'),
      },
    );
  };

  const handleRejectConfirm = () => {
    if (!selectedIssueId) return;
    resolve.mutate(
      {
        issueId: selectedIssueId,
        status: 'REJECTED',
        resolved_by: username,
      },
      {
        onSuccess: () => {
          showSnack('Issue rejected', 'info');
          closeDrawer();
        },
        onError: (err) =>
          showSnack(`Failed: ${err?.message ?? 'unknown error'}`, 'error'),
      },
    );
  };

  const handleOpenSynonymReview = (issue: AuditorIssue) => {
    if (!issue.resource_id) return;
    navigate(
      `/data-catalog?tab=synonym-review&cluster=${encodeURIComponent(issue.resource_id)}`,
    );
  };

  return (
    <Box>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
        <ReportProblemIcon color="warning" />
        <Typography variant="h5" fontWeight={600}>
          Auditor Issues
        </Typography>
        <Chip label="Govern" size="small" variant="outlined" />
      </Stack>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Runtime resolution gaps surfaced for Data Steward review. Each issue is
        produced by the orchestrator when an attribute, column, or synonym
        cannot be resolved unambiguously.
      </Typography>

      {/* --------------------- Top metric row --------------------- */}
      <Grid container spacing={2} sx={{ mb: 2 }}>
        <SummaryCard
          label="Open total"
          value={summary?.open_total}
          loading={summaryQ.isLoading}
          highlight={(summary?.open_total ?? 0) > 0}
        />
        <SummaryCard
          label="Synonym ambiguity"
          value={summaryByKind.SYNONYM_AMBIGUITY ?? 0}
          loading={summaryQ.isLoading}
        />
        <SummaryCard
          label="No resolution"
          value={summaryByKind.NO_RESOLUTION ?? 0}
          loading={summaryQ.isLoading}
        />
        <SummaryCard
          label="Orphan entities"
          value={summaryByKind.ORPHAN_ENTITY ?? 0}
          loading={summaryQ.isLoading}
        />
      </Grid>

      {/* --------------------- Filter bar --------------------- */}
      <Paper sx={{ p: 2, mb: 2 }}>
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
          <Typography variant="subtitle2">Status:</Typography>
          {STATUS_OPTIONS.map((s) => (
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
          <Box sx={{ width: 16 }} />
          <FormControl size="small" sx={{ minWidth: 200 }}>
            <InputLabel>Kind</InputLabel>
            <Select
              label="Kind"
              value={kindFilter}
              onChange={(e) =>
                setKindFilter((e.target.value as AuditorIssueKind | '') ?? '')
              }
            >
              {KIND_OPTIONS.map((k) => (
                <MenuItem key={k || 'ALL'} value={k}>
                  {k || 'All kinds'}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <Stack direction="row" spacing={0.5} alignItems="center">
            <Typography variant="caption" color="text.secondary">
              Severity:
            </Typography>
            {SEVERITY_OPTIONS.map((sev) => (
              <Chip
                key={sev || 'ALL'}
                label={sev || 'ALL'}
                size="small"
                onClick={() => setSeverityFilter(sev)}
                color={severityFilter === sev ? 'primary' : 'default'}
                variant={severityFilter === sev ? 'filled' : 'outlined'}
                sx={{ cursor: 'pointer', height: 22 }}
              />
            ))}
          </Stack>
          <Box sx={{ flex: 1 }} />
          <TextField
            size="small"
            placeholder="Search title…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            sx={{ minWidth: 220 }}
          />
          <IconButton size="small" onClick={() => listQ.refetch()}>
            <RefreshIcon fontSize="small" />
          </IconButton>
        </Stack>
      </Paper>

      {/* --------------------- Main list --------------------- */}
      {listQ.isLoading ? (
        <Skeleton height={400} />
      ) : filtered.length === 0 ? (
        <Alert severity="info">
          No issues match the current filter. Either everything is healthy or
          you need to widen the filter (e.g. flip Status to ALL).
        </Alert>
      ) : (
        <Paper>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Severity</TableCell>
                <TableCell>Kind</TableCell>
                <TableCell>Title</TableCell>
                <TableCell>Resource</TableCell>
                <TableCell>Raised</TableCell>
                <TableCell>Trace</TableCell>
                <TableCell>Status</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {filtered.map((issue) => (
                <IssueRow
                  key={issue.issue_id}
                  issue={issue}
                  onSelect={() => setSelectedIssueId(issue.issue_id)}
                  onMarkInReview={() => handleMarkInReview(issue)}
                  onOpenSynonymReview={() => handleOpenSynonymReview(issue)}
                  onOpenTrace={(traceId) =>
                    navigate(`/model-governance?trace=${encodeURIComponent(traceId)}`)
                  }
                  disabled={resolve.isPending}
                />
              ))}
            </TableBody>
          </Table>
        </Paper>
      )}

      {/* --------------------- Drawer --------------------- */}
      <Drawer
        anchor="right"
        open={!!selectedIssueId}
        onClose={closeDrawer}
        PaperProps={{ sx: { width: 520 } }}
      >
        <Box sx={{ p: 2, height: '100%', display: 'flex', flexDirection: 'column' }}>
          <Stack direction="row" alignItems="center" sx={{ mb: 1 }}>
            <Typography variant="subtitle1" fontWeight={600} sx={{ flex: 1 }}>
              Issue detail
            </Typography>
            <IconButton size="small" onClick={closeDrawer}>
              <CloseIcon fontSize="small" />
            </IconButton>
          </Stack>
          <Divider sx={{ mb: 1 }} />
          {detailQ.isLoading ? (
            <Skeleton height={300} />
          ) : !detailQ.data ? (
            <Alert severity="warning">Issue not found.</Alert>
          ) : (
            <IssueDetailBody
              issue={detailQ.data}
              onMarkInReview={() => handleMarkInReview(detailQ.data!)}
              onOpenResolve={() => {
                setResolveText('');
                setResolveBy(username);
                setResolveOpen(true);
              }}
              onOpenReject={() => setRejectConfirmOpen(true)}
              onOpenSynonymReview={() => handleOpenSynonymReview(detailQ.data!)}
              busy={resolve.isPending}
            />
          )}
        </Box>
      </Drawer>

      {/* Resolve dialog */}
      <Dialog open={resolveOpen} onClose={() => setResolveOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Resolve issue</DialogTitle>
        <DialogContent>
          <DialogContentText sx={{ mb: 2 }}>
            Mark this issue as resolved. Provide a brief note describing the
            resolution so future auditors can see what changed.
          </DialogContentText>
          <TextField
            fullWidth
            size="small"
            label="Resolution"
            margin="dense"
            multiline
            rows={3}
            value={resolveText}
            onChange={(e) => setResolveText(e.target.value)}
          />
          <TextField
            fullWidth
            size="small"
            label="Reviewed by"
            margin="dense"
            value={resolveBy}
            onChange={(e) => setResolveBy(e.target.value)}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setResolveOpen(false)} disabled={resolve.isPending}>
            Cancel
          </Button>
          <Button
            variant="contained"
            color="success"
            onClick={handleResolveSubmit}
            disabled={resolve.isPending}
          >
            {resolve.isPending ? 'Saving…' : 'Mark resolved'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Reject confirm */}
      <Dialog open={rejectConfirmOpen} onClose={() => setRejectConfirmOpen(false)}>
        <DialogTitle>Reject issue</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Reject this issue without taking corrective action. This is the
            right call when the surfaced gap is a false positive or has been
            superseded by another change. Confirm?
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRejectConfirmOpen(false)} disabled={resolve.isPending}>
            Cancel
          </Button>
          <Button
            variant="contained"
            color="error"
            onClick={() => {
              handleRejectConfirm();
              setRejectConfirmOpen(false);
            }}
            disabled={resolve.isPending}
          >
            {resolve.isPending ? 'Saving…' : 'Reject'}
          </Button>
        </DialogActions>
      </Dialog>

      <Snackbar
        open={snack.open}
        autoHideDuration={4500}
        onClose={() => setSnack((s) => ({ ...s, open: false }))}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      >
        <Alert
          severity={snack.severity}
          variant="filled"
          onClose={() => setSnack((s) => ({ ...s, open: false }))}
        >
          {snack.message}
        </Alert>
      </Snackbar>
    </Box>
  );
}

// ---------------------------------------------------------------------------
// IssueRow
// ---------------------------------------------------------------------------
function IssueRow({
  issue,
  onSelect,
  onMarkInReview,
  onOpenSynonymReview,
  onOpenTrace,
  disabled,
}: {
  issue: AuditorIssue;
  onSelect: () => void;
  onMarkInReview: () => void;
  onOpenSynonymReview: () => void;
  onOpenTrace: (traceId: string) => void;
  disabled: boolean;
}) {
  const resourceLabel =
    issue.resource_type && issue.resource_id
      ? `${issue.resource_type}:${issue.resource_id}`
      : issue.resource_type || issue.resource_id || '—';

  return (
    <TableRow hover onClick={onSelect} sx={{ cursor: 'pointer' }}>
      <TableCell>
        <Chip
          label={issue.severity}
          size="small"
          color={SEVERITY_COLOR[issue.severity]}
          sx={{ height: 18, fontSize: 10 }}
        />
      </TableCell>
      <TableCell>
        <Chip
          label={issue.kind}
          size="small"
          color={KIND_COLOR[issue.kind]}
          variant="outlined"
          sx={{ height: 18, fontSize: 10 }}
        />
      </TableCell>
      <TableCell sx={{ maxWidth: 320 }}>
        <Typography variant="body2" fontWeight={500} noWrap>
          {issue.title}
        </Typography>
        {issue.description && (
          <Typography variant="caption" color="text.secondary" noWrap sx={{ display: 'block' }}>
            {truncate(issue.description, 90)}
          </Typography>
        )}
      </TableCell>
      <TableCell sx={{ maxWidth: 220 }}>
        <Tooltip title={resourceLabel} placement="top">
          <Typography
            variant="caption"
            sx={{
              fontFamily: 'monospace',
              display: 'block',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {resourceLabel}
          </Typography>
        </Tooltip>
      </TableCell>
      <TableCell>
        <Tooltip title={fmtTs(issue.raised_at)} placement="top">
          <Typography variant="caption">{fmtRelative(issue.raised_at)}</Typography>
        </Tooltip>
      </TableCell>
      <TableCell>
        {issue.raised_trace ? (
          <Tooltip title="Open in Model Governance">
            <IconButton
              size="small"
              onClick={(e) => {
                e.stopPropagation();
                onOpenTrace(issue.raised_trace!);
              }}
            >
              <LaunchIcon fontSize="inherit" />
            </IconButton>
          </Tooltip>
        ) : (
          <Typography variant="caption" color="text.secondary">
            —
          </Typography>
        )}
      </TableCell>
      <TableCell>
        <Chip
          label={issue.status}
          size="small"
          color={STATUS_COLOR[issue.status]}
          sx={{ height: 18, fontSize: 10 }}
        />
      </TableCell>
      <TableCell align="right">
        <Stack
          direction="row"
          spacing={0.5}
          justifyContent="flex-end"
          onClick={(e) => e.stopPropagation()}
        >
          {issue.status === 'OPEN' && (
            <Button
              size="small"
              variant="outlined"
              onClick={onMarkInReview}
              disabled={disabled}
            >
              In review
            </Button>
          )}
          {issue.kind === 'SYNONYM_AMBIGUITY' && issue.resource_id && (
            <Button
              size="small"
              variant="contained"
              startIcon={<OpenInNewIcon />}
              onClick={onOpenSynonymReview}
            >
              Synonym
            </Button>
          )}
        </Stack>
      </TableCell>
    </TableRow>
  );
}

// ---------------------------------------------------------------------------
// IssueDetailBody (drawer content)
// ---------------------------------------------------------------------------
function IssueDetailBody({
  issue,
  onMarkInReview,
  onOpenResolve,
  onOpenReject,
  onOpenSynonymReview,
  busy,
}: {
  issue: AuditorIssue;
  onMarkInReview: () => void;
  onOpenResolve: () => void;
  onOpenReject: () => void;
  onOpenSynonymReview: () => void;
  busy: boolean;
}) {
  const isFinal =
    issue.status === 'RESOLVED' ||
    issue.status === 'REJECTED' ||
    issue.status === 'SUPERSEDED';
  const payloadJson = issue.payload ? JSON.stringify(issue.payload, null, 2) : '(empty)';

  return (
    <Box sx={{ flex: 1, overflowY: 'auto' }}>
      <Stack direction="row" spacing={1} sx={{ mb: 1 }} flexWrap="wrap" useFlexGap>
        <Chip
          label={issue.severity}
          size="small"
          color={SEVERITY_COLOR[issue.severity]}
        />
        <Chip
          label={issue.kind}
          size="small"
          color={KIND_COLOR[issue.kind]}
          variant="outlined"
        />
        <Chip
          label={issue.status}
          size="small"
          color={STATUS_COLOR[issue.status]}
        />
      </Stack>
      <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 0.5 }}>
        {issue.title}
      </Typography>
      {issue.description && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2, whiteSpace: 'pre-wrap' }}>
          {issue.description}
        </Typography>
      )}

      <Grid container spacing={1} sx={{ mb: 2 }}>
        <DetailField label="Resource type" value={issue.resource_type ?? '—'} />
        <DetailField
          label="Resource id"
          value={issue.resource_id ?? '—'}
          monospace
        />
        <DetailField label="Raised by" value={issue.raised_by ?? '—'} />
        <DetailField
          label="Raised trace"
          value={issue.raised_trace ?? '—'}
          monospace
        />
        <DetailField label="Assigned to" value={issue.assigned_to ?? '—'} />
        <DetailField label="Resolved by" value={issue.resolved_by ?? '—'} />
        <DetailField label="Raised at" value={fmtTs(issue.raised_at)} />
        <DetailField label="Updated at" value={fmtTs(issue.updated_at)} />
        {issue.resolved_at && (
          <DetailField label="Resolved at" value={fmtTs(issue.resolved_at)} />
        )}
        {issue.resolution && (
          <Grid item xs={12}>
            <Typography variant="caption" color="text.secondary">
              Resolution
            </Typography>
            <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
              {issue.resolution}
            </Typography>
          </Grid>
        )}
      </Grid>

      <Divider sx={{ my: 1 }} />
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
        Payload
      </Typography>
      <Box
        component="pre"
        sx={{
          m: 0,
          p: 1.25,
          fontSize: 11,
          fontFamily: 'monospace',
          bgcolor: (t) =>
            t.palette.mode === 'dark' ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)',
          borderRadius: 1,
          overflowX: 'auto',
          whiteSpace: 'pre',
          maxHeight: 280,
        }}
      >
        {payloadJson}
      </Box>

      <Divider sx={{ my: 2 }} />
      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
        {issue.kind === 'SYNONYM_AMBIGUITY' && issue.resource_id && (
          <Button
            variant="contained"
            color="primary"
            startIcon={<OpenInNewIcon />}
            onClick={onOpenSynonymReview}
          >
            Open in Synonym Review
          </Button>
        )}
        {!isFinal && issue.status === 'OPEN' && (
          <Button variant="outlined" onClick={onMarkInReview} disabled={busy}>
            Mark in review
          </Button>
        )}
        {!isFinal && (
          <>
            <Button
              variant="contained"
              color="success"
              onClick={onOpenResolve}
              disabled={busy}
            >
              Resolve
            </Button>
            <Button
              variant="outlined"
              color="error"
              onClick={onOpenReject}
              disabled={busy}
            >
              Reject
            </Button>
          </>
        )}
      </Stack>
    </Box>
  );
}

function DetailField({
  label,
  value,
  monospace,
}: {
  label: string;
  value: string;
  monospace?: boolean;
}) {
  return (
    <Grid item xs={6}>
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
        {label}
      </Typography>
      <Typography
        variant="body2"
        sx={{
          fontFamily: monospace ? 'monospace' : undefined,
          fontSize: monospace ? 12 : undefined,
          wordBreak: 'break-all',
        }}
      >
        {value}
      </Typography>
    </Grid>
  );
}

// ---------------------------------------------------------------------------
// SummaryCard
// ---------------------------------------------------------------------------
function SummaryCard({
  label,
  value,
  loading,
  highlight,
}: {
  label: string;
  value: number | undefined;
  loading?: boolean;
  highlight?: boolean;
}) {
  return (
    <Grid item xs={6} sm={3}>
      <Paper
        variant="outlined"
        sx={{
          p: 1.25,
          textAlign: 'center',
          borderColor: highlight ? 'warning.main' : undefined,
        }}
      >
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
          {label}
        </Typography>
        {loading ? (
          <Skeleton height={28} />
        ) : (
          <Typography variant="h6" fontWeight={600}>
            {value ?? '—'}
          </Typography>
        )}
      </Paper>
    </Grid>
  );
}
