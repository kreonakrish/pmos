import { useState, useMemo } from 'react';
import {
  Box,
  TextField,
  InputAdornment,
  Typography,
  Stack,
  Paper,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  IconButton,
  Tooltip,
  Divider,
  useTheme,
} from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import ChevronRightIcon from '@mui/icons-material/ChevronRight';
import ChevronLeftIcon from '@mui/icons-material/ChevronLeft';
import KeyboardArrowUpIcon from '@mui/icons-material/KeyboardArrowUp';
import KeyboardArrowDownIcon from '@mui/icons-material/KeyboardArrowDown';
import ApiIcon from '@mui/icons-material/Api';
import StorageIcon from '@mui/icons-material/Storage';
import CodeIcon from '@mui/icons-material/Code';
import GitHubIcon from '@mui/icons-material/GitHub';
import LanguageIcon from '@mui/icons-material/Language';
import { useTools } from '@/api/tools';
import type { AgentFormData } from '../index';

function getToolTypeIcon(type: string) {
  switch (type) {
    case 'Database':
      return <StorageIcon fontSize="small" />;
    case 'Python':
      return <CodeIcon fontSize="small" />;
    case 'GitHub':
      return <GitHubIcon fontSize="small" />;
    case 'WebService':
      return <LanguageIcon fontSize="small" />;
    default:
      return <ApiIcon fontSize="small" />;
  }
}

function getHealthDot(status: string) {
  const color =
    status === 'ACTIVE'
      ? 'success.main'
      : status === 'DEGRADED'
        ? 'warning.main'
        : 'text.disabled';
  return (
    <Box
      component="span"
      sx={{
        width: 8,
        height: 8,
        borderRadius: '50%',
        bgcolor: color,
        display: 'inline-block',
      }}
    />
  );
}

interface ToolsTabProps {
  agentData: AgentFormData;
  onChange: (partial: Partial<AgentFormData>) => void;
}

export default function ToolsTab({ agentData, onChange }: ToolsTabProps) {
  const theme = useTheme();
  const { data: allTools } = useTools();
  const [searchAvailable, setSearchAvailable] = useState('');
  const [searchAssigned, setSearchAssigned] = useState('');

  const assignedSet = useMemo(() => new Set(agentData.tools), [agentData.tools]);

  const availableTools = useMemo(() => {
    const base = (allTools ?? []).filter((t) => !assignedSet.has(t.name));
    if (!searchAvailable) return base;
    const q = searchAvailable.toLowerCase();
    return base.filter(
      (t) => t.name.toLowerCase().includes(q) || t.tool_type.toLowerCase().includes(q),
    );
  }, [allTools, assignedSet, searchAvailable]);

  const assignedTools = useMemo(() => {
    const toolMap = new Map((allTools ?? []).map((t) => [t.name, t]));
    const base = agentData.tools.map((name) => toolMap.get(name) ?? {
      id: 0,
      tool_id: name,
      name,
      tool_type: 'API',
      status: 'OFFLINE' as const,
      avg_latency_ms: 0,
      success_rate: 0,
      is_dynamic: false,
    });
    if (!searchAssigned) return base;
    const q = searchAssigned.toLowerCase();
    return base.filter((t) => t.name.toLowerCase().includes(q));
  }, [agentData.tools, allTools, searchAssigned]);

  const addTool = (name: string) => {
    if (!assignedSet.has(name)) {
      onChange({ tools: [...agentData.tools, name] });
    }
  };

  const removeTool = (name: string) => {
    onChange({ tools: agentData.tools.filter((t) => t !== name) });
  };

  const moveUp = (idx: number) => {
    if (idx === 0) return;
    const next = [...agentData.tools];
    [next[idx - 1], next[idx]] = [next[idx], next[idx - 1]];
    onChange({ tools: next });
  };

  const moveDown = (idx: number) => {
    if (idx >= agentData.tools.length - 1) return;
    const next = [...agentData.tools];
    [next[idx], next[idx + 1]] = [next[idx + 1], next[idx]];
    onChange({ tools: next });
  };

  const panelSx = {
    flex: 1,
    display: 'flex',
    flexDirection: 'column' as const,
    overflow: 'hidden',
    border: `1px solid ${theme.palette.divider}`,
    borderRadius: 1,
    minHeight: 400,
  };

  return (
    <Stack direction="row" spacing={2} sx={{ maxWidth: 900 }}>
      {/* Available Tools */}
      <Paper variant="outlined" sx={panelSx}>
        <Box sx={{ p: 1.5, borderBottom: `1px solid ${theme.palette.divider}` }}>
          <Typography variant="subtitle2" gutterBottom>
            Available Tools
          </Typography>
          <TextField
            fullWidth
            size="small"
            placeholder="Search..."
            value={searchAvailable}
            onChange={(e) => setSearchAvailable(e.target.value)}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <SearchIcon fontSize="small" />
                </InputAdornment>
              ),
            }}
          />
        </Box>
        <Box sx={{ flex: 1, overflow: 'auto' }}>
          {availableTools.length === 0 ? (
            <Box sx={{ p: 2, textAlign: 'center' }}>
              <Typography variant="caption" color="text.secondary">
                {allTools?.length === 0
                  ? 'No tools registered'
                  : 'All tools are assigned'}
              </Typography>
            </Box>
          ) : (
            <List dense disablePadding>
              {availableTools.map((tool) => (
                <ListItem
                  key={tool.id}
                  secondaryAction={
                    <Tooltip title="Assign">
                      <IconButton
                        edge="end"
                        size="small"
                        onClick={() => addTool(tool.name)}
                        color="primary"
                      >
                        <ChevronRightIcon />
                      </IconButton>
                    </Tooltip>
                  }
                  sx={{ py: 0.5 }}
                >
                  <ListItemIcon sx={{ minWidth: 28 }}>
                    {getToolTypeIcon(tool.tool_type)}
                  </ListItemIcon>
                  <Box sx={{ mr: 1 }}>{getHealthDot(tool.status)}</Box>
                  <ListItemText
                    primary={tool.name}
                    primaryTypographyProps={{ variant: 'body2', noWrap: true }}
                  />
                </ListItem>
              ))}
            </List>
          )}
        </Box>
      </Paper>

      {/* Assigned Tools */}
      <Paper variant="outlined" sx={panelSx}>
        <Box sx={{ p: 1.5, borderBottom: `1px solid ${theme.palette.divider}` }}>
          <Typography variant="subtitle2" gutterBottom>
            Assigned Tools ({agentData.tools.length})
          </Typography>
          <TextField
            fullWidth
            size="small"
            placeholder="Search..."
            value={searchAssigned}
            onChange={(e) => setSearchAssigned(e.target.value)}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <SearchIcon fontSize="small" />
                </InputAdornment>
              ),
            }}
          />
        </Box>
        <Box sx={{ flex: 1, overflow: 'auto' }}>
          {assignedTools.length === 0 ? (
            <Box sx={{ p: 2, textAlign: 'center' }}>
              <Typography variant="caption" color="text.secondary">
                No tools assigned. Add tools from the left panel.
              </Typography>
            </Box>
          ) : (
            <List dense disablePadding>
              {assignedTools.map((tool, idx) => (
                <ListItem
                  key={tool.name}
                  secondaryAction={
                    <Stack direction="row" spacing={0}>
                      <IconButton size="small" onClick={() => moveUp(idx)} disabled={idx === 0}>
                        <KeyboardArrowUpIcon fontSize="small" />
                      </IconButton>
                      <IconButton
                        size="small"
                        onClick={() => moveDown(idx)}
                        disabled={idx >= agentData.tools.length - 1}
                      >
                        <KeyboardArrowDownIcon fontSize="small" />
                      </IconButton>
                      <Divider orientation="vertical" flexItem sx={{ mx: 0.5 }} />
                      <Tooltip title="Remove">
                        <IconButton
                          edge="end"
                          size="small"
                          onClick={() => removeTool(tool.name)}
                          color="error"
                        >
                          <ChevronLeftIcon />
                        </IconButton>
                      </Tooltip>
                    </Stack>
                  }
                  sx={{ py: 0.5 }}
                >
                  <ListItemIcon sx={{ minWidth: 28 }}>
                    {getToolTypeIcon(tool.tool_type)}
                  </ListItemIcon>
                  <Box sx={{ mr: 1 }}>{getHealthDot(tool.status)}</Box>
                  <ListItemText
                    primary={tool.name}
                    primaryTypographyProps={{ variant: 'body2', noWrap: true }}
                  />
                </ListItem>
              ))}
            </List>
          )}
        </Box>
      </Paper>
    </Stack>
  );
}
