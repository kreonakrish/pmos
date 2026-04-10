import { useState, useMemo } from 'react';
import {
  Box,
  TextField,
  InputAdornment,
  Button,
  List,
  ListItemButton,
  ListItemAvatar,
  ListItemText,
  Avatar,
  Typography,
  Chip,
  Stack,
  Paper,
  useTheme,
} from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import AddIcon from '@mui/icons-material/Add';
import BuildIcon from '@mui/icons-material/Build';
import type { Agent } from '@/types';

function getStatusColor(status: Agent['status']): 'success' | 'warning' | 'error' | 'default' {
  switch (status) {
    case 'ACTIVE':
      return 'success';
    case 'DEGRADED':
      return 'warning';
    case 'DEPRECATED':
      return 'error';
    default:
      return 'default';
  }
}

interface AgentListProps {
  agents: Agent[];
  selectedAgentId: string | null;
  onSelect: (agent: Agent) => void;
  onCreate: () => void;
}

export default function AgentList({
  agents,
  selectedAgentId,
  onSelect,
  onCreate,
}: AgentListProps) {
  const theme = useTheme();
  const [search, setSearch] = useState('');

  const filtered = useMemo(() => {
    if (!search) return agents;
    const q = search.toLowerCase();
    return agents.filter(
      (a) =>
        a.name.toLowerCase().includes(q) ||
        a.role?.toLowerCase().includes(q) ||
        a.domains?.some((d) => d.toLowerCase().includes(q)),
    );
  }, [agents, search]);

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
          placeholder="Search agents..."
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
          Create Agent
        </Button>
      </Box>

      {/* Agent List */}
      <Box sx={{ flex: 1, overflowY: 'auto' }}>
        {agents.length === 0 ? (
          <Box sx={{ p: 3, textAlign: 'center' }}>
            <Typography variant="body2" color="text.secondary">
              No agents created yet
            </Typography>
          </Box>
        ) : filtered.length === 0 ? (
          <Box sx={{ p: 3, textAlign: 'center' }}>
            <Typography variant="body2" color="text.secondary">
              No agents match your search
            </Typography>
          </Box>
        ) : (
          <List dense disablePadding>
            {filtered.map((agent) => {
              const selected = selectedAgentId === String(agent.id);
              return (
                <ListItemButton
                  key={agent.id}
                  selected={selected}
                  onClick={() => onSelect(agent)}
                  sx={{
                    px: 1.5,
                    py: 1,
                    '&.Mui-selected': {
                      bgcolor:
                        theme.palette.mode === 'dark'
                          ? 'rgba(92, 156, 230, 0.12)'
                          : 'rgba(25, 118, 210, 0.08)',
                    },
                  }}
                >
                  <ListItemAvatar sx={{ minWidth: 40 }}>
                    <Avatar
                      sx={{
                        width: 32,
                        height: 32,
                        fontSize: '0.8rem',
                        fontWeight: 700,
                        bgcolor: 'primary.main',
                      }}
                    >
                      {agent.name.charAt(0).toUpperCase()}
                    </Avatar>
                  </ListItemAvatar>
                  <ListItemText
                    disableTypography
                    primary={
                      <Stack direction="row" spacing={0.5} alignItems="center">
                        <Typography
                          variant="body2"
                          noWrap
                          fontWeight={selected ? 600 : 400}
                          sx={{ flex: 1 }}
                        >
                          {agent.name}
                        </Typography>
                        <Chip
                          label={agent.status}
                          size="small"
                          color={getStatusColor(agent.status)}
                          sx={{ height: 18, fontSize: '0.65rem' }}
                        />
                      </Stack>
                    }
                    secondary={
                      <Stack direction="row" spacing={0.5} alignItems="center" sx={{ mt: 0.25 }}>
                        {agent.tools && agent.tools.length > 0 && (
                          <Chip
                            icon={<BuildIcon sx={{ fontSize: '0.7rem !important' }} />}
                            label={agent.tools.length}
                            size="small"
                            variant="outlined"
                            sx={{ height: 18, fontSize: '0.6rem' }}
                          />
                        )}
                        {agent.domains?.slice(0, 2).map((d) => (
                          <Chip
                            key={d}
                            label={d}
                            size="small"
                            variant="outlined"
                            sx={{ height: 18, fontSize: '0.6rem' }}
                          />
                        ))}
                      </Stack>
                    }
                  />
                </ListItemButton>
              );
            })}
          </List>
        )}
      </Box>
    </Paper>
  );
}
