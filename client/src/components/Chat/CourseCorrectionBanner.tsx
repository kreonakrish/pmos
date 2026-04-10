import React, { useState } from 'react';
import {
  Box,
  Typography,
  Collapse,
  IconButton,
  useTheme,
} from '@mui/material';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import type { CourseCorrection } from '@/types';

interface Props {
  correction: CourseCorrection;
}

const CourseCorrectionBanner: React.FC<Props> = ({ correction }) => {
  const theme = useTheme();
  const [expanded, setExpanded] = useState(false);

  return (
    <Box
      sx={{
        mb: 1,
        p: 1.5,
        borderRadius: 1,
        bgcolor: theme.palette.warning.main + '1A', // 10% opacity
        border: 1,
        borderColor: theme.palette.warning.main,
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <WarningAmberIcon sx={{ color: theme.palette.warning.main }} />
        <Typography
          variant="subtitle2"
          sx={{ flex: 1, color: theme.palette.warning.dark }}
        >
          Course Correction
        </Typography>
        {correction.details && (
          <IconButton
            size="small"
            onClick={() => setExpanded((p) => !p)}
            sx={{
              transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)',
              transition: 'transform 0.2s',
            }}
          >
            <ExpandMoreIcon fontSize="small" />
          </IconButton>
        )}
      </Box>

      <Typography variant="body2" sx={{ mt: 0.5, color: 'text.primary' }}>
        {correction.reason}
      </Typography>

      {(correction.from_agent || correction.to_agent) && (
        <Typography variant="caption" sx={{ display: 'block', mt: 0.5, color: 'text.secondary' }}>
          {correction.from_agent && correction.to_agent
            ? `Reassigned from ${correction.from_agent} to ${correction.to_agent}`
            : correction.to_agent
              ? `Assigned to ${correction.to_agent}`
              : `Removed from ${correction.from_agent}`}
        </Typography>
      )}

      {correction.details && (
        <Collapse in={expanded}>
          <Typography
            variant="body2"
            sx={{ mt: 1, p: 1, borderRadius: 1, bgcolor: 'action.hover', color: 'text.secondary' }}
          >
            {correction.details}
          </Typography>
        </Collapse>
      )}
    </Box>
  );
};

export default CourseCorrectionBanner;
