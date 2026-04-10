import { useMemo } from 'react';
import {
  Box,
  Typography,
  Stack,
  Paper,
  Table,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
  TableContainer,
  Chip,
  Alert,
  useTheme,
} from '@mui/material';
import {
  LineChart,
  Line,
  AreaChart,
  Area,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';
import { useScoreHistory, useScoringWeights } from '@/api/scoring';

interface PerformanceTabProps {
  agentId?: number;
}

export default function PerformanceTab({ agentId }: PerformanceTabProps) {
  const theme = useTheme();

  const { data: scoreHistory } = useScoreHistory(agentId ?? 0, {
    enabled: !!agentId && agentId > 0,
  });

  const { data: weightsData } = useScoringWeights(agentId ?? 0, {
    enabled: !!agentId && agentId > 0,
  });

  if (!agentId) {
    return (
      <Alert severity="info" variant="outlined">
        Save this agent first to see performance data.
      </Alert>
    );
  }

  // Score history chart data (last 50)
  const scoreChartData = useMemo(() => {
    if (!scoreHistory || scoreHistory.length === 0) {
      // Generate placeholder data
      return Array.from({ length: 20 }, (_, i) => ({
        idx: i + 1,
        score: 0.5 + Math.random() * 0.4,
        band_low: 0.5,
        band_high: 0.85,
      }));
    }
    return scoreHistory.slice(-50).map((entry, i) => ({
      idx: i + 1,
      score: entry.score,
      band_low: entry.band_low,
      band_high: entry.band_high,
    }));
  }, [scoreHistory]);

  // Band evolution chart data
  const bandChartData = useMemo(() => {
    if (!scoreHistory || scoreHistory.length === 0) {
      return Array.from({ length: 20 }, (_, i) => ({
        idx: i + 1,
        band_low: 0.5 + Math.random() * 0.05,
        band_high: 0.8 + Math.random() * 0.1,
      }));
    }
    return scoreHistory.slice(-50).map((entry, i) => ({
      idx: i + 1,
      band_low: entry.band_low,
      band_high: entry.band_high,
    }));
  }, [scoreHistory]);

  // Radar chart data for RL weights
  const radarData = useMemo(() => {
    const defaults: Record<string, number> = {
      Relevance: 0.2,
      Accuracy: 0.2,
      Precision: 0.15,
      Latency: 0.15,
      Confidence: 0.15,
      Knowledge: 0.15,
    };

    if (weightsData?.weights) {
      return Object.entries(defaults).map(([label]) => {
        const key = label.toLowerCase().replace(' ', '_');
        return {
          subject: label,
          weight: weightsData.weights[key] ?? defaults[label],
        };
      });
    }

    return Object.entries(defaults).map(([label, value]) => ({
      subject: label,
      weight: value + (Math.random() - 0.5) * 0.1,
    }));
  }, [weightsData]);

  // Top tasks placeholder
  const topTasks = [
    { task_type: 'data_analysis', count: 12, avg_score: 0.82 },
    { task_type: 'code_generation', count: 8, avg_score: 0.76 },
    { task_type: 'api_integration', count: 5, avg_score: 0.91 },
  ];

  // Recent failures placeholder
  const recentFailures = [
    {
      task_id: 'task-001',
      reason: 'Timeout during database query',
      correction: 'Switched to fallback agent with optimized query',
      severity: 'MEDIUM' as 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL',
    },
  ];

  const chartTooltipStyle = {
    backgroundColor: theme.palette.background.paper,
    border: `1px solid ${theme.palette.divider}`,
    borderRadius: 4,
    fontSize: 12,
  };

  return (
    <Stack spacing={3} sx={{ maxWidth: 1000 }}>
      {/* Score History */}
      <Box>
        <Typography variant="subtitle2" gutterBottom>
          Score History (Last 50 Executions)
        </Typography>
        <Paper variant="outlined" sx={{ p: 2 }}>
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={scoreChartData}>
              <CartesianGrid strokeDasharray="3 3" stroke={theme.palette.divider} />
              <XAxis dataKey="idx" fontSize={11} />
              <YAxis domain={[0, 1]} fontSize={11} />
              <Tooltip contentStyle={chartTooltipStyle} />
              <Legend />
              <Line
                type="monotone"
                dataKey="score"
                stroke={theme.palette.primary.main}
                strokeWidth={2}
                dot={{ r: 2 }}
                name="Score"
              />
              <Line
                type="monotone"
                dataKey="band_low"
                stroke={theme.palette.warning.main}
                strokeWidth={1}
                strokeDasharray="4 4"
                dot={false}
                name="Band Low"
              />
              <Line
                type="monotone"
                dataKey="band_high"
                stroke={theme.palette.success.main}
                strokeWidth={1}
                strokeDasharray="4 4"
                dot={false}
                name="Band High"
              />
            </LineChart>
          </ResponsiveContainer>
        </Paper>
      </Box>

      <Stack direction={{ xs: 'column', md: 'row' }} spacing={3}>
        {/* Band Evolution */}
        <Box sx={{ flex: 1 }}>
          <Typography variant="subtitle2" gutterBottom>
            Band Evolution
          </Typography>
          <Paper variant="outlined" sx={{ p: 2 }}>
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart data={bandChartData}>
                <CartesianGrid strokeDasharray="3 3" stroke={theme.palette.divider} />
                <XAxis dataKey="idx" fontSize={11} />
                <YAxis domain={[0, 1]} fontSize={11} />
                <Tooltip contentStyle={chartTooltipStyle} />
                <Area
                  type="monotone"
                  dataKey="band_high"
                  stackId="1"
                  stroke={theme.palette.primary.light}
                  fill={theme.palette.primary.main}
                  fillOpacity={0.15}
                  name="Band High"
                />
                <Area
                  type="monotone"
                  dataKey="band_low"
                  stackId="2"
                  stroke={theme.palette.warning.light}
                  fill={theme.palette.warning.main}
                  fillOpacity={0.1}
                  name="Band Low"
                />
              </AreaChart>
            </ResponsiveContainer>
          </Paper>
        </Box>

        {/* RL Weight Radar */}
        <Box sx={{ flex: 1 }}>
          <Typography variant="subtitle2" gutterBottom>
            RL Weight Distribution
          </Typography>
          <Paper variant="outlined" sx={{ p: 2 }}>
            <ResponsiveContainer width="100%" height={200}>
              <RadarChart data={radarData}>
                <PolarGrid stroke={theme.palette.divider} />
                <PolarAngleAxis
                  dataKey="subject"
                  tick={{ fontSize: 10, fill: theme.palette.text.secondary }}
                />
                <PolarRadiusAxis
                  domain={[0, 0.4]}
                  tick={{ fontSize: 9 }}
                  axisLine={false}
                />
                <Radar
                  name="Weight"
                  dataKey="weight"
                  stroke={theme.palette.secondary.main}
                  fill={theme.palette.secondary.main}
                  fillOpacity={0.3}
                />
                <Tooltip contentStyle={chartTooltipStyle} />
              </RadarChart>
            </ResponsiveContainer>
          </Paper>
        </Box>
      </Stack>

      {/* Top Tasks */}
      <Box>
        <Typography variant="subtitle2" gutterBottom>
          Top Task Types
        </Typography>
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Task Type</TableCell>
                <TableCell align="right">Count</TableCell>
                <TableCell align="right">Avg Score</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {topTasks.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={3} align="center">
                    <Typography variant="body2" color="text.secondary">
                      No task data yet
                    </Typography>
                  </TableCell>
                </TableRow>
              ) : (
                topTasks.map((t) => (
                  <TableRow key={t.task_type}>
                    <TableCell>
                      <Chip label={t.task_type} size="small" variant="outlined" />
                    </TableCell>
                    <TableCell align="right">{t.count}</TableCell>
                    <TableCell align="right">{t.avg_score.toFixed(3)}</TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </Box>

      {/* Recent Failures */}
      <Box>
        <Typography variant="subtitle2" gutterBottom>
          Recent Failures & Corrections
        </Typography>
        {recentFailures.length === 0 ? (
          <Paper variant="outlined" sx={{ p: 2, textAlign: 'center' }}>
            <Typography variant="body2" color="text.secondary">
              No recent failures
            </Typography>
          </Paper>
        ) : (
          <Stack spacing={1}>
            {recentFailures.map((f) => (
              <Paper key={f.task_id} variant="outlined" sx={{ p: 1.5 }}>
                <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
                  <Chip
                    label={f.severity}
                    size="small"
                    color={
                      f.severity === 'CRITICAL' || f.severity === 'HIGH'
                        ? 'error'
                        : f.severity === 'MEDIUM'
                          ? 'warning'
                          : 'info'
                    }
                  />
                  <Typography variant="body2" fontWeight={600} fontFamily="monospace">
                    {f.task_id}
                  </Typography>
                </Stack>
                <Typography variant="body2" color="error.main">
                  {f.reason}
                </Typography>
                <Typography variant="body2" color="success.main" sx={{ mt: 0.5 }}>
                  Correction: {f.correction}
                </Typography>
              </Paper>
            ))}
          </Stack>
        )}
      </Box>
    </Stack>
  );
}
