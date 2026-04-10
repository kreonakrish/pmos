import { memo } from 'react';
import { Handle, Position, type NodeProps } from 'reactflow';
import {
  Box,
  Typography,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  useTheme,
} from '@mui/material';
import type { Agent } from '@/types';

export interface OrchestratorNodeData {
  agentId: number | null;
  agentName: string;
  agents: Agent[];
  onAgentChange: (nodeId: string, agentId: number) => void;
}

function OrchestratorNode({ id, data }: NodeProps<OrchestratorNodeData>) {
  const theme = useTheme();

  return (
    <Box
      sx={{
        width: 200,
        minHeight: 100,
        bgcolor: 'background.paper',
        border: `2px solid ${theme.palette.warning.main}`,
        borderRadius: 2,
        p: 1.5,
        display: 'flex',
        flexDirection: 'column',
        gap: 1,
        boxShadow: `0 0 12px ${theme.palette.warning.main}40`,
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Box
          sx={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            bgcolor: 'warning.main',
            flexShrink: 0,
          }}
        />
        <Box>
          <Typography
            variant="caption"
            sx={{ color: 'warning.main', fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.5 }}
          >
            Orchestrator
          </Typography>
          <Typography variant="body2" sx={{ fontWeight: 600, color: 'text.primary' }} noWrap>
            {data.agentName || 'Unassigned'}
          </Typography>
        </Box>
      </Box>

      <FormControl size="small" fullWidth>
        <InputLabel sx={{ fontSize: '0.75rem' }}>Agent</InputLabel>
        <Select
          value={data.agentId ?? ''}
          label="Agent"
          onChange={(e) => data.onAgentChange(id, Number(e.target.value))}
          sx={{ fontSize: '0.75rem' }}
        >
          {data.agents.map((agent) => (
            <MenuItem key={agent.id} value={agent.id} sx={{ fontSize: '0.75rem' }}>
              {agent.name}
            </MenuItem>
          ))}
        </Select>
      </FormControl>

      <Handle
        type="source"
        position={Position.Bottom}
        style={{
          background: theme.palette.warning.main,
          width: 10,
          height: 10,
          border: `2px solid ${theme.palette.background.paper}`,
        }}
      />
    </Box>
  );
}

export default memo(OrchestratorNode);
