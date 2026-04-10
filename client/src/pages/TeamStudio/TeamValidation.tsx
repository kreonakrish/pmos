import { useMemo } from 'react';
import { Box, Typography, Chip, useTheme } from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import WarningIcon from '@mui/icons-material/Warning';
import type { Node } from 'reactflow';

interface ValidationIssue {
  severity: 'error' | 'warning';
  message: string;
}

interface TeamValidationProps {
  nodes: Node[];
}

export default function TeamValidation({ nodes }: TeamValidationProps) {
  const theme = useTheme();

  const issues = useMemo<ValidationIssue[]>(() => {
    const result: ValidationIssue[] = [];

    const orchestratorNodes = nodes.filter((n) => n.type === 'orchestratorNode');
    if (orchestratorNodes.length === 0) {
      result.push({ severity: 'error', message: 'No orchestrator assigned' });
    }

    const orchestratorWithoutAgent = orchestratorNodes.filter(
      (n) => !n.data?.agentId
    );
    if (orchestratorWithoutAgent.length > 0) {
      result.push({ severity: 'error', message: 'Orchestrator has no agent selected' });
    }

    const specialistNodes = nodes.filter((n) => n.type === 'specialistNode');
    const noAgentNodes = specialistNodes.filter((n) => !n.data?.agentId);
    if (noAgentNodes.length > 0) {
      result.push({
        severity: 'warning',
        message: `${noAgentNodes.length} node(s) have no agent assigned`,
      });
    }

    const criticalNodes = specialistNodes.filter(
      (n) => n.data?.criticality === 'CRITICAL'
    );
    const fallbackNodes = nodes.filter((n) => n.type === 'fallbackNode');
    if (criticalNodes.length > 0 && fallbackNodes.length === 0) {
      result.push({
        severity: 'warning',
        message: 'CRITICAL nodes have no fallback agents',
      });
    }

    return result;
  }, [nodes]);

  const errorCount = issues.filter((i) => i.severity === 'error').length;
  const warningCount = issues.filter((i) => i.severity === 'warning').length;
  const isValid = issues.length === 0;

  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
      {isValid ? (
        <Chip
          icon={<CheckCircleIcon />}
          label="Valid"
          size="small"
          sx={{
            bgcolor: `${theme.palette.success.main}20`,
            color: 'success.main',
            fontWeight: 600,
          }}
        />
      ) : (
        <>
          {errorCount > 0 && (
            <Chip
              icon={<ErrorIcon />}
              label={`${errorCount} error${errorCount > 1 ? 's' : ''}`}
              size="small"
              sx={{
                bgcolor: `${theme.palette.error.main}20`,
                color: 'error.main',
                fontWeight: 600,
              }}
            />
          )}
          {warningCount > 0 && (
            <Chip
              icon={<WarningIcon />}
              label={`${warningCount} warning${warningCount > 1 ? 's' : ''}`}
              size="small"
              sx={{
                bgcolor: `${theme.palette.warning.main}20`,
                color: 'warning.main',
                fontWeight: 600,
              }}
            />
          )}
        </>
      )}

      {issues.length > 0 && (
        <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
          {issues.slice(0, 3).map((issue, idx) => (
            <Typography
              key={idx}
              variant="caption"
              sx={{
                color: issue.severity === 'error' ? 'error.main' : 'warning.main',
                fontSize: '0.7rem',
              }}
            >
              {issue.message}
              {idx < Math.min(issues.length, 3) - 1 && ' | '}
            </Typography>
          ))}
        </Box>
      )}
    </Box>
  );
}
