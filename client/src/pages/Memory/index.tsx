import { useState, useMemo } from 'react';
import {
  Box,
  Typography,
  TextField,
  MenuItem,
  Tabs,
  Tab,
  InputAdornment,
  Paper,
  Table,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
  TableContainer,
  Chip,
  List,
  ListItem,
  ListItemText,
  Button,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Skeleton,
  Collapse,
  IconButton,
  LinearProgress,
} from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import DeleteIcon from '@mui/icons-material/Delete';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import RefreshIcon from '@mui/icons-material/Refresh';
import { useTheme, alpha } from '@mui/material/styles';
import type { MemoryEntry } from '@/types';
import { useAgents } from '@/api/agents';
import { useMemoryEntries } from '@/api/memory';

type Tier = 'SHORT_TERM' | 'LONG_TERM' | 'REASONING' | 'EPISODIC';
const TIERS: Tier[] = ['SHORT_TERM', 'LONG_TERM', 'REASONING', 'EPISODIC'];

function TtlBadge({ expiresAt }: { expiresAt?: string }) {
  if (!expiresAt) return <Chip label="No TTL" size="small" variant="outlined" />;
  const remaining = new Date(expiresAt).getTime() - Date.now();
  if (remaining <= 0) return <Chip label="Expired" size="small" color="error" />;
  const secs = Math.floor(remaining / 1000);
  const mins = Math.floor(secs / 60);
  const hrs = Math.floor(mins / 60);
  const display = hrs > 0 ? `${hrs}h ${mins % 60}m` : mins > 0 ? `${mins}m ${secs % 60}s` : `${secs}s`;
  return <Chip label={display} size="small" color={secs < 300 ? 'warning' : 'default'} variant="outlined" />;
}

function ShortTermPanel({ entries, loading }: { entries: MemoryEntry[]; loading: boolean }) {
  if (loading) return <Skeleton variant="rectangular" height={200} />;
  if (entries.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary" sx={{ py: 4, textAlign: 'center' }}>
        No short-term memory entries for this agent.
      </Typography>
    );
  }
  return (
    <List disablePadding>
      {entries.map((entry) => (
        <ListItem key={entry.id} divider sx={{ gap: 2 }}>
          <ListItemText
            primary={entry.content.slice(0, 120) + (entry.content.length > 120 ? '...' : '')}
            primaryTypographyProps={{ variant: 'body2' }}
            secondary={`Relevance: ${entry.relevance_score.toFixed(3)} | Access: ${entry.access_count}`}
          />
          <TtlBadge expiresAt={entry.expires_at} />
        </ListItem>
      ))}
    </List>
  );
}

function LongTermPanel({ entries, loading }: { entries: MemoryEntry[]; loading: boolean }) {
  if (loading) return <Skeleton variant="rectangular" height={200} />;
  if (entries.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary" sx={{ py: 4, textAlign: 'center' }}>
        No long-term memory entries for this agent.
      </Typography>
    );
  }
  return (
    <TableContainer>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Content</TableCell>
            <TableCell align="right" sx={{ minWidth: 130 }}>Relevance</TableCell>
            <TableCell align="right">Access Count</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {entries.map((entry) => (
            <TableRow key={entry.id}>
              <TableCell>
                <Typography variant="body2" noWrap sx={{ maxWidth: 400 }}>
                  {entry.content}
                </Typography>
              </TableCell>
              <TableCell align="right">
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, justifyContent: 'flex-end' }}>
                  <LinearProgress
                    variant="determinate"
                    value={entry.relevance_score * 100}
                    sx={{ width: 60, height: 6, borderRadius: 3 }}
                  />
                  <Typography variant="caption">{entry.relevance_score.toFixed(3)}</Typography>
                </Box>
              </TableCell>
              <TableCell align="right">{entry.access_count}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}

function ReasoningPanel({ entries, loading }: { entries: MemoryEntry[]; loading: boolean }) {
  if (loading) return <Skeleton variant="rectangular" height={200} />;
  if (entries.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary" sx={{ py: 4, textAlign: 'center' }}>
        No reasoning patterns distilled for this agent.
      </Typography>
    );
  }
  return (
    <List disablePadding>
      {entries.map((entry) => (
        <ListItem key={entry.id} divider>
          <ListItemText
            primary={entry.content}
            primaryTypographyProps={{ variant: 'body2' }}
          />
          <Box sx={{ display: 'flex', gap: 1, ml: 2, flexShrink: 0 }}>
            <Chip label={`Freq: ${entry.access_count}`} size="small" variant="outlined" />
            <Chip
              label={`Conf: ${entry.relevance_score.toFixed(2)}`}
              size="small"
              color={entry.relevance_score >= 0.7 ? 'success' : 'default'}
              variant="outlined"
            />
          </Box>
        </ListItem>
      ))}
    </List>
  );
}

function EpisodicPanel({ entries, loading }: { entries: MemoryEntry[]; loading: boolean }) {
  const [expanded, setExpanded] = useState<number | null>(null);
  const theme = useTheme();

  if (loading) return <Skeleton variant="rectangular" height={200} />;
  if (entries.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary" sx={{ py: 4, textAlign: 'center' }}>
        No episodic memories recorded for this agent.
      </Typography>
    );
  }

  return (
    <Box>
      {entries.map((entry) => {
        const meta = entry.metadata as Record<string, unknown> | undefined;
        const isOpen = expanded === entry.id;
        return (
          <Paper
            key={entry.id}
            variant="outlined"
            sx={{
              mb: 1,
              overflow: 'hidden',
              borderLeft: 3,
              borderLeftColor: entry.relevance_score >= 0.7 ? 'success.main' : 'warning.main',
            }}
          >
            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                p: 1.5,
                cursor: 'pointer',
                '&:hover': { bgcolor: alpha(theme.palette.action.hover, 0.5) },
              }}
              onClick={() => setExpanded(isOpen ? null : entry.id)}
            >
              <IconButton size="small" sx={{ mr: 1 }}>
                {isOpen ? <ExpandLessIcon /> : <ExpandMoreIcon />}
              </IconButton>
              <Box sx={{ flex: 1 }}>
                <Typography variant="body2" fontWeight={600}>
                  {entry.content.slice(0, 80)}{entry.content.length > 80 ? '...' : ''}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {new Date(entry.created_at).toLocaleString()}
                </Typography>
              </Box>
              <Chip
                label={entry.relevance_score.toFixed(3)}
                size="small"
                color={entry.relevance_score >= 0.7 ? 'success' : 'default'}
              />
            </Box>
            <Collapse in={isOpen}>
              <Box sx={{ px: 2, pb: 2, pt: 0 }}>
                <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', mb: 1 }}>
                  {entry.content}
                </Typography>
                {meta?.task_id != null && (
                  <Typography variant="caption" color="text.secondary">
                    {'Task: '}{String(meta.task_id)}
                  </Typography>
                )}
              </Box>
            </Collapse>
          </Paper>
        );
      })}
    </Box>
  );
}

export default function MemoryPage() {
  const [selectedAgentId, setSelectedAgentId] = useState<number | ''>('');
  const [tabIndex, setTabIndex] = useState(0);
  const [search, setSearch] = useState('');
  const [clearDialogOpen, setClearDialogOpen] = useState(false);

  const agentsQuery = useAgents();
  const agents = agentsQuery.data ?? [];

  const currentTier = TIERS[tabIndex];
  const memoryQuery = useMemoryEntries(
    typeof selectedAgentId === 'number' ? selectedAgentId : 0,
    currentTier,
    { enabled: typeof selectedAgentId === 'number' && selectedAgentId > 0 },
  );
  const entries = memoryQuery.data ?? [];

  // Filter by search
  const filtered = useMemo(() => {
    if (!search) return entries;
    const lower = search.toLowerCase();
    return entries.filter((e) => e.content.toLowerCase().includes(lower));
  }, [entries, search]);

  // Error state
  if (agentsQuery.isError) {
    return (
      <Box sx={{ p: 3, display: 'flex', justifyContent: 'center' }}>
        <Paper sx={{ p: 4, textAlign: 'center', maxWidth: 400 }}>
          <Typography variant="h6" color="error" gutterBottom>
            Failed to load memory data
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Unable to connect to the memory service.
          </Typography>
          <Button
            variant="outlined"
            startIcon={<RefreshIcon />}
            onClick={() => agentsQuery.refetch()}
          >
            Retry
          </Button>
        </Paper>
      </Box>
    );
  }

  const isLoading = agentsQuery.isLoading;

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" fontWeight={700} sx={{ mb: 3 }}>
        Memory Explorer
      </Typography>

      {/* Agent Selector */}
      <Box sx={{ display: 'flex', gap: 2, mb: 3, flexWrap: 'wrap', alignItems: 'center' }}>
        {isLoading ? (
          <Skeleton variant="rectangular" width={200} height={40} sx={{ borderRadius: 1 }} />
        ) : (
          <TextField
            select
            label="Select Agent"
            size="small"
            value={selectedAgentId}
            onChange={(e) => setSelectedAgentId(Number(e.target.value))}
            sx={{ minWidth: 200 }}
          >
            {agents.map((a) => (
              <MenuItem key={a.id} value={a.id}>
                {a.name}
              </MenuItem>
            ))}
          </TextField>
        )}

        <TextField
          placeholder="Search memories..."
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

        <Box sx={{ flex: 1 }} />

        <Button
          variant="outlined"
          color="error"
          startIcon={<DeleteIcon />}
          onClick={() => setClearDialogOpen(true)}
          disabled={typeof selectedAgentId !== 'number'}
          size="small"
        >
          Clear Tier
        </Button>
      </Box>

      {/* Tabs */}
      <Tabs
        value={tabIndex}
        onChange={(_, v) => setTabIndex(v)}
        sx={{ mb: 2, borderBottom: 1, borderColor: 'divider' }}
      >
        {TIERS.map((tier) => (
          <Tab key={tier} label={tier.replace('_', ' ')} />
        ))}
      </Tabs>

      {/* Tab Panels */}
      {typeof selectedAgentId !== 'number' ? (
        <Paper sx={{ p: 6, textAlign: 'center' }}>
          <Typography variant="body1" color="text.secondary">
            Select an agent to explore its memory tiers.
          </Typography>
        </Paper>
      ) : (
        <Paper sx={{ p: 2 }}>
          {currentTier === 'SHORT_TERM' && (
            <ShortTermPanel entries={filtered} loading={memoryQuery.isLoading} />
          )}
          {currentTier === 'LONG_TERM' && (
            <LongTermPanel entries={filtered} loading={memoryQuery.isLoading} />
          )}
          {currentTier === 'REASONING' && (
            <ReasoningPanel entries={filtered} loading={memoryQuery.isLoading} />
          )}
          {currentTier === 'EPISODIC' && (
            <EpisodicPanel entries={filtered} loading={memoryQuery.isLoading} />
          )}
        </Paper>
      )}

      {/* Clear Tier Confirmation Dialog */}
      <Dialog open={clearDialogOpen} onClose={() => setClearDialogOpen(false)}>
        <DialogTitle>Clear {currentTier.replace('_', ' ')} Memory?</DialogTitle>
        <DialogContent>
          <Typography variant="body2">
            This will permanently delete all {currentTier.replace('_', ' ').toLowerCase()} memory
            entries for the selected agent. This action cannot be undone.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setClearDialogOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            color="error"
            onClick={() => {
              // Would call a clear mutation here
              setClearDialogOpen(false);
            }}
          >
            Clear
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
