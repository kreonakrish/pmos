import { useState, useMemo } from 'react';
import {
  Box,
  Typography,
  TextField,
  InputAdornment,
  Chip,
  Button,
  Grid,
  Skeleton,
  Paper,
  Stack,
} from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import AddIcon from '@mui/icons-material/Add';
import RefreshIcon from '@mui/icons-material/Refresh';
import type { Agent } from '@/types';
import { useAgents } from '@/api/agents';
import AgentCard from '@/components/Agents/AgentCard';
import AgentDetailDrawer from '@/components/Agents/AgentDetailDrawer';
import CreateAgentModal from '@/components/Agents/CreateAgentModal';

const STATUS_FILTERS: Agent['status'][] = ['ACTIVE', 'IDLE', 'BUSY', 'DEGRADED', 'DEPRECATED'];

export default function AgentsPage() {
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<Agent['status'] | null>(null);
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);

  const { data: agents, isLoading, isError, refetch } = useAgents();

  const filtered = useMemo(() => {
    if (!agents) return [];
    return agents.filter((a) => {
      const matchSearch =
        !search ||
        a.name.toLowerCase().includes(search.toLowerCase()) ||
        a.description?.toLowerCase().includes(search.toLowerCase());
      const matchStatus = !statusFilter || a.status === statusFilter;
      return matchSearch && matchStatus;
    });
  }, [agents, search, statusFilter]);

  const handleCardClick = (agent: Agent) => {
    setSelectedAgent(agent);
    setDrawerOpen(true);
  };

  const toggleStatus = (status: Agent['status']) => {
    setStatusFilter((prev) => (prev === status ? null : status));
  };

  // Loading state
  if (isLoading) {
    return (
      <Box sx={{ p: 3 }}>
        <Skeleton variant="text" width={200} height={40} />
        <Skeleton variant="rectangular" height={48} sx={{ mt: 2, borderRadius: 1 }} />
        <Grid container spacing={2} sx={{ mt: 2 }}>
          {Array.from({ length: 6 }).map((_, i) => (
            <Grid item xs={12} sm={6} md={4} key={i}>
              <Skeleton variant="rectangular" height={220} sx={{ borderRadius: 2 }} />
            </Grid>
          ))}
        </Grid>
      </Box>
    );
  }

  // Error state
  if (isError) {
    return (
      <Box sx={{ p: 3, display: 'flex', justifyContent: 'center' }}>
        <Paper sx={{ p: 4, textAlign: 'center', maxWidth: 400 }}>
          <Typography variant="h6" color="error" gutterBottom>
            Failed to load agents
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Unable to fetch agent data. The agent-mgmt service may be unavailable.
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
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h5" fontWeight={700}>
          Agents
        </Typography>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => setCreateOpen(true)}
        >
          Create Agent
        </Button>
      </Box>

      {/* Search + Filters */}
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} alignItems="center" sx={{ mb: 3 }}>
        <TextField
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
          sx={{ minWidth: 260 }}
        />
        <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
          {STATUS_FILTERS.map((s) => (
            <Chip
              key={s}
              label={s}
              size="small"
              variant={statusFilter === s ? 'filled' : 'outlined'}
              color={statusFilter === s ? 'primary' : 'default'}
              onClick={() => toggleStatus(s)}
              sx={{ cursor: 'pointer' }}
            />
          ))}
        </Stack>
      </Stack>

      {/* Agent Grid */}
      {filtered.length === 0 ? (
        <Paper sx={{ p: 6, textAlign: 'center' }}>
          <Typography variant="h6" color="text.secondary">
            No agents found
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
            {search || statusFilter
              ? 'Try adjusting your filters or search term.'
              : 'Get started by creating your first agent.'}
          </Typography>
        </Paper>
      ) : (
        <Grid container spacing={2}>
          {filtered.map((agent) => (
            <Grid item xs={12} sm={6} md={4} key={agent.id}>
              <AgentCard agent={agent} onClick={handleCardClick} />
            </Grid>
          ))}
        </Grid>
      )}

      {/* Drawer */}
      <AgentDetailDrawer
        agent={selectedAgent}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      />

      {/* Create Modal */}
      <CreateAgentModal open={createOpen} onClose={() => setCreateOpen(false)} />
    </Box>
  );
}
