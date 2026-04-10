import React, { useState } from 'react';
import {
  Box,
  Typography,
  Collapse,
  useTheme,
} from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import RadioButtonCheckedIcon from '@mui/icons-material/RadioButtonChecked';
import ErrorIcon from '@mui/icons-material/Error';
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty';
import type { PipelineStep, PipelineStepStatus } from '@/types';

interface Props {
  steps: PipelineStep[];
}

function useStatusIcon(status: PipelineStepStatus) {
  const theme = useTheme();
  switch (status) {
    case 'completed':
      return <CheckCircleIcon fontSize="small" sx={{ color: theme.palette.success.main }} />;
    case 'running':
      return (
        <RadioButtonCheckedIcon
          fontSize="small"
          sx={{
            color: theme.palette.info.main,
            animation: 'pulse 1.2s ease-in-out infinite',
            '@keyframes pulse': {
              '0%': { opacity: 1 },
              '50%': { opacity: 0.4 },
              '100%': { opacity: 1 },
            },
          }}
        />
      );
    case 'failed':
      return <ErrorIcon fontSize="small" sx={{ color: theme.palette.error.main }} />;
    case 'pending':
    default:
      return <HourglassEmptyIcon fontSize="small" sx={{ color: theme.palette.text.disabled }} />;
  }
}

const StepRow: React.FC<{ step: PipelineStep }> = ({ step }) => {
  const [expanded, setExpanded] = useState(false);
  const icon = useStatusIcon(step.status);

  return (
    <Box sx={{ mb: 0.5 }}>
      <Box
        onClick={() => step.details && setExpanded((p) => !p)}
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 1,
          cursor: step.details ? 'pointer' : 'default',
          py: 0.5,
          px: 1,
          borderRadius: 1,
          '&:hover': step.details ? { bgcolor: 'action.hover' } : undefined,
        }}
      >
        {icon}
        <Typography variant="body2" sx={{ flex: 1 }}>
          {step.label}
        </Typography>
        {step.duration_ms != null && (
          <Typography variant="caption" sx={{ color: 'text.secondary' }}>
            {step.duration_ms}ms
          </Typography>
        )}
        {step.completed_at && (
          <Typography variant="caption" sx={{ color: 'text.secondary', ml: 1 }}>
            {new Date(step.completed_at).toLocaleTimeString()}
          </Typography>
        )}
      </Box>
      {step.details && (
        <Collapse in={expanded}>
          <Box sx={{ pl: 4.5, pb: 1 }}>
            {step.details.map((detail, idx) => (
              <Typography key={idx} variant="caption" component="div" sx={{ color: 'text.secondary' }}>
                {detail.agent_name}: {detail.action}
                {detail.score != null && ` (score: ${detail.score.toFixed(2)})`}
              </Typography>
            ))}
          </Box>
        </Collapse>
      )}
    </Box>
  );
};

const StepTimeline: React.FC<Props> = ({ steps }) => {
  return (
    <Box
      sx={{
        mt: 1,
        p: 1,
        borderRadius: 1,
        bgcolor: 'action.hover',
      }}
    >
      <Typography variant="caption" sx={{ fontWeight: 600, mb: 0.5, display: 'block', color: 'text.secondary' }}>
        Pipeline Steps
      </Typography>
      {steps.map((step, idx) => (
        <StepRow key={step.name + idx} step={step} />
      ))}
    </Box>
  );
};

export default StepTimeline;
