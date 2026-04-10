import {
  Drawer,
  Box,
  Typography,
  Chip,
  IconButton,
  Divider,
  Stack,
  Table,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
  Skeleton,
  Paper,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import { useTheme, alpha } from '@mui/material/styles';
import {
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
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts';
import type { Agent } from '@/types';
import { useScoreHistory, useScoringWeights } from '@/api/scoring';
import { useMemoryEntries } from '@/api/memory';
import ScoreBandViz from './ScoreBandViz';

interface Props {
  agent: Agent | null;
  open: boolean;
  onClose: () => void;
}

export default function AgentDetailDrawer({ agent, open, onClose }: Props) {
  const theme = useTheme();

  const scoreHistoryQuery = useScoreHistory(agent?.id ?? 0, {
    enabled: open && !!agent,
  });
  const weightsQuery = useScoringWeights(agent?.id ?? 0, {
    enabled: open && !!agent,
  });
  const memoryQuery = useMemoryEntries(agent?.id ?? 0, undefined, {
    enabled: open && !!agent,
  });

  const scoreHistory = scoreHistoryQuery.data ?? [];
  const weights = weightsQuery.data?.weights ?? {};
  const memoryEntries = memoryQuery.data ?? [];

  // Radar data from weights
  const radarData = [
    { axis: 'Relevance', value: weights.relevance ?? 0 },
    { axis: 'Accuracy', value: weights.accuracy ?? 0 },
    { axis: 'Tool Success', value: weights.tool_success ?? 0 },
    { axis: 'Latency', value: weights.latency ?? 0 },
    { axis: 'Memory Util', value: weights.memory_util ?? 0 },
    { axis: 'Validation', value: weights.validation ?? 0 },
  ];

  // Memory tier counts
  const tierCounts = {
    SHORT_TERM: 0,
    LONG_TERM: 0,
    REASONING: 0,
    EPISODIC: 0,
  };
  memoryEntries.forEach((e) => {
    if (e.memory_tier in tierCounts) {
      tierCounts[e.memory_tier as keyof typeof tierCounts]++;
    }
  });

  const last50 = scoreHistory.slice(-50);

  return (
    <Drawer
      anchor="right"
      open={open}
      onClose={onClose}
      PaperProps={{ sx: { width: { xs: '100%', sm: 450 }, p: 0 } }}
    >
      {!agent ? (
        <Box sx={{ p: 3 }}>
          <Skeleton variant="text" width="60%" height={40} />
          <Skeleton variant="rectangular" height={200} sx={{ mt: 2 }} />
        </Box>
      ) : (
        <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'auto' }}>
          {/* Header */}
          <Box
            sx={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              p: 2,
              position: 'sticky',
              top: 0,
              bgcolor: 'background.paper',
              zIndex: 1,
              borderBottom: 1,
              borderColor: 'divider',
            }}
          >
            <Box>
              <Typography variant="h6" fontWeight={700}>
                {agent.name}
              </Typography>
              <Chip
                label={agent.status}
                color={agent.status === 'ACTIVE' ? 'success' : agent.status === 'DEGRADED' ? 'warning' : 'default'}
                size="small"
                sx={{ mt: 0.5 }}
              />
            </Box>
            <IconButton onClick={onClose} edge="end">
              <CloseIcon />
            </IconButton>
          </Box>

          <Box sx={{ p: 2, display: 'flex', flexDirection: 'column', gap: 3 }}>
            {/* Score History Chart */}
            <Paper variant="outlined" sx={{ p: 2 }}>
              <Typography variant="subtitle2" gutterBottom>
                Score History (last 50)
              </Typography>
              {scoreHistoryQuery.isLoading ? (
                <Skeleton variant="rectangular" height={180} />
              ) : last50.length === 0 ? (
                <Typography variant="body2" color="text.secondary" sx={{ py: 4, textAlign: 'center' }}>
                  No score history available
                </Typography>
              ) : (
                <ResponsiveContainer width="100%" height={180}>
                  <AreaChart data={last50}>
                    <CartesianGrid strokeDasharray="3 3" stroke={alpha(theme.palette.divider, 0.5)} />
                    <XAxis dataKey="created_at" tick={false} />
                    <YAxis domain={[0, 1]} width={30} tick={{ fontSize: 10 }} />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: theme.palette.background.paper,
                        border: `1px solid ${theme.palette.divider}`,
                      }}
                    />
                    <Area
                      dataKey="band_high"
                      stroke="none"
                      fill={alpha(theme.palette.info.main, 0.15)}
                      stackId="band"
                    />
                    <Area
                      dataKey="band_low"
                      stroke="none"
                      fill={theme.palette.background.paper}
                      stackId="band"
                    />
                    <Line
                      dataKey="score"
                      stroke={theme.palette.primary.main}
                      strokeWidth={2}
                      dot={false}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </Paper>

            {/* Band Evolution */}
            <Paper variant="outlined" sx={{ p: 2 }}>
              <Typography variant="subtitle2" gutterBottom>
                Band Evolution
              </Typography>
              {scoreHistoryQuery.isLoading ? (
                <Skeleton variant="rectangular" height={140} />
              ) : last50.length === 0 ? (
                <Typography variant="body2" color="text.secondary" sx={{ py: 3, textAlign: 'center' }}>
                  No band data available
                </Typography>
              ) : (
                <ResponsiveContainer width="100%" height={140}>
                  <AreaChart data={last50}>
                    <XAxis dataKey="created_at" tick={false} />
                    <YAxis domain={[0, 1]} width={30} tick={{ fontSize: 10 }} />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: theme.palette.background.paper,
                        border: `1px solid ${theme.palette.divider}`,
                      }}
                    />
                    <Area
                      dataKey="band_high"
                      stroke={theme.palette.warning.main}
                      fill={alpha(theme.palette.warning.main, 0.2)}
                    />
                    <Area
                      dataKey="band_low"
                      stroke={theme.palette.info.main}
                      fill={alpha(theme.palette.info.main, 0.2)}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </Paper>

            {/* RL Weight Radar */}
            <Paper variant="outlined" sx={{ p: 2 }}>
              <Typography variant="subtitle2" gutterBottom>
                RL Weight Radar
              </Typography>
              {weightsQuery.isLoading ? (
                <Skeleton variant="rectangular" height={200} />
              ) : (
                <ResponsiveContainer width="100%" height={200}>
                  <RadarChart data={radarData}>
                    <PolarGrid stroke={alpha(theme.palette.divider, 0.5)} />
                    <PolarAngleAxis
                      dataKey="axis"
                      tick={{ fontSize: 10, fill: theme.palette.text.secondary }}
                    />
                    <PolarRadiusAxis domain={[0, 1]} tick={false} />
                    <Radar
                      dataKey="value"
                      stroke={theme.palette.primary.main}
                      fill={alpha(theme.palette.primary.main, 0.3)}
                      strokeWidth={2}
                    />
                  </RadarChart>
                </ResponsiveContainer>
              )}
            </Paper>

            {/* Memory Summary */}
            <Paper variant="outlined" sx={{ p: 2 }}>
              <Typography variant="subtitle2" gutterBottom>
                Memory Summary
              </Typography>
              {memoryQuery.isLoading ? (
                <Skeleton variant="rectangular" height={40} />
              ) : (
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                  {(Object.entries(tierCounts) as [string, number][]).map(([tier, count]) => (
                    <Chip
                      key={tier}
                      label={`${tier.replace('_', ' ')}: ${count}`}
                      size="small"
                      variant="outlined"
                    />
                  ))}
                </Stack>
              )}
            </Paper>

            {/* Tools List */}
            <Paper variant="outlined" sx={{ p: 2 }}>
              <Typography variant="subtitle2" gutterBottom>
                Tools
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Tool associations loaded from agent-mgmt service.
              </Typography>
            </Paper>

            {/* Recent Executions */}
            <Paper variant="outlined" sx={{ p: 2 }}>
              <Typography variant="subtitle2" gutterBottom>
                Recent Executions
              </Typography>
              {scoreHistoryQuery.isLoading ? (
                <Skeleton variant="rectangular" height={120} />
              ) : last50.length === 0 ? (
                <Typography variant="body2" color="text.secondary" sx={{ py: 2, textAlign: 'center' }}>
                  No executions recorded
                </Typography>
              ) : (
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Time</TableCell>
                      <TableCell align="right">Score</TableCell>
                      <TableCell align="center">In Band</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {last50.slice(-10).reverse().map((entry) => (
                      <TableRow key={entry.id}>
                        <TableCell sx={{ fontSize: '0.75rem' }}>
                          {new Date(entry.created_at).toLocaleString()}
                        </TableCell>
                        <TableCell align="right">
                          <Typography
                            variant="body2"
                            fontWeight={600}
                            color={entry.score >= 0.7 ? 'success.main' : entry.score >= 0.4 ? 'warning.main' : 'error.main'}
                          >
                            {entry.score.toFixed(3)}
                          </Typography>
                        </TableCell>
                        <TableCell align="center">
                          <Box
                            sx={{
                              width: 8,
                              height: 8,
                              borderRadius: '50%',
                              bgcolor: entry.within_band ? 'success.main' : 'error.main',
                              display: 'inline-block',
                            }}
                          />
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </Paper>

            <Divider />

            {/* Current Score Band */}
            <Box>
              <Typography variant="subtitle2" gutterBottom>
                Current Score Band
              </Typography>
              <ScoreBandViz
                bandLow={agent.health_score * 0.8}
                bandHigh={Math.min(1, agent.health_score * 1.2)}
                currentScore={agent.health_score}
                height={12}
              />
            </Box>
          </Box>
        </Box>
      )}
    </Drawer>
  );
}
