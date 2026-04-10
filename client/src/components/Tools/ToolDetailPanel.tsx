import {
  Drawer,
  Box,
  Typography,
  Chip,
  IconButton,
  Divider,
  Paper,
  Skeleton,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import { useTheme, alpha } from '@mui/material/styles';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts';
import type { Tool } from '@/types';

interface Props {
  tool: Tool | null;
  open: boolean;
  onClose: () => void;
}

const statusColor: Record<Tool['status'], 'success' | 'warning' | 'error'> = {
  ACTIVE: 'success',
  DEGRADED: 'warning',
  OFFLINE: 'error',
};

export default function ToolDetailPanel({ tool, open, onClose }: Props) {
  const theme = useTheme();

  // Synthetic health history for display (would come from real API)
  const healthHistory = tool
    ? Array.from({ length: 20 }, (_, i) => ({
        time: i,
        success_rate: Math.max(0, Math.min(1, tool.success_rate + (Math.random() - 0.5) * 0.1)),
      }))
    : [];

  return (
    <Drawer
      anchor="right"
      open={open}
      onClose={onClose}
      PaperProps={{ sx: { width: { xs: '100%', sm: 400 }, p: 0 } }}
    >
      {!tool ? (
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
                {tool.name}
              </Typography>
              <Box sx={{ display: 'flex', gap: 1, mt: 0.5 }}>
                <Chip label={tool.tool_type} size="small" variant="outlined" />
                <Chip
                  label={tool.status}
                  size="small"
                  color={statusColor[tool.status]}
                />
              </Box>
            </Box>
            <IconButton onClick={onClose} edge="end">
              <CloseIcon />
            </IconButton>
          </Box>

          <Box sx={{ p: 2, display: 'flex', flexDirection: 'column', gap: 2.5 }}>
            {/* Details */}
            {tool.description && (
              <Typography variant="body2" color="text.secondary">
                {tool.description}
              </Typography>
            )}

            <Box>
              <Typography variant="caption" color="text.secondary">
                Endpoint / Hostname
              </Typography>
              <Typography variant="body2" fontWeight={500}>
                {tool.hostname || 'N/A'}
              </Typography>
            </Box>

            <Box>
              <Typography variant="caption" color="text.secondary">
                Avg Latency
              </Typography>
              <Typography variant="body2" fontWeight={500}>
                {tool.avg_latency_ms}ms
              </Typography>
            </Box>

            <Box>
              <Typography variant="caption" color="text.secondary">
                Success Rate
              </Typography>
              <Typography variant="body2" fontWeight={500}>
                {(tool.success_rate * 100).toFixed(1)}%
              </Typography>
            </Box>

            <Divider />

            {/* Health History Chart */}
            <Paper variant="outlined" sx={{ p: 2 }}>
              <Typography variant="subtitle2" gutterBottom>
                Health History
              </Typography>
              <ResponsiveContainer width="100%" height={150}>
                <LineChart data={healthHistory}>
                  <CartesianGrid strokeDasharray="3 3" stroke={alpha(theme.palette.divider, 0.5)} />
                  <XAxis dataKey="time" tick={false} />
                  <YAxis domain={[0, 1]} width={30} tick={{ fontSize: 10 }} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: theme.palette.background.paper,
                      border: `1px solid ${theme.palette.divider}`,
                    }}
                    formatter={(value: number) => [`${(value * 100).toFixed(1)}%`, 'Success Rate']}
                  />
                  <Line
                    dataKey="success_rate"
                    stroke={theme.palette.success.main}
                    strokeWidth={2}
                    dot={false}
                    type="monotone"
                  />
                </LineChart>
              </ResponsiveContainer>
            </Paper>

            <Divider />

            {/* Assigned Agents placeholder */}
            <Box>
              <Typography variant="subtitle2" gutterBottom>
                Assigned Agents
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Agent assignments loaded from agent-mgmt service.
              </Typography>
            </Box>

            {/* Last Health Check */}
            {tool.last_health_check && (
              <Box>
                <Typography variant="caption" color="text.secondary">
                  Last Health Check
                </Typography>
                <Typography variant="body2">
                  {new Date(tool.last_health_check).toLocaleString()}
                </Typography>
              </Box>
            )}

            <Chip
              label={tool.is_dynamic ? 'Dynamic (auto-generated)' : 'Static'}
              size="small"
              color={tool.is_dynamic ? 'info' : 'default'}
              variant="outlined"
            />
          </Box>
        </Box>
      )}
    </Drawer>
  );
}
