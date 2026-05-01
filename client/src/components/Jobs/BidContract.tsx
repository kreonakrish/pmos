/**
 * Bid contract renderer — what the winning agent committed to deliver.
 *
 * Surfaces the agent's `coverage` (which question parts it owns vs which
 * other agents handle) and `plan` (the SQL/Cypher/Python sketch it
 * promised to run, with expected_columns) onto the Pipeline Jobs page.
 *
 * Hidden when the bid carried no structured contract — either bidding
 * was skipped (schema-meta override) or the bid LLM emitted the legacy
 * {confidence, reasoning, eligible} shape and we kept its old behaviour.
 */

import {
  Box,
  Chip,
  Stack,
  Tooltip,
  Typography,
  useTheme,
} from '@mui/material';
import HandshakeIcon from '@mui/icons-material/Handshake';
import type { BidCoverage, BidPlanStep } from '@/api/jobs';

interface Props {
  plan: BidPlanStep[] | null | undefined;
  coverage: BidCoverage | null | undefined;
  planFormat: string | null | undefined;
}

export default function BidContract({ plan, coverage, planFormat }: Props) {
  const theme = useTheme();

  const hasPlan = Array.isArray(plan) && plan.length > 0;
  const hasCoverage =
    coverage &&
    ((coverage.answerable && coverage.answerable.length > 0) ||
      (coverage.not_answerable && coverage.not_answerable.length > 0));

  if (planFormat === 'legacy' || (!hasPlan && !hasCoverage)) {
    return null;
  }

  const ratio = (() => {
    if (!coverage) return null;
    const total =
      (coverage.answerable?.length ?? 0) +
      (coverage.not_answerable?.length ?? 0);
    if (total === 0) return null;
    return `${coverage.answerable?.length ?? 0}/${total}`;
  })();

  return (
    <Box
      sx={{
        mt: 1,
        p: 1.5,
        bgcolor: theme.palette.action.hover,
        borderRadius: 1,
        borderLeft: `3px solid ${theme.palette.primary.main}`,
      }}
    >
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 0.75 }}>
        <HandshakeIcon fontSize="small" color="primary" />
        <Typography
          variant="caption"
          sx={{ fontWeight: 600, color: theme.palette.text.primary }}
        >
          Bid contract
        </Typography>
        {ratio && (
          <Tooltip title="answerable / total parts the agent declared">
            <Chip
              label={`coverage ${ratio}`}
              size="small"
              variant="outlined"
              color="primary"
              sx={{ height: 18, fontSize: '0.6rem' }}
            />
          </Tooltip>
        )}
      </Stack>

      {hasCoverage && (
        <Stack spacing={0.5} sx={{ mb: hasPlan ? 1 : 0 }}>
          {coverage!.answerable && coverage!.answerable.length > 0 && (
            <Box>
              <Typography variant="caption" color="text.secondary">
                <strong>committed:</strong>{' '}
              </Typography>
              {coverage!.answerable.map((p) => (
                <Chip
                  key={`ans-${p}`}
                  label={p}
                  size="small"
                  color="success"
                  variant="outlined"
                  sx={{ height: 18, fontSize: '0.6rem', mr: 0.5, mb: 0.25 }}
                />
              ))}
            </Box>
          )}
          {coverage!.not_answerable && coverage!.not_answerable.length > 0 && (
            <Box>
              <Typography variant="caption" color="text.secondary">
                <strong>handled by other agents:</strong>{' '}
              </Typography>
              {coverage!.not_answerable.map((p) => (
                <Chip
                  key={`miss-${p}`}
                  label={p}
                  size="small"
                  variant="outlined"
                  sx={{
                    height: 18,
                    fontSize: '0.6rem',
                    mr: 0.5,
                    mb: 0.25,
                    color: theme.palette.text.secondary,
                  }}
                />
              ))}
            </Box>
          )}
          {coverage!.reason_missing && (
            <Typography
              variant="caption"
              color="text.secondary"
              sx={{ fontStyle: 'italic' }}
            >
              {coverage!.reason_missing}
            </Typography>
          )}
        </Stack>
      )}

      {hasPlan && (
        <Box sx={{ overflow: 'auto' }}>
          <table
            style={{
              width: '100%',
              borderCollapse: 'collapse',
              fontSize: '0.72rem',
              fontFamily: 'monospace',
            }}
          >
            <thead>
              <tr>
                {['#', 'Tool', 'Kind', 'Purpose', 'Expected columns', 'Sketch'].map(
                  (h) => (
                    <th
                      key={h}
                      style={{
                        textAlign: 'left',
                        padding: '4px 8px',
                        fontWeight: 600,
                        borderBottom: `1px solid ${theme.palette.divider}`,
                        color: theme.palette.text.secondary,
                        fontSize: '0.65rem',
                      }}
                    >
                      {h}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {plan!.map((step, i) => (
                <tr key={i}>
                  <td style={{ padding: '4px 8px' }}>{i + 1}</td>
                  <td style={{ padding: '4px 8px', fontWeight: 600 }}>{step.tool}</td>
                  <td style={{ padding: '4px 8px' }}>{step.kind}</td>
                  <td
                    style={{
                      padding: '4px 8px',
                      maxWidth: 200,
                      whiteSpace: 'normal',
                      color: theme.palette.text.secondary,
                    }}
                  >
                    {step.purpose || '—'}
                  </td>
                  <td style={{ padding: '4px 8px' }}>
                    {(step.expected_columns ?? []).join(', ') || '—'}
                  </td>
                  <td
                    style={{
                      padding: '4px 8px',
                      maxWidth: 360,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                      color: theme.palette.text.secondary,
                    }}
                  >
                    <Tooltip title={step.sketch || ''} placement="top">
                      <span>{step.sketch || '—'}</span>
                    </Tooltip>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Box>
      )}
    </Box>
  );
}
