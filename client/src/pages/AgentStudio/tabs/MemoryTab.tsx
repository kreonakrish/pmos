import { useState } from 'react';
import {
  Box,
  TextField,
  Typography,
  Stack,
  Chip,
  Button,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogContentText,
  DialogActions,
  Alert,
  CircularProgress,
} from '@mui/material';
import DeleteSweepIcon from '@mui/icons-material/DeleteSweep';
import { useMemoryStats } from '@/api/memory';
import type { AgentFormData } from '../index';

interface MemoryTabProps {
  agentData: AgentFormData;
  onChange: (partial: Partial<AgentFormData>) => void;
}

export default function MemoryTab({ agentData, onChange }: MemoryTabProps) {
  const [clearDialogOpen, setClearDialogOpen] = useState(false);
  const { data: memStats, isLoading: statsLoading } = useMemoryStats(agentData.id);

  const stats = memStats ?? { short_term: 0, long_term: 0, reasoning: 0, episodic: 0 };

  return (
    <Stack spacing={3} sx={{ maxWidth: 700 }}>
      {/* Memory Seed */}
      <Box>
        <Typography variant="subtitle2" gutterBottom>
          Memory Seed
        </Typography>
        <TextField
          multiline
          minRows={4}
          maxRows={10}
          fullWidth
          value={agentData.memory_seed}
          onChange={(e) => onChange({ memory_seed: e.target.value })}
          placeholder="Initial knowledge and context this agent should start with..."
        />
        <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>
          Format: Free-form text. This seed is stored in LONG_TERM memory on agent creation and
          becomes part of the agent's persistent knowledge base.
        </Typography>
      </Box>

      {/* Reasoning Seed */}
      <Box>
        <Typography variant="subtitle2" gutterBottom>
          Reasoning Seed
        </Typography>
        <TextField
          multiline
          minRows={3}
          maxRows={8}
          fullWidth
          value={agentData.reasoning_seed}
          onChange={(e) => onChange({ reasoning_seed: e.target.value })}
          placeholder="When analyzing data, first check for null values, then validate types, then compute statistics..."
        />
        <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>
          Provide step-by-step reasoning patterns. These are stored in the REASONING memory tier
          and used to guide the agent's problem-solving approach.
        </Typography>
      </Box>

      {/* Current Memory Stats */}
      <Box>
        <Typography variant="subtitle2" gutterBottom>
          Current Memory Stats
          {statsLoading && <CircularProgress size={12} sx={{ ml: 1 }} />}
        </Typography>
        {agentData.id ? (
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            <Chip
              label={`SHORT_TERM: ${stats.short_term}`}
              size="small"
              variant="outlined"
              color={stats.short_term > 0 ? 'info' : 'default'}
            />
            <Chip
              label={`LONG_TERM: ${stats.long_term}`}
              size="small"
              variant="outlined"
              color={stats.long_term > 0 ? 'primary' : 'default'}
            />
            <Chip
              label={`REASONING: ${stats.reasoning}`}
              size="small"
              variant="outlined"
              color={stats.reasoning > 0 ? 'secondary' : 'default'}
            />
            <Chip
              label={`EPISODIC: ${stats.episodic}`}
              size="small"
              variant="outlined"
              color={stats.episodic > 0 ? 'warning' : 'default'}
            />
          </Stack>
        ) : (
          <Alert severity="info" variant="outlined" sx={{ maxWidth: 500 }}>
            Memory stats will be available after the agent is created.
          </Alert>
        )}
        {agentData.id && (stats.short_term + stats.long_term + stats.reasoning + stats.episodic) > 0 && (
          <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
            Memory evolves automatically as the agent executes tasks. Short-term entries are promoted
            to long-term when accessed frequently (distillation).
          </Typography>
        )}
      </Box>

      {/* Clear Memory */}
      {agentData.id && (
        <Box>
          <Button
            variant="outlined"
            color="error"
            startIcon={<DeleteSweepIcon />}
            onClick={() => setClearDialogOpen(true)}
          >
            Clear All Memory
          </Button>
        </Box>
      )}

      {/* Confirmation Dialog */}
      <Dialog open={clearDialogOpen} onClose={() => setClearDialogOpen(false)}>
        <DialogTitle>Clear All Memory?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            This will permanently delete all SHORT_TERM, LONG_TERM, REASONING, and EPISODIC
            memory entries for this agent. The memory seed will be re-applied but all
            learned patterns will be lost. This action cannot be undone.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setClearDialogOpen(false)}>Cancel</Button>
          <Button
            onClick={() => {
              setClearDialogOpen(false);
            }}
            color="error"
            variant="contained"
          >
            Clear All Memory
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
