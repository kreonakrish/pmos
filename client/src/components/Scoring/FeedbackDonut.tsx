import { Box, Typography, Skeleton } from '@mui/material';
import { useTheme } from '@mui/material/styles';
import {
  PieChart,
  Pie,
  Cell,
  Legend,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';

interface FeedbackSlice {
  name: string;
  value: number;
}

interface Props {
  data?: FeedbackSlice[];
  loading?: boolean;
}

const DEFAULT_DATA: FeedbackSlice[] = [
  { name: 'Automated', value: 40 },
  { name: 'User', value: 30 },
  { name: 'Inter-Agent', value: 20 },
  { name: 'Orchestrator', value: 10 },
];

export default function FeedbackDonut({ data, loading }: Props) {
  const theme = useTheme();
  const slices = data ?? DEFAULT_DATA;

  const COLORS = [
    theme.palette.primary.main,
    theme.palette.secondary.main,
    theme.palette.info.main,
    theme.palette.warning.main,
  ];

  if (loading) {
    return <Skeleton variant="circular" width={280} height={280} sx={{ mx: 'auto' }} />;
  }

  return (
    <Box>
      <Typography variant="subtitle2" gutterBottom>
        Feedback Sources
      </Typography>
      <ResponsiveContainer width="100%" height={280}>
        <PieChart>
          <Pie
            data={slices}
            cx="50%"
            cy="45%"
            innerRadius={60}
            outerRadius={90}
            paddingAngle={3}
            dataKey="value"
            label={false}
          >
            {slices.map((_entry, idx) => (
              <Cell key={idx} fill={COLORS[idx % COLORS.length]} />
            ))}
          </Pie>
          <Tooltip
            contentStyle={{
              backgroundColor: theme.palette.background.paper,
              border: `1px solid ${theme.palette.divider}`,
            }}
          />
          <Legend
            verticalAlign="bottom"
            height={36}
            formatter={(value: string) => (
              <Typography variant="caption" component="span" color="text.secondary">
                {value}
              </Typography>
            )}
          />
          {/* Center label */}
          <text
            x="50%"
            y="45%"
            textAnchor="middle"
            dominantBaseline="middle"
            fill={theme.palette.text.secondary}
            fontSize={12}
          >
            Feedback Sources
          </text>
        </PieChart>
      </ResponsiveContainer>
    </Box>
  );
}
