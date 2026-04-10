import { memo, useState, useCallback } from 'react';
import { Handle, Position, type NodeProps } from 'reactflow';
import {
  Box,
  Typography,
  Select,
  MenuItem,
  IconButton,
  Menu,
  ListItemIcon,
  ListItemText,
  FormControl,
  Chip,
  useTheme,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import AddIcon from '@mui/icons-material/Add';
import ShieldIcon from '@mui/icons-material/Shield';
import DeleteIcon from '@mui/icons-material/Delete';
import StarIcon from '@mui/icons-material/Star';
import type { Agent } from '@/types';

export interface SpecialistNodeData {
  agentId: number | null;
  agentName: string;
  role: string;
  agents: Agent[];
  colorIndex: number;
  onAgentChange: (nodeId: string, agentId: number) => void;
  onRemove: (nodeId: string) => void;
  onAddChild: (nodeId: string) => void;
  onSetFallback: (nodeId: string) => void;
  onPromoteToOrchestrator?: (nodeId: string) => void;
}

const STRIPE_COLORS = [
  'primary.main',
  'secondary.main',
  'info.main',
  'success.main',
  'warning.main',
  'error.main',
];

function SpecialistNode({ id, data }: NodeProps<SpecialistNodeData>) {
  const theme = useTheme();
  const [contextMenu, setContextMenu] = useState<{ mouseX: number; mouseY: number } | null>(null);

  const stripeColor = STRIPE_COLORS[data.colorIndex % STRIPE_COLORS.length];

  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setContextMenu({ mouseX: e.clientX, mouseY: e.clientY });
  }, []);

  const handleCloseContext = useCallback(() => {
    setContextMenu(null);
  }, []);

  return (
    <>
      <Box
        onContextMenu={handleContextMenu}
        sx={{
          width: 180,
          minHeight: 80,
          bgcolor: 'background.paper',
          border: `1px solid ${theme.palette.divider}`,
          borderRadius: 2,
          display: 'flex',
          overflow: 'hidden',
          position: 'relative',
        }}
      >
        <Handle
          type="target"
          position={Position.Top}
          style={{
            background: theme.palette.primary.main,
            width: 8,
            height: 8,
            border: `2px solid ${theme.palette.background.paper}`,
          }}
        />

        {/* Color stripe */}
        <Box sx={{ width: 6, bgcolor: stripeColor, flexShrink: 0 }} />

        <Box sx={{ p: 1.5, flex: 1, display: 'flex', flexDirection: 'column', gap: 0.5 }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Typography variant="body2" sx={{ fontWeight: 600, color: 'text.primary' }} noWrap>
                {data.agentName || 'Unassigned'}
              </Typography>
              {data.role && (
                <Chip
                  label={data.role}
                  size="small"
                  sx={{ height: 18, fontSize: '0.65rem', mt: 0.25 }}
                />
              )}
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

        <Handle
          type="source"
          position={Position.Bottom}
          style={{
            background: theme.palette.primary.main,
            width: 8,
            height: 8,
            border: `2px solid ${theme.palette.background.paper}`,
          }}
        />
      </Box>

      <Menu
        open={contextMenu !== null}
        onClose={handleCloseContext}
        anchorReference="anchorPosition"
        anchorPosition={
          contextMenu !== null ? { top: contextMenu.mouseY, left: contextMenu.mouseX } : undefined
        }
      >
        {data.onPromoteToOrchestrator && (
          <MenuItem
            onClick={() => {
              data.onPromoteToOrchestrator!(id);
              handleCloseContext();
            }}
          >
            <ListItemIcon>
              <StarIcon fontSize="small" color="warning" />
            </ListItemIcon>
            <ListItemText>Set as Orchestrator</ListItemText>
          </MenuItem>
        )}
        <MenuItem
          onClick={() => {
            data.onAddChild(id);
            handleCloseContext();
          }}
        >
          <ListItemIcon>
            <AddIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>Add Child</ListItemText>
        </MenuItem>
        <MenuItem
          onClick={() => {
            data.onSetFallback(id);
            handleCloseContext();
          }}
        >
          <ListItemIcon>
            <ShieldIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>Set as Fallback</ListItemText>
        </MenuItem>
        <MenuItem
          onClick={() => {
            data.onRemove(id);
            handleCloseContext();
          }}
        >
          <ListItemIcon>
            <DeleteIcon fontSize="small" color="error" />
          </ListItemIcon>
          <ListItemText sx={{ color: 'error.main' }}>Remove</ListItemText>
        </MenuItem>
      </Menu>
    </>
  );
}

export default memo(SpecialistNode);
