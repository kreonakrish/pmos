import { Paper, Typography, Box } from '@mui/material';
import TrendingUpIcon from '@mui/icons-material/TrendingUp';
import TrendingDownIcon from '@mui/icons-material/TrendingDown';
import type { SvgIconComponent } from '@mui/icons-material';

interface Props {
  label: string;
  value: string | number;
  trend?: 'up' | 'down';
  icon?: SvgIconComponent;
}

export default function StatCard({ label, value, trend, icon: Icon }: Props) {

  return (
    <Paper
      sx={{
        p: 2.5,
        position: 'relative',
        overflow: 'hidden',
        height: '100%',
      }}
    >
      {Icon && (
        <Box
          sx={{
            position: 'absolute',
            top: 12,
            right: 12,
            color: 'text.disabled',
            opacity: 0.5,
          }}
        >
          <Icon fontSize="large" />
        </Box>
      )}
      <Typography variant="h4" fontWeight={700} sx={{ mb: 0.5 }}>
        {value}
      </Typography>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
        <Typography variant="body2" color="text.secondary">
          {label}
        </Typography>
        {trend === 'up' && (
          <TrendingUpIcon sx={{ fontSize: 16, color: 'success.main' }} />
        )}
        {trend === 'down' && (
          <TrendingDownIcon sx={{ fontSize: 16, color: 'error.main' }} />
        )}
      </Box>
    </Paper>
  );
}
