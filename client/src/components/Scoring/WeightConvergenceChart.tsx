import { Box, Typography, TextField, MenuItem, Skeleton } from '@mui/material';
import { useTheme, alpha } from '@mui/material/styles';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts';
import type { Agent } from '@/types';

interface WeightPoint {
  update: number;
  relevance: number;
  accuracy: number;
  tool_success: number;
  latency: number;
  memory_util: number;
  validation: number;
}

interface Props {
  agents: Agent[];
  selectedAgentId: number | null;
  onAgentChange: (id: number) => void;
  data: WeightPoint[];
  loading?: boolean;
}

const WEIGHT_KEYS: { key: keyof Omit<WeightPoint, 'update'>; label: string }[] = [
  { key: 'relevance', label: 'Relevance' },
  { key: 'accuracy', label: 'Accuracy' },
  { key: 'tool_success', label: 'Tool Success' },
  { key: 'latency', label: 'Latency' },
  { key: 'memory_util', label: 'Memory Util' },
  { key: 'validation', label: 'Validation' },
];

export default function WeightConvergenceChart({
  agents,
  selectedAgentId,
  onAgentChange,
  data,
  loading,
}: Props) {
  const theme = useTheme();

  const LINE_COLORS = [
    theme.palette.primary.main,
    theme.palette.secondary.main,
    theme.palette.error.main,
    theme.palette.warning.main,
    theme.palette.info.main,
    theme.palette.success.main,
  ];

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
        <Typography variant="subtitle2">Weight Convergence</Typography>
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
      ) : data.length === 0 ? (
        <Box sx={{ height: 250, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Typography variant="body2" color="text.secondary">
            {selectedAgentId ? 'No weight history for this agent' : 'Select an agent to view weight convergence'}
          </Typography>
        </Box>
      ) : (
        <ResponsiveContainer width="100%" height={250}>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke={alpha(theme.palette.divider, 0.5)} />
            <XAxis dataKey="update" tick={{ fontSize: 10 }} label={{ value: 'Update #', position: 'insideBottom', offset: -5, fontSize: 10 }} />
            <YAxis domain={[0, 1]} width={35} tick={{ fontSize: 10 }} />
            <Tooltip
              contentStyle={{
                backgroundColor: theme.palette.background.paper,
                border: `1px solid ${theme.palette.divider}`,
              }}
            />
            <Legend
              verticalAlign="bottom"
              height={36}
              wrapperStyle={{ fontSize: 10 }}
            />
            {WEIGHT_KEYS.map(({ key, label }, i) => (
              <Line
                key={key}
                dataKey={key}
                name={label}
                stroke={LINE_COLORS[i]}
                strokeWidth={1.5}
                dot={false}
                type="monotone"
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      )}
    </Box>
  );
}
