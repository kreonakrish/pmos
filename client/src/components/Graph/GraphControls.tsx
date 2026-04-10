import React from 'react';
import {
  Box,
  IconButton,
  Chip,
  Slider,
  Typography,
  Tooltip,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  useTheme,
} from '@mui/material';
import ZoomInIcon from '@mui/icons-material/ZoomIn';
import ZoomOutIcon from '@mui/icons-material/ZoomOut';
import FitScreenIcon from '@mui/icons-material/FitScreen';
import RefreshIcon from '@mui/icons-material/Refresh';
import ClearIcon from '@mui/icons-material/Clear';
import type { TaskNodeStatus } from '@/types';

const ALL_STATUSES: TaskNodeStatus[] = [
  'PENDING', 'RUNNING', 'SUCCESS', 'FAILED', 'CORRECTING', 'SKIPPED',
];

function useStatusChipColor(status: TaskNodeStatus) {
  const theme = useTheme();
  const map: Record<TaskNodeStatus, string> = {
    PENDING: theme.palette.grey[500],
    RUNNING: theme.palette.info.main,
    SUCCESS: theme.palette.success.main,
    FAILED: theme.palette.error.main,
    CORRECTING: theme.palette.warning.main,
    SKIPPED: theme.palette.grey[400],
  };
  return map[status];
}

interface Props {
  statusFilter: TaskNodeStatus[];
  onStatusFilterChange: (statuses: TaskNodeStatus[]) => void;
  maxDepth: number;
  onMaxDepthChange: (depth: number) => void;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onFitToScreen: () => void;
  onRefresh: () => void;
  // New filters
  teams?: Array<{ team_id: string; name: string }>;
  selectedTeamId: string;
  onTeamChange: (teamId: string) => void;
  agents?: string[];
  selectedAgent: string;
  onAgentChange: (agent: string) => void;
  graphIds?: string[];
  selectedGraphId: string;
  onGraphIdChange: (graphId: string) => void;
  nodeCount?: number;
  edgeCount?: number;
}

const StatusChip: React.FC<{
  status: TaskNodeStatus;
  selected: boolean;
  onClick: () => void;
}> = ({ status, selected, onClick }) => {
  const color = useStatusChipColor(status);
  return (
    <Chip
      label={status}
      size="small"
      onClick={onClick}
      variant={selected ? 'filled' : 'outlined'}
      sx={{
        bgcolor: selected ? color : 'transparent',
        color: selected ? '#fff' : 'text.primary',
        borderColor: color,
        fontWeight: 500,
        fontSize: '0.7rem',
        '&:hover': { bgcolor: selected ? color : `${color}22` },
      }}
    />
  );
};

const GraphControls: React.FC<Props> = ({
  statusFilter,
  onStatusFilterChange,
  maxDepth,
  onMaxDepthChange,
  onZoomIn,
  onZoomOut,
  onFitToScreen,
  onRefresh,
  teams = [],
  selectedTeamId,
  onTeamChange,
  agents = [],
  selectedAgent,
  onAgentChange,
  graphIds = [],
  selectedGraphId,
  onGraphIdChange,
  nodeCount = 0,
  edgeCount = 0,
}) => {
  const toggleStatus = (status: TaskNodeStatus) => {
    if (statusFilter.includes(status)) {
      onStatusFilterChange(statusFilter.filter((s) => s !== status));
    } else {
      onStatusFilterChange([...statusFilter, status]);
    }
  };

  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        gap: 1.5,
        px: 2,
        py: 1,
        borderBottom: 1,
        borderColor: 'divider',
        bgcolor: 'background.paper',
        flexWrap: 'wrap',
        flexShrink: 0,
      }}
    >
      {/* Zoom controls */}
      <Box sx={{ display: 'flex', gap: 0.5 }}>
        <Tooltip title="Zoom In"><IconButton size="small" onClick={onZoomIn}><ZoomInIcon fontSize="small" /></IconButton></Tooltip>
        <Tooltip title="Zoom Out"><IconButton size="small" onClick={onZoomOut}><ZoomOutIcon fontSize="small" /></IconButton></Tooltip>
        <Tooltip title="Fit to Screen"><IconButton size="small" onClick={onFitToScreen}><FitScreenIcon fontSize="small" /></IconButton></Tooltip>
        <Tooltip title="Refresh"><IconButton size="small" onClick={onRefresh}><RefreshIcon fontSize="small" /></IconButton></Tooltip>
      </Box>

      {/* Team filter */}
      {teams.length > 0 && (
        <FormControl size="small" sx={{ minWidth: 150 }}>
          <InputLabel sx={{ fontSize: '0.75rem' }}>Team</InputLabel>
          <Select
            value={selectedTeamId}
            label="Team"
            onChange={(e) => onTeamChange(e.target.value)}
            sx={{ fontSize: '0.75rem', height: 32 }}
          >
            <MenuItem value="" sx={{ fontSize: '0.75rem' }}><em>All Teams</em></MenuItem>
            {teams.map((t) => (
              <MenuItem key={t.team_id} value={t.team_id} sx={{ fontSize: '0.75rem' }}>{t.name}</MenuItem>
            ))}
          </Select>
        </FormControl>
      )}

      {/* Agent filter */}
      {agents.length > 0 && (
        <FormControl size="small" sx={{ minWidth: 140 }}>
          <InputLabel sx={{ fontSize: '0.75rem' }}>Agent</InputLabel>
          <Select
            value={selectedAgent}
            label="Agent"
            onChange={(e) => onAgentChange(e.target.value)}
            sx={{ fontSize: '0.75rem', height: 32 }}
          >
            <MenuItem value="" sx={{ fontSize: '0.75rem' }}><em>All Agents</em></MenuItem>
            {agents.map((a) => (
              <MenuItem key={a} value={a} sx={{ fontSize: '0.75rem' }}>{a}</MenuItem>
            ))}
          </Select>
        </FormControl>
      )}

      {/* Graph/Conversation filter */}
      {graphIds.length > 1 && (
        <FormControl size="small" sx={{ minWidth: 160 }}>
          <InputLabel sx={{ fontSize: '0.75rem' }}>Graph</InputLabel>
          <Select
            value={selectedGraphId}
            label="Graph"
            onChange={(e) => onGraphIdChange(e.target.value)}
            sx={{ fontSize: '0.75rem', height: 32 }}
          >
            <MenuItem value="" sx={{ fontSize: '0.75rem' }}><em>All Graphs</em></MenuItem>
            {graphIds.map((g) => (
              <MenuItem key={g} value={g} sx={{ fontSize: '0.75rem' }}>{g.slice(0, 8)}...</MenuItem>
            ))}
          </Select>
        </FormControl>
      )}

      {/* Status filter chips */}
      <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', alignItems: 'center' }}>
        {ALL_STATUSES.map((s) => (
          <StatusChip key={s} status={s} selected={statusFilter.includes(s)} onClick={() => toggleStatus(s)} />
        ))}
      </Box>

      {/* Depth slider */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 140 }}>
        <Typography variant="caption" sx={{ color: 'text.secondary', whiteSpace: 'nowrap' }}>
          Depth: {maxDepth}
        </Typography>
        <Slider
          value={maxDepth}
          min={1}
          max={10}
          step={1}
          onChange={(_e, val) => onMaxDepthChange(val as number)}
          size="small"
          sx={{ width: 80 }}
        />
      </Box>

      {/* Clear filters */}
      {(selectedAgent || selectedGraphId || selectedTeamId) && (
        <Tooltip title="Clear Filters">
          <IconButton size="small" onClick={() => { onTeamChange(''); onAgentChange(''); onGraphIdChange(''); }}>
            <ClearIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      )}

      {/* Node/edge count */}
      <Typography variant="caption" color="text.secondary" sx={{ ml: 'auto' }}>
        {nodeCount} nodes, {edgeCount} edges
      </Typography>
    </Box>
  );
};

export default GraphControls;
