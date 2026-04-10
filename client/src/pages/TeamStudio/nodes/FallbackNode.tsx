import { memo } from 'react';
import { Handle, Position, type NodeProps } from 'reactflow';
import {
  Box,
  Typography,
  Select,
  MenuItem,
  IconButton,
  FormControl,
  useTheme,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import type { Agent } from '@/types';

export interface FallbackNodeData {
  agentId: number | null;
  agentName: string;
  primaryName: string;
  agents: Agent[];
  onAgentChange: (nodeId: string, agentId: number) => void;
  onRemove: (nodeId: string) => void;
}

function FallbackNode({ id, data }: NodeProps<FallbackNodeData>) {
  const theme = useTheme();

  return (
    <Box
      sx={{
        width: 180,
        minHeight: 80,
        bgcolor: 'background.paper',
        border: `2px dashed ${theme.palette.error.main}50`,
        borderRadius: 2,
        p: 1.5,
        display: 'flex',
        flexDirection: 'column',
        gap: 0.5,
        position: 'relative',
        background: `linear-gradient(135deg, ${theme.palette.background.paper} 0%, ${theme.palette.error.main}08 100%)`,
      }}
    >
      <Handle
        type="target"
        position={Position.Top}
        style={{
          background: theme.palette.error.main,
          width: 8,
          height: 8,
          border: `2px solid ${theme.palette.background.paper}`,
        }}
      />

      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography
            variant="caption"
            sx={{ color: 'error.main', fontWeight: 700, fontSize: '0.65rem', textTransform: 'uppercase' }}
          >
            Fallback
          </Typography>
          <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block' }} noWrap>
            for {data.primaryName || 'unknown'}
          </Typography>
        </Box>
        <IconButton
          size="small"
          onClick={() => data.onRemove(id)}
          sx={{
            width: 20,
            height: 20,
            color: 'text.secondary',
            '&:hover': { color: 'error.main' },
          }}
        >
          <CloseIcon sx={{ fontSize: 14 }} />
        </IconButton>
      </Box>

      <Typography variant="body2" sx={{ fontWeight: 600, color: 'text.primary' }} noWrap>
        {data.agentName || 'Unassigned'}
      </Typography>

      <FormControl size="small" fullWidth>
        <Select
          value={data.agentId ?? ''}
          displayEmpty
          onChange={(e) => data.onAgentChange(id, Number(e.target.value))}
          sx={{ fontSize: '0.7rem', height: 28 }}
        >
          <MenuItem value="" disabled sx={{ fontSize: '0.7rem' }}>
            Select agent
          </MenuItem>
          {data.agents.map((agent) => (
            <MenuItem key={agent.id} value={agent.id} sx={{ fontSize: '0.7rem' }}>
              {agent.name}
            </MenuItem>
          ))}
        </Select>
      </FormControl>
    </Box>
  );
}

export default memo(FallbackNode);
