/**
 * Pattern-decision trace renderer for the Pipeline Jobs page.
 *
 * Shows every QuestionPattern's score / threshold / accept verdict for
 * a single pipeline run, plus the evidence that fired. The orchestrator
 * stamps this on TaskGraph; we just render. No client-side scoring.
 */

import {
  Alert,
  Box,
  Chip,
  Stack,
  Typography,
  useTheme,
} from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import CancelIcon from '@mui/icons-material/Cancel';
import EmojiEventsIcon from '@mui/icons-material/EmojiEvents';
import type { PatternDecisionTrace } from '@/api/jobs';

interface Props {
  trace: PatternDecisionTrace | null | undefined;
}

export default function PatternDecision({ trace }: Props) {
  const theme = useTheme();

  if (!trace) {
    // No decision recorded — pre-Phase-1 graph or stamping failed.
    return null;
  }

  const candidates = [...(trace.candidates || [])].sort((a, b) => {
    // Winner first, then accepted, then by score desc, then by priority desc.
    const aw = a.name === trace.winner ? 1 : 0;
    const bw = b.name === trace.winner ? 1 : 0;
    if (aw !== bw) return bw - aw;
    if (a.accepted !== b.accepted) return a.accepted ? -1 : 1;
    if (a.score !== b.score) return b.score - a.score;
    return b.priority - a.priority;
  });

  return (
    <Box>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{ fontWeight: 600 }}
        >
          Pattern Decision
        </Typography>
        {trace.shadow && (
          <Chip
            label="shadow"
            size="small"
            color="warning"
            variant="outlined"
            sx={{ height: 18, fontSize: '0.6rem' }}
          />
        )}
        {trace.winner && (
          <Chip
            icon={<EmojiEventsIcon fontSize="small" />}
            label={`winner: ${trace.winner}`}
            size="small"
            color="primary"
            variant="filled"
            sx={{ height: 22, fontSize: '0.7rem' }}
          />
        )}
        <Typography variant="caption" color="text.secondary">
          ({trace.duration_ms}ms · {candidates.length} pattern{candidates.length === 1 ? '' : 's'})
        </Typography>
      </Stack>

      {trace.shadow && (
        <Alert
          severity="info"
          variant="outlined"
          sx={{ mb: 1, fontSize: '0.75rem', py: 0.5 }}
        >
          Dispatcher is in shadow mode. The candidate scores are recorded
          but the legacy if/elif gates drove this run. Cutover happens in
          Phase 4.
        </Alert>
      )}

      {candidates.length === 0 ? (
        <Typography variant="caption" color="text.secondary">
          No patterns registered. (Phase 1 ships an empty registry.)
        </Typography>
      ) : (
        <Box sx={{ overflow: 'auto' }}>
          <table
            style={{
              width: '100%',
              borderCollapse: 'collapse',
              fontSize: '0.78rem',
            }}
          >
            <thead>
              <tr>
                {[
                  'Pattern',
                  'Priority',
                  'Score',
                  'Threshold',
                  'Verdict',
                  'Why',
                ].map((h) => (
                  <th
                    key={h}
                    style={{
                      textAlign: 'left',
                      padding: '6px 10px',
                      fontWeight: 600,
                      borderBottom: `1px solid ${theme.palette.divider}`,
                      color: theme.palette.text.secondary,
                      fontSize: '0.7rem',
                    }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {candidates.map((c) => {
                const isWinner = c.name === trace.winner;
                return (
                  <tr
                    key={c.name}
                    style={
                      isWinner
                        ? { backgroundColor: theme.palette.action.selected }
                        : undefined
                    }
                  >
                    <td style={{ padding: '6px 10px', fontWeight: isWinner ? 700 : 500 }}>
                      <Stack direction="row" alignItems="center" spacing={0.5}>
                        {isWinner && <EmojiEventsIcon fontSize="small" color="primary" />}
                        <span>{c.name}</span>
                      </Stack>
                    </td>
                    <td style={{ padding: '6px 10px', fontFamily: 'monospace' }}>
                      {c.priority}
                    </td>
                    <td style={{ padding: '6px 10px', fontFamily: 'monospace' }}>
                      {c.score.toFixed(3)}
                    </td>
                    <td style={{ padding: '6px 10px', fontFamily: 'monospace' }}>
                      {c.threshold.toFixed(3)}
                    </td>
                    <td style={{ padding: '6px 10px' }}>
                      {c.error ? (
                        <Chip
                          icon={<CancelIcon fontSize="small" />}
                          label="error"
                          size="small"
                          color="error"
                          variant="outlined"
                          sx={{ height: 20, fontSize: '0.65rem' }}
                        />
                      ) : c.accepted ? (
                        <Chip
                          icon={<CheckCircleIcon fontSize="small" />}
                          label="accepted"
                          size="small"
                          color="success"
                          variant="outlined"
                          sx={{ height: 20, fontSize: '0.65rem' }}
                        />
                      ) : (
                        <Chip
                          label="rejected"
                          size="small"
                          variant="outlined"
                          sx={{ height: 20, fontSize: '0.65rem' }}
                        />
                      )}
                    </td>
                    <td
                      style={{
                        padding: '6px 10px',
                        color: theme.palette.text.secondary,
                        fontSize: '0.75rem',
                      }}
                    >
                      {c.error
                        ? c.error
                        : c.explanation || c.evidence.join('; ') || '—'}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Box>
      )}

      {/* Translator summary footer — what the dispatcher saw. */}
      {trace.translator_summary && (
        <Stack
          direction="row"
          spacing={2}
          sx={{ mt: 1.5, flexWrap: 'wrap', rowGap: 0.5 }}
          useFlexGap
        >
          <Typography variant="caption" color="text.secondary">
            <strong>intent:</strong> {trace.translator_summary.intent ?? '—'}
          </Typography>
          {trace.translator_summary.domain && (
            <Typography variant="caption" color="text.secondary">
              <strong>domain:</strong> {trace.translator_summary.domain}
            </Typography>
          )}
          <Typography variant="caption" color="text.secondary">
            <strong>entities:</strong>{' '}
            {trace.translator_summary.n_canonical_entities ?? 0}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            <strong>bindings:</strong>{' '}
            {trace.translator_summary.n_dataset_bindings ?? 0}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            <strong>reports:</strong>{' '}
            {trace.translator_summary.n_matched_reports ?? 0}
          </Typography>
          {trace.translator_summary.schema_meta_column && (
            <Typography variant="caption" color="text.secondary">
              <strong>column:</strong> {trace.translator_summary.schema_meta_column}
            </Typography>
          )}
        </Stack>
      )}
    </Box>
  );
}
