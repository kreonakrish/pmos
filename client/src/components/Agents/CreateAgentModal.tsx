import { useState } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  MenuItem,
  FormControlLabel,
  Switch,
  Stack,
  Alert,
} from '@mui/material';
import { useCreateAgent } from '@/api/agents';

interface Props {
  open: boolean;
  onClose: () => void;
}

const FOUNDATION_MODELS = [
  'gpt-4o',
  'gpt-4o-mini',
  'gpt-4-turbo',
  'claude-3-opus',
  'claude-3-sonnet',
  'claude-3-haiku',
];

export default function CreateAgentModal({ open, onClose }: Props) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [foundationModel, setFoundationModel] = useState('gpt-4o');
  const [domainTags, setDomainTags] = useState('');
  const [isPrimary, setIsPrimary] = useState(false);

  const createAgent = useCreateAgent();

  const handleSubmit = () => {
    if (!name.trim()) return;

    createAgent.mutate(
      {
        name: name.trim(),
        description: domainTags.trim() || description.trim() || undefined,
        foundation_model: foundationModel,
        is_primary: isPrimary,
      },
      {
        onSuccess: () => {
          resetForm();
          onClose();
        },
      },
    );
  };

  const resetForm = () => {
    setName('');
    setDescription('');
    setFoundationModel('gpt-4o');
    setDomainTags('');
    setIsPrimary(false);
  };

  const handleClose = () => {
    if (!createAgent.isPending) {
      resetForm();
      onClose();
    }
  };

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>Create Agent</DialogTitle>
      <DialogContent>
        <Stack spacing={2.5} sx={{ mt: 1 }}>
          {createAgent.isError && (
            <Alert severity="error">
              Failed to create agent. Please try again.
            </Alert>
          )}

          <TextField
            label="Name"
            required
            fullWidth
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={createAgent.isPending}
          />

          <TextField
            label="Description"
            fullWidth
            multiline
            rows={2}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            disabled={createAgent.isPending}
          />

          <TextField
            label="Foundation Model"
            select
            fullWidth
            value={foundationModel}
            onChange={(e) => setFoundationModel(e.target.value)}
            disabled={createAgent.isPending}
          >
            {FOUNDATION_MODELS.map((m) => (
              <MenuItem key={m} value={m}>
                {m}
              </MenuItem>
            ))}
          </TextField>

          <TextField
            label="Domain Tags (comma-separated)"
            fullWidth
            value={domainTags}
            onChange={(e) => setDomainTags(e.target.value)}
            placeholder="e.g. finance, analytics, code-gen"
            disabled={createAgent.isPending}
          />

          <FormControlLabel
            control={
              <Switch
                checked={isPrimary}
                onChange={(e) => setIsPrimary(e.target.checked)}
                disabled={createAgent.isPending}
              />
            }
            label="Primary Agent"
          />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={handleClose} disabled={createAgent.isPending}>
          Cancel
        </Button>
        <Button
          variant="contained"
          onClick={handleSubmit}
          disabled={!name.trim() || createAgent.isPending}
        >
          {createAgent.isPending ? 'Creating...' : 'Create'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
