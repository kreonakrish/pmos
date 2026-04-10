import React, { useMemo } from 'react';
import {
  Box,
  Typography,
  Tooltip,
  Paper,
  useTheme,
} from '@mui/material';
import type { TaskNode } from '@/types';

/* ---- Props ---- */

interface Props {
  nodes: TaskNode[];
  onTaskSelect: (node: TaskNode) => void;
  selectedNodeId?: string;
}

/* ---- Agent color palette ---- */

const AGENT_PALETTE = [
  '#5c9ce6',
  '#4db6ac',
  '#ffa726',
  '#ab47bc',
  '#ef5350',
  '#66bb6a',
  '#29b6f6',
  '#ec407a',
  '#8d6e63',
  '#78909c',
];

function getAgentColor(agentName: string, agentMap: Map<string, number>): string {
  if (!agentMap.has(agentName)) {
    agentMap.set(agentName, agentMap.size);
  }
  return AGENT_PALETTE[agentMap.get(agentName)! % AGENT_PALETTE.length];
}

/* ---- Component ---- */

const ExecutionGantt: React.FC<Props> = ({ nodes, onTaskSelect, selectedNodeId }) => {
  const theme = useTheme();

  const { rows, timeRange, agentColorMap } = useMemo(() => {
    const acm = new Map<string, number>();
    const sorted = [...nodes].sort(
      (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
    );

    const times = sorted.map((n) => new Date(n.created_at).getTime());
    const endTimes = sorted.map((n) => {
      const start = new Date(n.created_at).getTime();
      return start + (n.execution_time_ms ?? 0);
    });

    const minTime = times.length > 0 ? Math.min(...times) : 0;
    const maxTime = endTimes.length > 0 ? Math.max(...endTimes) : minTime + 1000;

    // Pre-allocate colors
    for (const n of sorted) {
      if (n.agent_name) getAgentColor(n.agent_name, acm);
    }

    return {
      rows: sorted,
      timeRange: { min: minTime, max: maxTime },
      agentColorMap: acm,
    };
  }, [nodes]);

  if (rows.length === 0) {
    return (
      <Box sx={{ p: 2, textAlign: 'center' }}>
        <Typography variant="body2" color="text.secondary">
          No execution data to display
        </Typography>
      </Box>
    );
  }

  const duration = timeRange.max - timeRange.min || 1;
  const ROW_HEIGHT = 32;
  const LABEL_WIDTH = 180;
  const BAR_AREA_WIDTH = 600;

  return (
    <Paper
      elevation={0}
      sx={{
        overflow: 'auto',
        bgcolor: 'background.paper',
        borderTop: `1px solid ${theme.palette.divider}`,
      }}
    >
      {/* Header */}
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          px: 2,
          py: 0.75,
          borderBottom: `1px solid ${theme.palette.divider}`,
        }}
      >
        <Box sx={{ width: LABEL_WIDTH, flexShrink: 0 }}>
          <Typography variant="caption" sx={{ fontWeight: 600, color: 'text.secondary' }}>
            Task
          </Typography>
        </Box>
        <Box sx={{ flex: 1, display: 'flex', justifyContent: 'space-between' }}>
          <Typography variant="caption" color="text.secondary">
            {new Date(timeRange.min).toLocaleTimeString()}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {new Date(timeRange.max).toLocaleTimeString()}
          </Typography>
        </Box>
      </Box>

      {/* Rows */}
      {rows.map((node) => {
        const start = new Date(node.created_at).getTime();
        const execMs = node.execution_time_ms ?? 0;
        const leftPct = ((start - timeRange.min) / duration) * 100;
        const widthPct = Math.max((execMs / duration) * 100, 1); // min 1% visible
        const color = node.agent_name
          ? getAgentColor(node.agent_name, agentColorMap)
          : theme.palette.grey[500];
        const isSelected = node.task_id === selectedNodeId;

        return (
          <Box
            key={node.task_id}
            sx={{
              display: 'flex',
              alignItems: 'center',
              height: ROW_HEIGHT,
              px: 2,
              borderBottom: `1px solid ${theme.palette.divider}`,
              bgcolor: isSelected ? theme.palette.action.selected : 'transparent',
              cursor: 'pointer',
              '&:hover': { bgcolor: theme.palette.action.hover },
            }}
            onClick={() => onTaskSelect(node)}
          >
            {/* Label */}
            <Box sx={{ width: LABEL_WIDTH, flexShrink: 0, overflow: 'hidden' }}>
              <Typography
                variant="caption"
                noWrap
                sx={{ color: 'text.primary', fontSize: '0.7rem' }}
              >
                {node.description.length > 28
                  ? node.description.slice(0, 27) + '\u2026'
                  : node.description}
              </Typography>
            </Box>

            {/* Bar area */}
            <Box
              sx={{
                flex: 1,
                position: 'relative',
                height: ROW_HEIGHT - 8,
                minWidth: BAR_AREA_WIDTH,
              }}
            >
              <Tooltip
                title={
                  <Box>
                    <Typography variant="caption" sx={{ fontWeight: 600 }}>
                      {node.description}
                    </Typography>
                    <br />
                    <Typography variant="caption">
                      Agent: {node.agent_name ?? 'N/A'}
                    </Typography>
                    <br />
                    <Typography variant="caption">
                      Duration: {execMs} ms
                    </Typography>
                    {node.score != null && (
                      <>
                        <br />
                        <Typography variant="caption">
                          Score: {node.score.toFixed(3)}
                        </Typography>
                      </>
                    )}
                  </Box>
                }
                arrow
              >
                <Box
                  sx={{
                    position: 'absolute',
                    left: `${leftPct}%`,
                    width: `${widthPct}%`,
                    top: 2,
                    bottom: 2,
                    borderRadius: 1,
                    bgcolor: color,
                    opacity: isSelected ? 1 : 0.75,
                    transition: 'opacity 0.15s',
                    '&:hover': { opacity: 1 },
                    minWidth: 6,
                  }}
                />
              </Tooltip>
            </Box>
          </Box>
        );
      })}

      {/* Legend */}
      <Box
        sx={{
          display: 'flex',
          gap: 1.5,
          px: 2,
          py: 0.75,
          borderTop: `1px solid ${theme.palette.divider}`,
          flexWrap: 'wrap',
        }}
      >
        {Array.from(agentColorMap.entries()).map(([name, idx]) => (
          <Box key={name} sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
            <Box
              sx={{
                width: 10,
                height: 10,
                borderRadius: '50%',
                bgcolor: AGENT_PALETTE[idx % AGENT_PALETTE.length],
              }}
            />
            <Typography variant="caption" color="text.secondary">
              {name}
            </Typography>
          </Box>
        ))}
      </Box>
    </Paper>
  );
};

export default ExecutionGantt;
