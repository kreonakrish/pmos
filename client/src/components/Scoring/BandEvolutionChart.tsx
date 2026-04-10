import { Box, Typography, TextField, MenuItem, Skeleton } from '@mui/material';
import { useTheme, alpha } from '@mui/material/styles';
import {
  AreaChart,
  Area,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts';
import type { Agent, ScoreHistory } from '@/types';

interface Props {
  agents: Agent[];
  selectedAgentId: number | null;
  onAgentChange: (id: number) => void;
  data: ScoreHistory[];
  loading?: boolean;
}

export default function BandEvolutionChart({
  agents,
  selectedAgentId,
  onAgentChange,
  data,
  loading,
}: Props) {
  const theme = useTheme();
  const last50 = data.slice(-50);

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
        <Typography variant="subtitle2">Band Evolution</Typography>
        <TextField
          select
          size="small"
          value={selectedAgentId ?? ''}
          onChange={(e) => onAgentChange(Number(e.target.value))}
          sx={{ minWidth: 160 }}
          label="Agent"
        >
          {agents.map((a) => (
            <MenuItem key={a.id} value={a.id}>
              {a.name}
            </MenuItem>
          ))}
        </TextField>
      </Box>

      {loading ? (
        <Skeleton variant="rectangular" height={250} sx={{ borderRadius: 1 }} />
      ) : last50.length === 0 ? (
        <Box sx={{ height: 250, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Typography variant="body2" color="text.secondary">
            {selectedAgentId ? 'No band data for this agent' : 'Select an agent to view band evolution'}
          </Typography>
        </Box>
      ) : (
        <ResponsiveContainer width="100%" height={250}>
          <AreaChart data={last50}>
            <CartesianGrid strokeDasharray="3 3" stroke={alpha(theme.palette.divider, 0.5)} />
            <XAxis dataKey="created_at" tick={false} />
            <YAxis domain={[0, 1]} width={35} tick={{ fontSize: 10 }} />
            <Tooltip
              contentStyle={{
                backgroundColor: theme.palette.background.paper,
                border: `1px solid ${theme.palette.divider}`,
              }}
              labelFormatter={() => ''}
            />
            <Area
              dataKey="band_high"
              stroke={theme.palette.warning.main}
              fill={alpha(theme.palette.warning.main, 0.15)}
              strokeWidth={1.5}
              name="Band High"
            />
            <Area
              dataKey="band_low"
              stroke={theme.palette.info.main}
              fill={alpha(theme.palette.info.main, 0.15)}
              strokeWidth={1.5}
              name="Band Low"
            />
            <Line
              dataKey="score"
              stroke={theme.palette.primary.main}
              strokeWidth={2}
              dot={false}
              name="Score"
              type="monotone"
            />
          </AreaChart>
        </ResponsiveContainer>
      )}
    </Box>
  );
}
