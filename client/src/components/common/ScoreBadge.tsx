import React from 'react';
import { Chip } from '@mui/material';
import type { ScoreBand } from '@/types';

interface ScoreBadgeProps {
  score: number;
  band?: ScoreBand;
  size?: 'small' | 'medium';
}

function getBadgeColor(score: number, band?: ScoreBand): 'success' | 'warning' | 'error' | 'default' {
  if (!band) return 'default';
  if (score >= band.high) return 'success';
  if (score >= band.low) return 'warning';
  return 'error';
}

const ScoreBadge: React.FC<ScoreBadgeProps> = ({ score, band, size = 'small' }) => {
  const color = getBadgeColor(score, band);

  return (
    <Chip
      label={score.toFixed(2)}
      color={color}
      size={size}
      variant="filled"
      sx={{
        fontWeight: 600,
        minWidth: 52,
      }}
    />
  );
};

export default ScoreBadge;
