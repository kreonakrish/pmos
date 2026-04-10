import { useMemo } from 'react';
import { Box, Typography, Skeleton } from '@mui/material';
import { useTheme, alpha } from '@mui/material/styles';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  Cell,
} from 'recharts';
import type { ScoreHistory } from '@/types';

interface Props {
  data: ScoreHistory[];
  loading?: boolean;
}

const BUCKETS = [
  '0-0.1', '0.1-0.2', '0.2-0.3', '0.3-0.4', '0.4-0.5',
  '0.5-0.6', '0.6-0.7', '0.7-0.8', '0.8-0.9', '0.9-1.0',
];

function lerpColor(t: number, theme: { palette: { error: { main: string }; warning: { main: string }; success: { main: string } } }) {
  if (t < 0.4) return theme.palette.error.main;
  if (t < 0.7) return theme.palette.warning.main;
  return theme.palette.success.main;
}

export default function ScoreDistribution({ data, loading }: Props) {
  const theme = useTheme();

  const bucketData = useMemo(() => {
    const counts = new Array(10).fill(0);
    data.forEach((entry) => {
      const idx = Math.min(Math.floor(entry.score * 10), 9);
      counts[idx]++;
    });
    return BUCKETS.map((label, i) => ({
      bucket: label,
      count: counts[i],
      midpoint: (i + 0.5) / 10,
    }));
  }, [data]);

  if (loading) {
    return <Skeleton variant="rectangular" height={280} sx={{ borderRadius: 1 }} />;
  }

  if (data.length === 0) {
    return (
      <Box sx={{ height: 280, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Typography variant="body2" color="text.secondary">
          No score data available
        </Typography>
      </Box>
    );
  }

  return (
    <Box>
      <Typography variant="subtitle2" gutterBottom>
        Score Distribution
      </Typography>
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={bucketData}>
          <CartesianGrid strokeDasharray="3 3" stroke={alpha(theme.palette.divider, 0.5)} />
          <XAxis dataKey="bucket" tick={{ fontSize: 10 }} />
          <YAxis allowDecimals={false} tick={{ fontSize: 10 }} />
          <Tooltip
            contentStyle={{
              backgroundColor: theme.palette.background.paper,
              border: `1px solid ${theme.palette.divider}`,
            }}
          />
          <Bar dataKey="count" radius={[4, 4, 0, 0]}>
            {bucketData.map((entry, idx) => (
              <Cell key={idx} fill={lerpColor(entry.midpoint, theme)} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </Box>
  );
}
