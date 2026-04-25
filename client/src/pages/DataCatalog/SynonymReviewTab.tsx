import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
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
  FormControl,
  Grid,
  IconButton,
  InputLabel,
  MenuItem,
  Paper,
  Radio,
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
import RefreshIcon from '@mui/icons-material/Refresh';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import CheckIcon from '@mui/icons-material/Check';
import CloseIcon from '@mui/icons-material/Close';
import MergeTypeIcon from '@mui/icons-material/MergeType';
import { useOntology } from '@/api/catalog';
import {
  ReviewSynonymProposalResponse,
  SynonymMemberColumn,
  SynonymProposal,
  SynonymProposalKind,
  SynonymProposalStatus,
  useReviewSynonymProposal,
  useSynonymProposals,
  useTriggerConsolidation,
} from '@/api/synonymProposals';
import { useAuthStore } from '@/store/authStore';

const STATUS_OPTIONS: Array<SynonymProposalStatus | ''> = [
  '',
  'PROPOSED',
  'CONFIRMED',
  'REJECTED',
  'APPLIED',
  'SUPERSEDED',
];

const KIND_OPTIONS: Array<SynonymProposalKind | ''> = [
  '',
  'SYNONYM',
  'DUPLICATION',
  'GRAIN',
  'NAMING',
  'OTHER',
];

const KIND_COLOR: Record<
  SynonymProposalKind,
  'default' | 'primary' | 'secondary' | 'info' | 'warning' | 'error' | 'success'
> = {
  SYNONYM: 'primary',
  DUPLICATION: 'warning',
  GRAIN: 'info',
  NAMING: 'secondary',
  OTHER: 'default',
};

const STATUS_COLOR: Record<
  SynonymProposalStatus,
  'default' | 'info' | 'success' | 'warning' | 'error'
> = {
  PROPOSED: 'warning',
  CONFIRMED: 'info',
  REJECTED: 'error',
  APPLIED: 'success',
  SUPERSEDED: 'default',
};

function confidenceColor(c: number | null): 'default' | 'success' | 'warning' | 'error' {
  if (c === null || c === undefined) return 'default';
  if (c >= 0.8) return 'success';
  if (c >= 0.5) return 'warning';
  return 'error';
}

function fmtConfidence(c: number | null): string {
  if (c === null || c === undefined) return '—';
  return c.toFixed(2);
}

export default function SynonymReviewTab() {
  const username = useAuthStore((s) => s.user?.username) ?? 'auditor';
  const [searchParams, setSearchParams] = useSearchParams();
  const focusedCluster = searchParams.get('cluster');

  const [statusFilter, setStatusFilter] = useState<SynonymProposalStatus | ''>('PROPOSED');
  const [kindFilter, setKindFilter] = useState<SynonymProposalKind | ''>('');
  const [domainFilter, setDomainFilter] = useState<string>('');

  const [rejectFor, setRejectFor] = useState<string | null>(null);
  const [snack, setSnack] = useState<{
    open: boolean;
    message: string;
    severity: 'success' | 'error' | 'info';
  }>({ open: false, message: '', severity: 'success' });

  const ontologyQ = useOntology();
  const proposalsQ = useSynonymProposals({
    status: statusFilter,
    kind: kindFilter,
    domain: domainFilter || undefined,
  });
  const review = useReviewSynonymProposal();
  const trigger = useTriggerConsolidation();

  const proposals = proposalsQ.data?.proposals ?? [];

  // If a cluster is being deep-linked from the Auditor Issues page, scroll
  // it into view and pre-clear filters that might hide it.
  useEffect(() => {
    if (!focusedCluster) return;
    setStatusFilter('PROPOSED');
    const el = document.getElementById(`synonym-proposal-${focusedCluster}`);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, [focusedCluster, proposals.length]);

  const showSnack = (
    message: string,
    severity: 'success' | 'error' | 'info' = 'success',
  ) => setSnack({ open: true, message, severity });

  const domains = useMemo<string[]>(() => {
    const d = ontologyQ.data?.domains ?? [];
    return d.map((x) => x.domain).filter(Boolean);
  }, [ontologyQ.data]);

  const handleConsolidate = () => {
    trigger.mutate(
      { domain: domainFilter || undefined },
      {
        onSuccess: (resp) =>
          showSnack(
            `Consolidation triggered — ${resp.proposals_created ?? 0} new proposals`,
            'success',
          ),
        onError: (err) =>
          showSnack(`Failed: ${err?.message ?? 'unknown error'}`, 'error'),
      },
    );
  };

  const handleConfirm = (
    proposal: SynonymProposal,
    chosenAttr: string,
    chosenColumn: string,
    note: string,
    reviewedBy: string,
  ) => {
    review.mutate(
      {
        proposalId: proposal.proposal_id,
        action: 'CONFIRM',
        chosen_canonical_attr: chosenAttr,
        chosen_canonical_column: chosenColumn,
        note: note || undefined,
        reviewed_by: reviewedBy || username,
      },
      {
        onSuccess: (resp: ReviewSynonymProposalResponse) => {
          const n = resp.superseded ?? Math.max(0, proposal.members_json.length - 1);
          showSnack(`Merge applied — supersedes ${n} non-canonical mappings`);
          if (focusedCluster) {
            const next = new URLSearchParams(searchParams);
            next.delete('cluster');
            setSearchParams(next, { replace: true });
          }
        },
        onError: (err) =>
          showSnack(`Failed: ${err?.message ?? 'unknown error'}`, 'error'),
      },
    );
  };

  const handleReject = (proposalId: string, reviewedBy: string) => {
    review.mutate(
      {
        proposalId,
        action: 'REJECT',
        reviewed_by: reviewedBy || username,
      },
      {
        onSuccess: () => {
          showSnack('Proposal rejected', 'info');
          setRejectFor(null);
        },
        onError: (err) =>
          showSnack(`Failed: ${err?.message ?? 'unknown error'}`, 'error'),
      },
    );
  };

  return (
    <Box>
      {/* Filter bar + consolidate button */}
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
          <FormControl size="small" sx={{ minWidth: 160 }}>
            <InputLabel>Kind</InputLabel>
            <Select
              label="Kind"
              value={kindFilter}
              onChange={(e) =>
                setKindFilter((e.target.value as SynonymProposalKind | '') ?? '')
              }
            >
              {KIND_OPTIONS.map((k) => (
                <MenuItem key={k || 'ALL'} value={k}>
                  {k || 'All kinds'}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl size="small" sx={{ minWidth: 200 }}>
            <InputLabel>Domain</InputLabel>
            <Select
              label="Domain"
              value={domainFilter}
              onChange={(e) => setDomainFilter(String(e.target.value))}
            >
              <MenuItem value="">All domains</MenuItem>
              {domains.map((d) => (
                <MenuItem key={d} value={d}>
                  {d}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <Box sx={{ flex: 1 }} />
          <Tooltip title="Refresh proposals">
            <IconButton size="small" onClick={() => proposalsQ.refetch()}>
              <RefreshIcon fontSize="small" />
            </IconButton>
          </Tooltip>
          <Button
            variant="contained"
            startIcon={<PlayArrowIcon />}
            onClick={handleConsolidate}
            disabled={trigger.isPending}
          >
            {trigger.isPending ? 'Running…' : 'Run consolidation now'}
          </Button>
        </Stack>
      </Paper>

      {proposalsQ.isLoading ? (
        <Skeleton height={400} />
      ) : proposals.length === 0 ? (
        <Alert severity="info">
          No synonym proposals in this filter. Run consolidation to scan the
          current ontology for likely duplicates and synonym clusters.
        </Alert>
      ) : (
        <Stack spacing={2}>
          {proposals.map((p) => (
            <ProposalCard
              key={p.proposal_id}
              proposal={p}
              defaultReviewedBy={username}
              busy={review.isPending}
              focused={focusedCluster === p.proposal_id}
              onConfirm={(attr, col, note, by) => handleConfirm(p, attr, col, note, by)}
              onReject={() => setRejectFor(p.proposal_id)}
            />
          ))}
        </Stack>
      )}

      {/* Reject confirm dialog */}
      <Dialog open={!!rejectFor} onClose={() => setRejectFor(null)}>
        <DialogTitle>Reject proposal</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Reject this synonym proposal without merging. The members remain
            independent BusinessAttributes. Confirm?
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRejectFor(null)} disabled={review.isPending}>
            Cancel
          </Button>
          <Button
            color="error"
            variant="contained"
            onClick={() => rejectFor && handleReject(rejectFor, username)}
            disabled={review.isPending}
          >
            {review.isPending ? 'Saving…' : 'Reject'}
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
// Proposal card
// ---------------------------------------------------------------------------
function ProposalCard({
  proposal,
  defaultReviewedBy,
  busy,
  focused,
  onConfirm,
  onReject,
}: {
  proposal: SynonymProposal;
  defaultReviewedBy: string;
  busy: boolean;
  focused: boolean;
  onConfirm: (
    chosenAttr: string,
    chosenColumn: string,
    note: string,
    reviewedBy: string,
  ) => void;
  onReject: () => void;
}) {
  // Default radio selections from the LLM's suggestion. If the suggested
  // attribute is not actually one of the cluster members, fall back to the
  // first member.
  const memberAttrs = proposal.members_json;
  const memberCols = proposal.member_columns_json;
  const defaultAttr =
    proposal.suggested_canonical_attr &&
    memberAttrs.includes(proposal.suggested_canonical_attr)
      ? proposal.suggested_canonical_attr
      : memberAttrs[0] ?? '';
  const defaultCol =
    proposal.suggested_canonical_column &&
    memberCols.some((m) => m.column_fq_name === proposal.suggested_canonical_column)
      ? proposal.suggested_canonical_column
      : memberCols[0]?.column_fq_name ?? '';

  const [chosenAttr, setChosenAttr] = useState<string>(defaultAttr);
  const [chosenColumn, setChosenColumn] = useState<string>(defaultCol);
  const [note, setNote] = useState<string>('');
  const [reviewedBy, setReviewedBy] = useState<string>(defaultReviewedBy);

  const isTerminal =
    proposal.status === 'APPLIED' ||
    proposal.status === 'REJECTED' ||
    proposal.status === 'SUPERSEDED';
  const canConfirm =
    !!chosenAttr && !!chosenColumn && proposal.status === 'PROPOSED' && !busy;

  return (
    <Paper
      id={`synonym-proposal-${proposal.proposal_id}`}
      sx={{
        p: 2,
        borderLeft: focused ? '3px solid' : undefined,
        borderColor: focused ? 'primary.main' : undefined,
      }}
    >
      {/* Header */}
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.5 }} flexWrap="wrap" useFlexGap>
        <MergeTypeIcon fontSize="small" color="primary" />
        <Chip
          label={proposal.kind}
          size="small"
          color={KIND_COLOR[proposal.kind]}
          sx={{ height: 20 }}
        />
        {proposal.domain && (
          <Chip
            label={proposal.domain}
            size="small"
            variant="outlined"
            sx={{ height: 20 }}
          />
        )}
        <Chip
          label={`conf ${fmtConfidence(proposal.confidence)}`}
          size="small"
          color={confidenceColor(proposal.confidence)}
          sx={{ height: 20 }}
        />
        <Chip
          label={proposal.status}
          size="small"
          color={STATUS_COLOR[proposal.status]}
          sx={{ height: 20 }}
        />
        <Box sx={{ flex: 1 }} />
        <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace' }}>
          {proposal.proposal_id.slice(0, 8)}
        </Typography>
      </Stack>

      <Grid container spacing={2}>
        {/* Left pane — cluster members */}
        <Grid item xs={12} md={8}>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>
            Cluster members ({memberAttrs.length})
          </Typography>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell padding="checkbox" align="center">
                  <Tooltip title="Canonical attribute">
                    <span>Attr</span>
                  </Tooltip>
                </TableCell>
                <TableCell>Business attribute</TableCell>
                <TableCell padding="checkbox" align="center">
                  <Tooltip title="Canonical physical column">
                    <span>Col</span>
                  </Tooltip>
                </TableCell>
                <TableCell>Physical column</TableCell>
                <TableCell>Source</TableCell>
                <TableCell>Samples</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {memberAttrs.map((attr) => {
                const memberCol = memberCols.find((c) => c.ba_fq_name === attr);
                return (
                  <MemberRow
                    key={attr}
                    attr={attr}
                    memberCol={memberCol ?? null}
                    chosenAttr={chosenAttr}
                    chosenColumn={chosenColumn}
                    setChosenAttr={setChosenAttr}
                    setChosenColumn={setChosenColumn}
                    disabled={isTerminal}
                  />
                );
              })}
            </TableBody>
          </Table>
        </Grid>

        {/* Right pane — rationale */}
        <Grid item xs={12} md={4}>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>
            Rationale
          </Typography>
          <Paper variant="outlined" sx={{ p: 1.25, mb: 1 }}>
            <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
              {proposal.rationale || '(no rationale provided)'}
            </Typography>
          </Paper>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
            LLM suggestion
          </Typography>
          <Box sx={{ mb: 1 }}>
            <Typography variant="caption" color="text.secondary">
              attribute:
            </Typography>{' '}
            <Typography variant="caption" sx={{ fontFamily: 'monospace' }}>
              {proposal.suggested_canonical_attr ?? '—'}
            </Typography>
          </Box>
          <Box>
            <Typography variant="caption" color="text.secondary">
              column:
            </Typography>{' '}
            <Typography variant="caption" sx={{ fontFamily: 'monospace' }}>
              {proposal.suggested_canonical_column ?? '—'}
            </Typography>
          </Box>
          {proposal.reviewed_by && (
            <Typography
              variant="caption"
              color="text.secondary"
              sx={{ display: 'block', mt: 1 }}
            >
              Reviewed by {proposal.reviewed_by}
            </Typography>
          )}
        </Grid>
      </Grid>

      {/* Footer */}
      {!isTerminal && proposal.status === 'PROPOSED' && (
        <>
          <Stack direction="row" spacing={1} sx={{ mt: 2 }} alignItems="center" flexWrap="wrap" useFlexGap>
            <TextField
              size="small"
              label="Reviewed by"
              value={reviewedBy}
              onChange={(e) => setReviewedBy(e.target.value)}
              sx={{ width: 200 }}
            />
            <TextField
              size="small"
              label="Note (optional)"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              sx={{ flex: 1, minWidth: 240 }}
            />
            <Box sx={{ flex: 1 }} />
            <Button
              variant="outlined"
              color="error"
              startIcon={<CloseIcon />}
              onClick={onReject}
              disabled={busy}
            >
              Reject
            </Button>
            <Button
              variant="contained"
              color="success"
              startIcon={<CheckIcon />}
              onClick={() => onConfirm(chosenAttr, chosenColumn, note, reviewedBy)}
              disabled={!canConfirm}
            >
              Confirm Merge
            </Button>
          </Stack>
        </>
      )}
    </Paper>
  );
}

function MemberRow({
  attr,
  memberCol,
  chosenAttr,
  chosenColumn,
  setChosenAttr,
  setChosenColumn,
  disabled,
}: {
  attr: string;
  memberCol: SynonymMemberColumn | null;
  chosenAttr: string;
  chosenColumn: string;
  setChosenAttr: (v: string) => void;
  setChosenColumn: (v: string) => void;
  disabled: boolean;
}) {
  const samples = memberCol?.sample_values ?? [];
  return (
    <TableRow>
      <TableCell padding="checkbox" align="center">
        <Radio
          size="small"
          checked={chosenAttr === attr}
          onChange={() => setChosenAttr(attr)}
          disabled={disabled}
        />
      </TableCell>
      <TableCell sx={{ maxWidth: 220 }}>
        <Typography
          variant="body2"
          sx={{ fontFamily: 'monospace', fontSize: 12, wordBreak: 'break-all' }}
        >
          {attr}
        </Typography>
      </TableCell>
      <TableCell padding="checkbox" align="center">
        <Radio
          size="small"
          checked={!!memberCol && chosenColumn === memberCol.column_fq_name}
          onChange={() => memberCol && setChosenColumn(memberCol.column_fq_name)}
          disabled={disabled || !memberCol}
        />
      </TableCell>
      <TableCell sx={{ maxWidth: 220 }}>
        {memberCol ? (
          <Typography
            variant="caption"
            sx={{ fontFamily: 'monospace', fontSize: 11, wordBreak: 'break-all' }}
          >
            {memberCol.column_fq_name}
          </Typography>
        ) : (
          <Typography variant="caption" color="text.secondary">
            —
          </Typography>
        )}
      </TableCell>
      <TableCell>
        {memberCol?.source_uri ? (
          <Tooltip title={memberCol.source_uri} placement="top">
            <Typography
              variant="caption"
              sx={{
                fontFamily: 'monospace',
                fontSize: 11,
                maxWidth: 140,
                display: 'inline-block',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {memberCol.source_uri}
            </Typography>
          </Tooltip>
        ) : (
          <Typography variant="caption" color="text.secondary">
            —
          </Typography>
        )}
      </TableCell>
      <TableCell>
        <Stack direction="row" spacing={0.25} flexWrap="wrap" useFlexGap>
          {samples.slice(0, 3).map((s, i) => (
            <Chip
              key={`${attr}-sample-${i}`}
              label={String(s)}
              size="small"
              variant="outlined"
              sx={{ height: 16, fontSize: 10 }}
            />
          ))}
          {samples.length > 3 && (
            <Typography variant="caption" color="text.secondary">
              +{samples.length - 3}
            </Typography>
          )}
        </Stack>
      </TableCell>
    </TableRow>
  );
}
