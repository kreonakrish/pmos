import React, { useCallback, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Divider,
  Grid,
  IconButton,
  MenuItem,
  Paper,
  Select,
  Snackbar,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import TranslateIcon from '@mui/icons-material/Translate';
import SendIcon from '@mui/icons-material/Send';
import HistoryIcon from '@mui/icons-material/History';
import ThumbUpAltIcon from '@mui/icons-material/ThumbUpAlt';
import ThumbDownAltIcon from '@mui/icons-material/ThumbDownAlt';
import StorageIcon from '@mui/icons-material/Storage';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import HubIcon from '@mui/icons-material/Hub';
import {
  useTranslate,
  usePromoteExample,
  TranslationResult,
  TranslationTurn,
  PromoteExampleRequest,
  MatchedReport,
} from '@/api/translator';
import TranslationSubgraphCanvas from '@/components/Graph/TranslationSubgraphCanvas';
import { useAuthStore } from '@/store/authStore';
import { Link as RouterLink } from 'react-router-dom';
import RestartAltIcon from '@mui/icons-material/RestartAlt';
import ReportProblemIcon from '@mui/icons-material/ReportProblem';

interface HistoryEntry {
  question: string;
  ts: number;
}

interface FeedbackState {
  /** Sub-task indices that have been promoted (thumbs up confirmed). */
  promoted: Set<number>;
  /** Sub-task indices that the user dismissed (thumbs down). */
  dismissed: Set<number>;
}

const EMPTY_FEEDBACK: FeedbackState = {
  promoted: new Set(),
  dismissed: new Set(),
};

const TranslatorPage: React.FC = () => {
  // -------------------------------------------------------------------------
  // State
  // -------------------------------------------------------------------------
  const [question, setQuestion] = useState('');
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [result, setResult] = useState<TranslationResult | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<FeedbackState>(EMPTY_FEEDBACK);
  const [confirmIdx, setConfirmIdx] = useState<number | null>(null);
  const [snack, setSnack] = useState<{
    open: boolean;
    message: string;
    severity: 'success' | 'error' | 'info';
  }>({ open: false, message: '', severity: 'success' });
  // Phase F7 — multi-turn clarification dialog state.
  const [dialogTurns, setDialogTurns] = useState<TranslationTurn[]>([]);

  const translate = useTranslate();
  const promote = usePromoteExample();
  const username = useAuthStore((s) => s.user?.username) ?? 'unknown';

  // -------------------------------------------------------------------------
  // Handlers
  // -------------------------------------------------------------------------
  const submit = useCallback(() => {
    const trimmed = question.trim();
    if (!trimmed) return;
    setErrorMsg(null);
    setFeedback({ promoted: new Set(), dismissed: new Set() });
    // Snapshot the dialogTurns we're sending — needed in onSuccess to know
    // whether to append a new round-trip when the response is another
    // clarification.
    const sentTurns: TranslationTurn[] = dialogTurns;
    translate.mutate(
      { question: trimmed, prior_turns: sentTurns },
      {
        onSuccess: (data) => {
          setResult(data);
          setHistory((prev) => {
            const next: HistoryEntry[] = [
              { question: trimmed, ts: Date.now() },
              ...prev.filter((h) => h.question !== trimmed),
            ];
            return next.slice(0, 10);
          });
          if (data.clarification_needed && data.clarification_question) {
            // Append the user's question + translator's clarifier so the
            // next submission carries the full dialog history.
            setDialogTurns([
              ...sentTurns,
              { role: 'user', content: trimmed },
              {
                role: 'translator',
                content: data.clarification_question,
              },
            ]);
            setQuestion('');
          }
          // If the dialog has resolved (clarification_needed=false) we
          // leave dialogTurns alone so the user can still see the
          // transcript above the input. The "Reset dialog" button clears
          // it explicitly.
        },
        onError: (err: unknown) => {
          const e = err as {
            response?: { data?: { detail?: unknown }; status?: number };
            message?: string;
          };
          const detail = e?.response?.data?.detail;
          const msg =
            (typeof detail === 'string' && detail) ||
            (detail && typeof detail === 'object' && 'error' in detail
              ? String((detail as { error?: unknown }).error)
              : null) ||
            e?.message ||
            'Translate request failed.';
          setErrorMsg(String(msg));
        },
      },
    );
  }, [question, translate, dialogTurns]);

  const resetDialog = useCallback(() => {
    setDialogTurns([]);
    setResult(null);
    setQuestion('');
    setErrorMsg(null);
    setFeedback({ promoted: new Set(), dismissed: new Set() });
  }, []);

  const handleHistoryPick = useCallback((q: string) => {
    setQuestion(q);
  }, []);

  const handleThumbsDown = useCallback((idx: number) => {
    setFeedback((prev) => {
      const dismissed = new Set(prev.dismissed);
      dismissed.add(idx);
      return { ...prev, dismissed };
    });
    // Local-only — the spec says no backend call yet.
    // eslint-disable-next-line no-console
    console.info('[translator] thumbs-down logged', { idx });
  }, []);

  const handleThumbsUp = useCallback((idx: number) => {
    setConfirmIdx(idx);
  }, []);

  const cancelPromote = useCallback(() => setConfirmIdx(null), []);

  const confirmPromote = useCallback(() => {
    if (confirmIdx === null || !result) {
      setConfirmIdx(null);
      return;
    }
    const idx = confirmIdx;
    const lastQuestion = history[0]?.question ?? '';
    const payload: PromoteExampleRequest = {
      question: lastQuestion,
      canonical_entities: result.canonical_entities,
      relationships: result.relationships,
      dataset_bindings: result.dataset_bindings,
      decomposition: result.domain_subtasks,
      intent: result.intent,
      domain: result.domain,
      score: 1.0,
      promoted_by: username,
      trace_id: result.trace_id,
    };
    promote.mutate(payload, {
      onSuccess: (data) => {
        if (data.status === 'ok') {
          setFeedback((prev) => {
            const promoted = new Set(prev.promoted);
            promoted.add(idx);
            return { ...prev, promoted };
          });
          setSnack({
            open: true,
            severity: 'success',
            message:
              'Promoted — future similar questions will use this as a few-shot example.',
          });
        } else if (data.status === 'skipped_no_embedder') {
          setSnack({
            open: true,
            severity: 'info',
            message:
              'Promotion skipped: no embedder configured on the Translator service.',
          });
        } else {
          setSnack({
            open: true,
            severity: 'error',
            message: data.message || 'Promotion failed.',
          });
        }
        setConfirmIdx(null);
      },
      onError: (err: unknown) => {
        const e = err as { message?: string };
        setSnack({
          open: true,
          severity: 'error',
          message: e?.message || 'Promotion failed.',
        });
        setConfirmIdx(null);
      },
    });
  }, [confirmIdx, history, promote, result, username]);

  // -------------------------------------------------------------------------
  // Derived values
  // -------------------------------------------------------------------------
  /**
   * Group canonical entities + dataset bindings by sub-task index. The
   * backend doesn't yet return per-subtask bindings, so the chip strips on
   * each card mirror the global lists. This is good enough for the surface
   * spec'd by Phase D and lets the user see what physical assets the entire
   * decomposition will touch.
   */
  const subtaskRows = useMemo(() => {
    if (!result) return [];
    return result.domain_subtasks.map((task, idx) => ({
      idx,
      task,
      // For now: each card lists the same canonical entities / bindings.
      entities: result.canonical_entities,
      bindings: result.dataset_bindings,
    }));
  }, [result]);

  const isLoading = translate.isPending;
  const hasResult = result !== null;
  const subgraphNodes = result?.used_ontology_subgraph.nodes ?? [];
  const subgraphEdges = result?.used_ontology_subgraph.edges ?? [];

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------
  return (
    <Box>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
        <TranslateIcon color="primary" />
        <Typography variant="h5" fontWeight={600}>
          Translator
        </Typography>
        <Chip label="NL → business decomposition" size="small" variant="outlined" />
      </Stack>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Paste a natural-language question to see how the Translator service
        maps it onto canonical business entities and physical datasets. Promote
        good decompositions back into the few-shot store to bias future
        translations.
      </Typography>

      <Grid container spacing={2}>
        {/* ---------------- LEFT: input + history ------------------------ */}
        <Grid item xs={12} md={4} lg={3.6}>
          <Paper sx={{ p: 2, height: 600, display: 'flex', flexDirection: 'column' }}>
            {/* F7 — multi-turn dialog transcript */}
            {dialogTurns.length > 0 && (
              <Box sx={{ mb: 1.5, maxHeight: 200, overflowY: 'auto' }}>
                <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 0.5 }}>
                  <Typography variant="subtitle2">Dialog</Typography>
                  <Chip
                    size="small"
                    label={`${Math.ceil(dialogTurns.length / 2)} turn${dialogTurns.length > 2 ? 's' : ''}`}
                    sx={{ height: 18, fontSize: 10 }}
                  />
                  <Box sx={{ flex: 1 }} />
                  <Tooltip title="Reset dialog (start a fresh translation)">
                    <span>
                      <IconButton size="small" onClick={resetDialog} disabled={isLoading}>
                        <RestartAltIcon fontSize="small" />
                      </IconButton>
                    </span>
                  </Tooltip>
                </Stack>
                <Stack spacing={0.75}>
                  {dialogTurns.map((t, i) => (
                    <Box
                      key={`turn-${i}`}
                      sx={{
                        display: 'flex',
                        justifyContent:
                          t.role === 'user' ? 'flex-end' : 'flex-start',
                      }}
                    >
                      <Paper
                        variant="outlined"
                        sx={{
                          p: 1,
                          maxWidth: '85%',
                          bgcolor: (theme) =>
                            t.role === 'user'
                              ? theme.palette.primary.main + '22'
                              : theme.palette.action.hover,
                          borderColor: (theme) =>
                            t.role === 'user'
                              ? theme.palette.primary.light
                              : 'divider',
                        }}
                      >
                        <Typography
                          variant="caption"
                          color="text.secondary"
                          sx={{ display: 'block', fontWeight: 600, mb: 0.25 }}
                        >
                          {t.role === 'user' ? 'You' : 'Translator'}
                        </Typography>
                        <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
                          {t.content}
                        </Typography>
                      </Paper>
                    </Box>
                  ))}
                </Stack>
                <Divider sx={{ mt: 1 }} />
              </Box>
            )}

            <Typography variant="subtitle2" sx={{ mb: 1 }}>
              {dialogTurns.length > 0 ? 'Your reply' : 'Question'}
            </Typography>
            <TextField
              multiline
              minRows={dialogTurns.length > 0 ? 3 : 6}
              maxRows={12}
              fullWidth
              size="small"
              placeholder={
                dialogTurns.length > 0
                  ? 'Reply to the translator’s clarification…'
                  : 'e.g. Show me total payments by quarter for the last 2 years and compute YoY change.'
              }
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              disabled={isLoading}
            />
            <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
              <Button
                variant="contained"
                startIcon={<SendIcon />}
                onClick={submit}
                disabled={isLoading || !question.trim()}
                fullWidth
              >
                {isLoading
                  ? 'Translating…'
                  : dialogTurns.length > 0
                    ? 'Send reply'
                    : 'Translate'}
              </Button>
              {dialogTurns.length > 0 && (
                <Tooltip title="Reset dialog">
                  <span>
                    <Button
                      variant="outlined"
                      onClick={resetDialog}
                      disabled={isLoading}
                      startIcon={<RestartAltIcon />}
                    >
                      Reset
                    </Button>
                  </span>
                </Tooltip>
              )}
            </Stack>

            <Divider sx={{ my: 2 }} />

            <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
              <HistoryIcon fontSize="small" color="action" />
              <Typography variant="subtitle2">Recent (this session)</Typography>
            </Stack>
            {history.length === 0 ? (
              <Typography variant="caption" color="text.secondary">
                No questions yet. Translations from this session will appear
                here for quick reuse.
              </Typography>
            ) : (
              <Select
                size="small"
                fullWidth
                displayEmpty
                value=""
                onChange={(e) => {
                  const v = e.target.value;
                  if (typeof v === 'string' && v) handleHistoryPick(v);
                }}
                renderValue={() => 'Pick a previous question…'}
                disabled={isLoading}
              >
                {history.map((h) => (
                  <MenuItem key={`${h.ts}-${h.question}`} value={h.question}>
                    <Typography
                      variant="body2"
                      noWrap
                      sx={{ maxWidth: 300, fontFamily: 'inherit' }}
                    >
                      {h.question}
                    </Typography>
                  </MenuItem>
                ))}
              </Select>
            )}
          </Paper>
        </Grid>

        {/* ---------------- CENTER: decomposition output ------------------- */}
        <Grid item xs={12} md={8} lg={4.8}>
          <Paper
            sx={{
              p: 2,
              height: 600,
              display: 'flex',
              flexDirection: 'column',
              position: 'relative',
            }}
          >
            <Typography variant="subtitle2" sx={{ mb: 1 }}>
              Decomposition
            </Typography>

            {errorMsg && !isLoading && (
              <Alert severity="error" sx={{ mb: 1 }}>
                {errorMsg}
              </Alert>
            )}

            {!hasResult && !isLoading && !errorMsg && (
              <Box
                sx={{
                  flex: 1,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexDirection: 'column',
                  color: 'text.secondary',
                  gap: 1,
                }}
              >
                <TranslateIcon fontSize="large" />
                <Typography variant="body2" color="text.secondary">
                  Translate a question to see its business decomposition.
                </Typography>
              </Box>
            )}

            {hasResult && result && (
              <Box sx={{ flex: 1, overflowY: 'auto', pr: 0.5 }}>
                {/* Header chip strip */}
                <Stack
                  direction="row"
                  spacing={0.75}
                  sx={{ mb: 1.5, flexWrap: 'wrap', rowGap: 0.5 }}
                >
                  <Chip
                    size="small"
                    label={`intent: ${result.intent}`}
                    color="primary"
                    variant="outlined"
                  />
                  <Chip
                    size="small"
                    label={`domain: ${result.domain}`}
                    color="secondary"
                    variant="outlined"
                  />
                  {result.fallback_used && (
                    <Chip
                      size="small"
                      label="fallback used"
                      color="error"
                      variant="filled"
                    />
                  )}
                  {result.ontology_versions.map((v) => (
                    <Chip
                      key={v}
                      size="small"
                      label={v}
                      variant="outlined"
                      sx={{ fontFamily: 'monospace' }}
                    />
                  ))}
                  <Chip
                    size="small"
                    label={`trace ${result.trace_id.slice(0, 8)}`}
                    variant="outlined"
                    sx={{ fontFamily: 'monospace' }}
                  />
                  {result.auditor_issue_id && (
                    <Chip
                      size="small"
                      icon={<ReportProblemIcon sx={{ fontSize: 12 }} />}
                      label={`Auditor issue raised: ${result.auditor_issue_kind ?? 'OPEN'}`}
                      color="warning"
                      variant="outlined"
                      component={RouterLink}
                      to={`/auditor-issues?issue=${encodeURIComponent(result.auditor_issue_id)}`}
                      clickable
                    />
                  )}
                </Stack>

                {/* F7 — clarification banner */}
                {result.clarification_needed && result.clarification_question && (
                  <Alert severity="info" sx={{ mb: 1.5 }}>
                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                      Translator needs more info
                    </Typography>
                    <Typography variant="body2" sx={{ mt: 0.25 }}>
                      {result.clarification_question}
                    </Typography>
                  </Alert>
                )}

                {/* Ext2 — deterministic Report short-circuit matches. */}
                {result.matched_reports.length > 0 && (
                  <Box sx={{ mb: 1.5 }}>
                    <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
                      <Typography variant="subtitle2">Matched reports</Typography>
                      <Chip
                        size="small"
                        label={result.matched_reports.length}
                        color="primary"
                        sx={{ height: 18, fontSize: 10 }}
                      />
                      <Typography variant="caption" color="text.secondary">
                        Auto-run threshold ≥ 5.0 with lead ≥ 1.0
                      </Typography>
                    </Stack>
                    <Stack spacing={1.25}>
                      {result.matched_reports.map((r) => (
                        <MatchedReportCard key={r.report_id} report={r} />
                      ))}
                    </Stack>
                  </Box>
                )}

                <Divider sx={{ mb: 1.5 }} />

                {/* Sub-task cards */}
                {subtaskRows.length === 0 ? (
                  <Alert severity="info">
                    Translator returned no sub-tasks for this question.
                  </Alert>
                ) : (
                  <Stack spacing={1.25}>
                    {subtaskRows.map((row) => {
                      const isPromoted = feedback.promoted.has(row.idx);
                      const isDismissed = feedback.dismissed.has(row.idx);
                      return (
                        <Paper
                          key={row.idx}
                          variant="outlined"
                          sx={{
                            p: 1.25,
                            borderColor: isPromoted ? 'success.main' : undefined,
                            borderWidth: isPromoted ? 2 : 1,
                            opacity: isDismissed ? 0.45 : 1,
                            transition: 'opacity 150ms ease, border-color 150ms ease',
                          }}
                        >
                          <Stack direction="row" alignItems="flex-start" spacing={1}>
                            <Box sx={{ flex: 1, minWidth: 0 }}>
                              <Stack direction="row" alignItems="center" spacing={1}>
                                <Chip
                                  size="small"
                                  label={`#${row.idx + 1}`}
                                  sx={{ height: 18, fontSize: 10 }}
                                />
                                <Typography variant="body2" fontWeight={500}>
                                  {row.task}
                                </Typography>
                                {isPromoted && (
                                  <Tooltip title="Promoted to few-shot store">
                                    <CheckCircleIcon
                                      color="success"
                                      sx={{ fontSize: 16 }}
                                    />
                                  </Tooltip>
                                )}
                              </Stack>

                              {/* Canonical entity chips */}
                              {row.entities.length > 0 && (
                                <Stack
                                  direction="row"
                                  spacing={0.5}
                                  sx={{ mt: 1, flexWrap: 'wrap', rowGap: 0.5 }}
                                >
                                  {row.entities.map((e) => (
                                    <Chip
                                      key={e.fq_name}
                                      size="small"
                                      label={`${e.fq_name} · ${e.confidence.toFixed(
                                        2,
                                      )}`}
                                      color={
                                        e.confidence >= 0.8
                                          ? 'success'
                                          : e.confidence >= 0.5
                                            ? 'warning'
                                            : 'error'
                                      }
                                      variant="outlined"
                                      sx={{ height: 20, fontSize: 10 }}
                                    />
                                  ))}
                                </Stack>
                              )}

                              {/* Dataset binding chips */}
                              {row.bindings.length > 0 && (
                                <Stack
                                  direction="row"
                                  spacing={0.5}
                                  sx={{ mt: 0.5, flexWrap: 'wrap', rowGap: 0.5 }}
                                >
                                  {row.bindings.map((b) => (
                                    <Chip
                                      key={b.asset_fq_name}
                                      size="small"
                                      icon={<StorageIcon sx={{ fontSize: 12 }} />}
                                      label={`${b.asset_fq_name} (${b.columns.length} col${b.columns.length === 1 ? '' : 's'})`}
                                      variant="outlined"
                                      sx={{
                                        height: 20,
                                        fontSize: 10,
                                        fontFamily: 'monospace',
                                      }}
                                    />
                                  ))}
                                </Stack>
                              )}
                            </Box>

                            {/* Feedback buttons */}
                            <Stack direction="row" spacing={0.25}>
                              <Tooltip title="Promote — use as few-shot example">
                                <span>
                                  <IconButton
                                    size="small"
                                    color={isPromoted ? 'success' : 'default'}
                                    onClick={() => handleThumbsUp(row.idx)}
                                    disabled={isPromoted}
                                  >
                                    <ThumbUpAltIcon fontSize="small" />
                                  </IconButton>
                                </span>
                              </Tooltip>
                              <Tooltip title="Dismiss this sub-task (local only)">
                                <span>
                                  <IconButton
                                    size="small"
                                    color={isDismissed ? 'error' : 'default'}
                                    onClick={() => handleThumbsDown(row.idx)}
                                    disabled={isDismissed}
                                  >
                                    <ThumbDownAltIcon fontSize="small" />
                                  </IconButton>
                                </span>
                              </Tooltip>
                            </Stack>
                          </Stack>
                        </Paper>
                      );
                    })}
                  </Stack>
                )}
              </Box>
            )}

            {/* Loading overlay */}
            {isLoading && (
              <Box
                sx={{
                  position: 'absolute',
                  inset: 0,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  bgcolor: (t) =>
                    t.palette.mode === 'dark'
                      ? 'rgba(0, 0, 0, 0.45)'
                      : 'rgba(255, 255, 255, 0.55)',
                  zIndex: 1,
                  borderRadius: 1,
                }}
              >
                <Stack alignItems="center" spacing={1}>
                  <CircularProgress size={28} />
                  <Typography variant="caption" color="text.secondary">
                    Translating…
                  </Typography>
                </Stack>
              </Box>
            )}
          </Paper>
        </Grid>

        {/* ---------------- RIGHT: ontology subgraph ----------------------- */}
        <Grid item xs={12} md={12} lg={3.6}>
          <Paper
            sx={{
              p: 2,
              height: 600,
              display: 'flex',
              flexDirection: 'column',
              position: 'relative',
            }}
          >
            <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
              <HubIcon fontSize="small" color="action" />
              <Typography variant="subtitle2">Ontology subgraph used</Typography>
              {hasResult && (
                <Chip
                  size="small"
                  variant="outlined"
                  label={`${subgraphNodes.length} nodes / ${subgraphEdges.length} edges`}
                  sx={{ height: 18, fontSize: 10 }}
                />
              )}
            </Stack>

            {!hasResult && !isLoading && (
              <Box
                sx={{
                  flex: 1,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: 'text.secondary',
                }}
              >
                <Typography variant="body2" color="text.secondary">
                  The ontology nodes used for this question will be shown here.
                </Typography>
              </Box>
            )}

            {hasResult && subgraphNodes.length === 0 && !isLoading && (
              <Alert severity="info">
                No ontology subgraph returned (Translator may have used a
                fallback path).
              </Alert>
            )}

            {hasResult && subgraphNodes.length > 0 && (
              <Box sx={{ flex: 1, minHeight: 0 }}>
                <TranslationSubgraphCanvas
                  nodes={subgraphNodes}
                  edges={subgraphEdges}
                  height={520}
                />
              </Box>
            )}

            {isLoading && (
              <Box
                sx={{
                  position: 'absolute',
                  inset: 0,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  bgcolor: (t) =>
                    t.palette.mode === 'dark'
                      ? 'rgba(0, 0, 0, 0.45)'
                      : 'rgba(255, 255, 255, 0.55)',
                  zIndex: 1,
                  borderRadius: 1,
                }}
              >
                <CircularProgress size={28} />
              </Box>
            )}
          </Paper>
        </Grid>
      </Grid>

      {/* Confirm-and-promote dialog */}
      <Dialog
        open={confirmIdx !== null}
        onClose={cancelPromote}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Promote decomposition to few-shot store?</DialogTitle>
        <DialogContent>
          <DialogContentText sx={{ mb: 1.5 }}>
            This will save the entire decomposition (intent, domain, canonical
            entities, dataset bindings, and sub-tasks) to the Translator's
            few-shot example store. Future similar questions will use it to
            bias their translation.
          </DialogContentText>
          {result && confirmIdx !== null && (
            <Paper variant="outlined" sx={{ p: 1.5 }}>
              <Typography variant="caption" color="text.secondary">
                Sub-task #{confirmIdx + 1}
              </Typography>
              <Typography variant="body2" sx={{ mt: 0.5 }}>
                {result.domain_subtasks[confirmIdx]}
              </Typography>
              <Stack
                direction="row"
                spacing={0.5}
                sx={{ mt: 1, flexWrap: 'wrap', rowGap: 0.5 }}
              >
                <Chip
                  size="small"
                  label={`intent: ${result.intent}`}
                  variant="outlined"
                />
                <Chip
                  size="small"
                  label={`domain: ${result.domain}`}
                  variant="outlined"
                />
                <Chip
                  size="small"
                  label={`${result.canonical_entities.length} entities`}
                  variant="outlined"
                />
                <Chip
                  size="small"
                  label={`${result.dataset_bindings.length} bindings`}
                  variant="outlined"
                />
              </Stack>
            </Paper>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={cancelPromote} disabled={promote.isPending}>
            Cancel
          </Button>
          <Button
            variant="contained"
            color="success"
            onClick={confirmPromote}
            disabled={promote.isPending}
            startIcon={<ThumbUpAltIcon />}
          >
            {promote.isPending ? 'Promoting…' : 'Confirm & promote'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Snackbar */}
      <Snackbar
        open={snack.open}
        autoHideDuration={5000}
        onClose={() => setSnack((s) => ({ ...s, open: false }))}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      >
        <Alert
          severity={snack.severity}
          onClose={() => setSnack((s) => ({ ...s, open: false }))}
          variant="filled"
        >
          {snack.message}
        </Alert>
      </Snackbar>
    </Box>
  );
};

// ---------------------------------------------------------------------------
// Ext2 — Matched-report card. Shows a deterministic Report node that
// overlapped the question's canonical attributes. The orchestrator already
// auto-runs reports whose score ≥ 5.0 and lead ≥ 1.0, so this surface is
// informational — there is no separate "run now" endpoint.
// ---------------------------------------------------------------------------
function scoreColor(
  score: number,
): 'success' | 'info' | 'default' {
  if (score >= 10) return 'success';
  if (score >= 5) return 'info';
  return 'default';
}

const MatchedReportCard: React.FC<{ report: MatchedReport }> = ({ report }) => {
  const [showAllAttrs, setShowAllAttrs] = useState(false);
  const visibleAttrs = showAllAttrs
    ? report.uses_attributes
    : report.uses_attributes.slice(0, 6);
  const hiddenCount = report.uses_attributes.length - visibleAttrs.length;
  const willAutoRun = report.score >= 5.0;

  return (
    <Paper
      variant="outlined"
      sx={{
        p: 1.25,
        borderColor: report.score >= 5 ? 'primary.light' : undefined,
        borderWidth: report.score >= 10 ? 2 : 1,
      }}
    >
      {/* Header */}
      <Stack
        direction="row"
        alignItems="center"
        spacing={0.75}
        sx={{ mb: 0.75, flexWrap: 'wrap', rowGap: 0.5 }}
      >
        <Typography variant="body2" fontWeight={600} sx={{ flex: 1, minWidth: 0 }}>
          {report.name}
        </Typography>
        <Chip
          size="small"
          label={report.system}
          variant="outlined"
          sx={{ height: 20, fontSize: 10 }}
        />
        {report.owner_team && (
          <Chip
            size="small"
            label={report.owner_team}
            variant="outlined"
            sx={{ height: 20, fontSize: 10 }}
          />
        )}
        <Chip
          size="small"
          label={`score ${report.score.toFixed(2)}`}
          color={scoreColor(report.score)}
          sx={{ height: 20, fontSize: 10 }}
        />
      </Stack>

      {/* Body */}
      {report.description && (
        <Typography variant="body2" sx={{ mb: 0.5 }}>
          {report.description}
        </Typography>
      )}
      {report.why && (
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{ display: 'block', mb: 0.75, fontStyle: 'italic' }}
        >
          {report.why}
        </Typography>
      )}

      {/* uses_attributes chip strip */}
      {report.uses_attributes.length > 0 && (
        <Stack
          direction="row"
          spacing={0.5}
          sx={{ mb: 1, flexWrap: 'wrap', rowGap: 0.5 }}
        >
          {visibleAttrs.map((a) => (
            <Chip
              key={a}
              size="small"
              label={a}
              variant="outlined"
              sx={{ height: 18, fontSize: 10, fontFamily: 'monospace' }}
            />
          ))}
          {hiddenCount > 0 && (
            <Chip
              size="small"
              label={`+${hiddenCount} more`}
              variant="outlined"
              onClick={() => setShowAllAttrs(true)}
              sx={{ height: 18, fontSize: 10, cursor: 'pointer' }}
            />
          )}
        </Stack>
      )}

      {/* Datasets */}
      {report.datasets.length === 0 ? (
        <Alert severity="warning" sx={{ py: 0 }}>
          This report has no datasets bound — nothing to execute.
        </Alert>
      ) : (
        <Stack spacing={1}>
          {report.datasets.map((d) => (
            <Box key={d.dataset_id}>
              <Stack
                direction="row"
                alignItems="center"
                spacing={0.5}
                sx={{ mb: 0.5, flexWrap: 'wrap', rowGap: 0.25 }}
              >
                <Typography variant="caption" fontWeight={600}>
                  {d.name}
                </Typography>
                <Chip
                  size="small"
                  label={d.command_type}
                  variant="outlined"
                  sx={{ height: 16, fontSize: 9 }}
                />
                {d.source_name && (
                  <Chip
                    size="small"
                    label={d.source_name}
                    variant="outlined"
                    sx={{ height: 16, fontSize: 9 }}
                  />
                )}
              </Stack>
              <Box
                component="pre"
                sx={{
                  m: 0,
                  p: 1,
                  bgcolor: (theme) =>
                    theme.palette.mode === 'dark'
                      ? 'rgba(255,255,255,0.04)'
                      : 'rgba(0,0,0,0.04)',
                  borderRadius: 0.5,
                  fontFamily: 'monospace',
                  fontSize: 11,
                  overflowX: 'auto',
                  whiteSpace: 'pre',
                  maxHeight: 180,
                  overflowY: 'auto',
                }}
              >
                {d.command}
              </Box>
              {d.source_uri && (
                <Typography
                  variant="caption"
                  color="text.secondary"
                  sx={{ display: 'block', mt: 0.25, fontFamily: 'monospace' }}
                >
                  runs on {d.source_uri}
                </Typography>
              )}
            </Box>
          ))}
        </Stack>
      )}

      {/* Run-report indicator */}
      <Box sx={{ mt: 1 }}>
        {willAutoRun ? (
          <Alert severity="success" icon={false} sx={{ py: 0.25 }}>
            <Typography variant="caption">
              Auto-run threshold ≥ 5.0; this match scored{' '}
              <strong>{report.score.toFixed(2)}</strong>, will run automatically
              when sent through chat.
            </Typography>
          </Alert>
        ) : (
          <Alert severity="info" icon={false} sx={{ py: 0.25 }}>
            <Typography variant="caption">
              Below the auto-run threshold (≥ 5.0); this match scored{' '}
              <strong>{report.score.toFixed(2)}</strong> and will be shown as a
              suggestion only.
            </Typography>
          </Alert>
        )}
      </Box>
    </Paper>
  );
};

export default TranslatorPage;
