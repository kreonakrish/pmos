import { useState, useMemo, useCallback } from 'react';
import {
  Box,
  TextField,
  InputAdornment,
  Button,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Typography,
  Chip,
  Collapse,
  Menu,
  MenuItem,
  Paper,
  useTheme,
} from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import AddIcon from '@mui/icons-material/Add';
import ApiIcon from '@mui/icons-material/Api';
import StorageIcon from '@mui/icons-material/Storage';
import CodeIcon from '@mui/icons-material/Code';
import GitHubIcon from '@mui/icons-material/GitHub';
import LanguageIcon from '@mui/icons-material/Language';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import type { Tool } from '@/types';
import type { ToolType } from './index';

const TOOL_TYPE_GROUPS: { type: ToolType; label: string; icon: React.ReactElement }[] = [
  { type: 'API', label: 'API', icon: <ApiIcon fontSize="small" /> },
  { type: 'Database', label: 'Database', icon: <StorageIcon fontSize="small" /> },
  { type: 'Python', label: 'Python', icon: <CodeIcon fontSize="small" /> },
  { type: 'GitHub', label: 'GitHub', icon: <GitHubIcon fontSize="small" /> },
  { type: 'WebService', label: 'Web Service', icon: <LanguageIcon fontSize="small" /> },
];

function getToolTypeIcon(type: string): React.ReactElement {
  const match = TOOL_TYPE_GROUPS.find((g) => g.type === type);
  return match?.icon ?? <ApiIcon fontSize="small" />;
}

function getHealthColor(status: Tool['status']): string {
  switch (status) {
    case 'ACTIVE':
      return 'success.main';
    case 'DEGRADED':
      return 'warning.main';
    case 'OFFLINE':
    default:
      return 'text.disabled';
  }
}

interface ToolListProps {
  tools: Tool[];
  selectedToolId: string | null;
  isError: boolean;
  onSelect: (tool: Tool) => void;
  onCreate: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
  onRefetch: () => void;
}

export default function ToolList({
  tools,
  selectedToolId,
  onSelect,
  onCreate,
  onDuplicate,
  onDelete,
}: ToolListProps) {
  const theme = useTheme();
  const [search, setSearch] = useState('');
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  const [contextMenu, setContextMenu] = useState<{
    mouseX: number;
    mouseY: number;
    tool: Tool;
  } | null>(null);

  const filtered = useMemo(() => {
    if (!search) return tools;
    const q = search.toLowerCase();
    return tools.filter(
      (t) =>
        t.name.toLowerCase().includes(q) ||
        t.tool_type.toLowerCase().includes(q) ||
        t.description?.toLowerCase().includes(q),
    );
  }, [tools, search]);

  const grouped = useMemo(() => {
    const map = new Map<string, Tool[]>();
    for (const group of TOOL_TYPE_GROUPS) {
      map.set(group.type, []);
    }
    for (const tool of filtered) {
      const toolType = tool.tool_type?.toUpperCase() ?? '';
      const key = TOOL_TYPE_GROUPS.find((g) => g.type.toUpperCase() === toolType)?.type ?? 'API';
      const arr = map.get(key) ?? [];
      arr.push(tool);
      map.set(key, arr);
    }
    return map;
  }, [filtered]);

  const toggleGroup = useCallback((type: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  }, []);

  const handleContextMenu = useCallback((e: React.MouseEvent, tool: Tool) => {
    e.preventDefault();
    setContextMenu({ mouseX: e.clientX, mouseY: e.clientY, tool });
  }, []);

  const handleCloseContext = useCallback(() => {
    setContextMenu(null);
  }, []);

  return (
    <Paper
      elevation={0}
      sx={{
        width: 280,
        flexShrink: 0,
        display: 'flex',
        flexDirection: 'column',
        borderRight: `1px solid ${theme.palette.divider}`,
        borderRadius: 0,
        overflow: 'hidden',
      }}
    >
      {/* Search */}
      <Box sx={{ p: 1.5 }}>
        <TextField
          fullWidth
          placeholder="Search tools..."
          size="small"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <SearchIcon fontSize="small" />
              </InputAdornment>
            ),
          }}
        />
      </Box>

      {/* Create Button */}
      <Box sx={{ px: 1.5, pb: 1 }}>
        <Button
          fullWidth
          variant="contained"
          size="small"
          startIcon={<AddIcon />}
          onClick={onCreate}
        >
          Create Tool
        </Button>
      </Box>

      {/* Grouped List */}
      <Box sx={{ flex: 1, overflowY: 'auto' }}>
        {tools.length === 0 ? (
          <Box sx={{ p: 3, textAlign: 'center' }}>
            <Typography variant="body2" color="text.secondary">
              No tools registered yet
            </Typography>
          </Box>
        ) : filtered.length === 0 ? (
          <Box sx={{ p: 3, textAlign: 'center' }}>
            <Typography variant="body2" color="text.secondary">
              No tools match your search
            </Typography>
          </Box>
        ) : (
          <List dense disablePadding>
            {TOOL_TYPE_GROUPS.map((group) => {
              const items = grouped.get(group.type) ?? [];
              if (items.length === 0) return null;
              const collapsed = collapsedGroups.has(group.type);
              return (
                <Box key={group.type}>
                  <ListItemButton
                    onClick={() => toggleGroup(group.type)}
                    sx={{
                      py: 0.5,
                      px: 1.5,
                      bgcolor: theme.palette.mode === 'dark'
                        ? 'rgba(255,255,255,0.03)'
                        : 'rgba(0,0,0,0.02)',
                    }}
                  >
                    <ListItemIcon sx={{ minWidth: 28 }}>{group.icon}</ListItemIcon>
                    <ListItemText
                      primary={group.label}
                      primaryTypographyProps={{
                        variant: 'caption',
                        fontWeight: 700,
                        textTransform: 'uppercase',
                        letterSpacing: 0.5,
                      }}
                    />
                    <Chip label={items.length} size="small" sx={{ height: 20, fontSize: '0.7rem' }} />
                    {collapsed ? (
                      <ExpandMoreIcon fontSize="small" sx={{ ml: 0.5 }} />
                    ) : (
                      <ExpandLessIcon fontSize="small" sx={{ ml: 0.5 }} />
                    )}
                  </ListItemButton>
                  <Collapse in={!collapsed}>
                    {items.map((tool) => (
                      <ListItemButton
                        key={tool.id}
                        selected={selectedToolId === String(tool.id)}
                        onClick={() => onSelect(tool)}
                        onContextMenu={(e) => handleContextMenu(e, tool)}
                        sx={{
                          pl: 3,
                          pr: 1.5,
                          py: 0.75,
                          '&.Mui-selected': {
                            bgcolor:
                              theme.palette.mode === 'dark'
                                ? 'rgba(92, 156, 230, 0.12)'
                                : 'rgba(25, 118, 210, 0.08)',
                          },
                        }}
                      >
                        <ListItemIcon sx={{ minWidth: 24 }}>
                          {getToolTypeIcon(tool.tool_type)}
                        </ListItemIcon>
                        {/* Health dot */}
                        <Box
                          sx={{
                            width: 8,
                            height: 8,
                            borderRadius: '50%',
                            bgcolor: getHealthColor(tool.status),
                            mr: 1,
                            flexShrink: 0,
                          }}
                        />
                        <ListItemText
                          primary={tool.name}
                          primaryTypographyProps={{
                            variant: 'body2',
                            noWrap: true,
                            fontWeight: selectedToolId === String(tool.id) ? 600 : 400,
                          }}
                        />
                      </ListItemButton>
                    ))}
                  </Collapse>
                </Box>
              );
            })}
          </List>
        )}
      </Box>

      {/* Context Menu */}
      <Menu
        open={contextMenu !== null}
        onClose={handleCloseContext}
        anchorReference="anchorPosition"
        anchorPosition={
          contextMenu ? { top: contextMenu.mouseY, left: contextMenu.mouseX } : undefined
        }
      >
        <MenuItem
          onClick={() => {
            if (contextMenu) onSelect(contextMenu.tool);
            onDuplicate();
            handleCloseContext();
          }}
        >
          <ContentCopyIcon fontSize="small" sx={{ mr: 1 }} />
          Duplicate
        </MenuItem>
        <MenuItem
          onClick={() => {
            if (contextMenu) onSelect(contextMenu.tool);
            onDelete();
            handleCloseContext();
          }}
          sx={{ color: 'error.main' }}
        >
          <DeleteOutlineIcon fontSize="small" sx={{ mr: 1 }} />
          Delete
        </MenuItem>
      </Menu>
    </Paper>
  );
}
