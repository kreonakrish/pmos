import { useState } from 'react';
import {
  Box,
  Typography,
  Button,
  Paper,
  Table,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
  TableContainer,
  Chip,
  Skeleton,
  Divider,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import RefreshIcon from '@mui/icons-material/Refresh';
import type { Tool, Capability } from '@/types';
import { useTools } from '@/api/tools';
import ToolDetailPanel from '@/components/Tools/ToolDetailPanel';
import RegisterToolModal from '@/components/Tools/RegisterToolModal';

const statusDot = (status: Tool['status']) => {
  const color = status === 'ACTIVE' ? 'success.main' : status === 'DEGRADED' ? 'warning.main' : 'error.main';
  return (
    <Box
      component="span"
      sx={{
        width: 10,
        height: 10,
        borderRadius: '50%',
        bgcolor: color,
        display: 'inline-block',
        mr: 1,
      }}
    />
  );
};

export default function ToolsPage() {
  const [selectedTool, setSelectedTool] = useState<Tool | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [registerOpen, setRegisterOpen] = useState(false);

  const { data: tools, isLoading, isError, refetch } = useTools();

  // Capabilities would come from a separate hook; placeholder for now
  const capabilities: Capability[] = [];

  const handleRowClick = (tool: Tool) => {
    setSelectedTool(tool);
    setDetailOpen(true);
  };

  // Loading
  if (isLoading) {
    return (
      <Box sx={{ p: 3 }}>
        <Skeleton variant="text" width={200} height={40} />
        <Skeleton variant="rectangular" height={300} sx={{ mt: 2, borderRadius: 1 }} />
        <Skeleton variant="rectangular" height={200} sx={{ mt: 3, borderRadius: 1 }} />
      </Box>
    );
  }

  // Error
  if (isError) {
    return (
      <Box sx={{ p: 3, display: 'flex', justifyContent: 'center' }}>
        <Paper sx={{ p: 4, textAlign: 'center', maxWidth: 400 }}>
          <Typography variant="h6" color="error" gutterBottom>
            Failed to load tools
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Unable to connect to the agent-mgmt service.
          </Typography>
          <Button variant="outlined" startIcon={<RefreshIcon />} onClick={() => refetch()}>
            Retry
          </Button>
        </Paper>
      </Box>
    );
  }

  return (
    <Box sx={{ p: 3 }}>
      {/* Tools Section */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Typography variant="h5" fontWeight={700}>
          Tools
        </Typography>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => setRegisterOpen(true)}
        >
          Register Tool
        </Button>
      </Box>

      {!tools || tools.length === 0 ? (
        <Paper sx={{ p: 4, textAlign: 'center', mb: 4 }}>
          <Typography variant="body1" color="text.secondary">
            No tools registered yet. Register your first tool to get started.
          </Typography>
        </Paper>
      ) : (
        <TableContainer component={Paper} sx={{ mb: 4 }}>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>Name</TableCell>
                <TableCell>Type</TableCell>
                <TableCell>Health</TableCell>
                <TableCell>Last Check</TableCell>
                <TableCell align="right">Avg Latency</TableCell>
                <TableCell align="right">Success Rate</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {tools.map((tool) => (
                <TableRow
                  key={tool.id}
                  hover
                  sx={{ cursor: 'pointer' }}
                  onClick={() => handleRowClick(tool)}
                >
                  <TableCell>
                    <Typography variant="body2" fontWeight={600}>
                      {tool.name}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Chip label={tool.tool_type} size="small" variant="outlined" />
                  </TableCell>
                  <TableCell>
                    {statusDot(tool.status)}
                    {tool.status}
                  </TableCell>
                  <TableCell>
                    {tool.last_health_check
                      ? new Date(tool.last_health_check).toLocaleString()
                      : 'Never'}
                  </TableCell>
                  <TableCell align="right">{tool.avg_latency_ms}ms</TableCell>
                  <TableCell align="right">{(tool.success_rate * 100).toFixed(1)}%</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      <Divider sx={{ my: 3 }} />

      {/* Capability Registry */}
      <Typography variant="h6" fontWeight={700} sx={{ mb: 2 }}>
        Capability Registry
      </Typography>

      {capabilities.length === 0 ? (
        <Paper sx={{ p: 4, textAlign: 'center' }}>
          <Typography variant="body1" color="text.secondary">
            No auto-generated capabilities yet. Capabilities appear here when the meta-assembly service
            detects gaps and generates new tools, skills, or agents.
          </Typography>
        </Paper>
      ) : (
        <TableContainer component={Paper}>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>Name</TableCell>
                <TableCell>Type</TableCell>
                <TableCell>Source</TableCell>
                <TableCell align="right">Validation Score</TableCell>
                <TableCell align="right">Uses</TableCell>
                <TableCell>Created</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {capabilities.map((cap) => (
                <TableRow key={cap.id}>
                  <TableCell>
                    <Typography variant="body2" fontWeight={600}>
                      {cap.name}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Chip
                      label={cap.capability_type}
                      size="small"
                      color={
                        cap.capability_type === 'TOOL'
                          ? 'primary'
                          : cap.capability_type === 'SKILL'
                            ? 'secondary'
                            : 'info'
                      }
                    />
                  </TableCell>
                  <TableCell>
                    <Chip
                      label={cap.source}
                      size="small"
                      variant="outlined"
                      color={cap.source === 'DYNAMIC' ? 'warning' : 'default'}
                    />
                  </TableCell>
                  <TableCell align="right">
                    {cap.validation_score != null ? cap.validation_score.toFixed(3) : 'N/A'}
                  </TableCell>
                  <TableCell align="right">{cap.usage_count}</TableCell>
                  <TableCell>{new Date(cap.created_at).toLocaleDateString()}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {/* Panels and Modals */}
      <ToolDetailPanel
        tool={selectedTool}
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
      />
      <RegisterToolModal open={registerOpen} onClose={() => setRegisterOpen(false)} />
    </Box>
  );
}
