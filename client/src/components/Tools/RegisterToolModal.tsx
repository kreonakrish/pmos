import { useState } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  MenuItem,
  Stack,
  Alert,
} from '@mui/material';
import { useCreateTool } from '@/api/tools';

interface Props {
  open: boolean;
  onClose: () => void;
}

const TOOL_TYPES = ['DATABASE', 'API', 'GITHUB', 'PYTHON', 'WEBSERVICE', 'FILE', 'VECTOR'] as const;
const AUTH_METHODS = ['none', 'api_key', 'bearer_token', 'basic', 'oauth2'] as const;

export default function RegisterToolModal({ open, onClose }: Props) {
  const [name, setName] = useState('');
  const [toolType, setToolType] = useState<string>('API');
  const [hostname, setHostname] = useState('');
  const [endpoint, setEndpoint] = useState('');
  const [authMethod, setAuthMethod] = useState<string>('none');
  const [description, setDescription] = useState('');

  const createTool = useCreateTool();

  const handleSubmit = () => {
    if (!name.trim()) return;

    createTool.mutate(
      {
        name: name.trim(),
        tool_type: toolType,
        hostname: hostname.trim() || undefined,
        description: description.trim() || undefined,
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
    setToolType('API');
    setHostname('');
    setEndpoint('');
    setAuthMethod('none');
    setDescription('');
  };

  const handleClose = () => {
    if (!createTool.isPending) {
      resetForm();
      onClose();
    }
  };

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>Register Tool</DialogTitle>
      <DialogContent>
        <Stack spacing={2.5} sx={{ mt: 1 }}>
          {createTool.isError && (
            <Alert severity="error">
              Failed to register tool. Please try again.
            </Alert>
          )}

          <TextField
            label="Name"
            required
            fullWidth
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={createTool.isPending}
          />

          <TextField
            label="Tool Type"
            select
            fullWidth
            value={toolType}
            onChange={(e) => setToolType(e.target.value)}
            disabled={createTool.isPending}
          >
            {TOOL_TYPES.map((t) => (
              <MenuItem key={t} value={t}>
                {t}
              </MenuItem>
            ))}
          </TextField>

          <TextField
            label="Hostname"
            fullWidth
            value={hostname}
            onChange={(e) => setHostname(e.target.value)}
            placeholder="e.g. https://api.example.com"
            disabled={createTool.isPending}
          />

          <TextField
            label="Endpoint"
            fullWidth
            value={endpoint}
            onChange={(e) => setEndpoint(e.target.value)}
            placeholder="e.g. /v1/execute"
            disabled={createTool.isPending}
          />

          <TextField
            label="Auth Method"
            select
            fullWidth
            value={authMethod}
            onChange={(e) => setAuthMethod(e.target.value)}
            disabled={createTool.isPending}
          >
            {AUTH_METHODS.map((m) => (
              <MenuItem key={m} value={m}>
                {m.replace('_', ' ')}
              </MenuItem>
            ))}
          </TextField>

          <TextField
            label="Description"
            fullWidth
            multiline
            rows={2}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            disabled={createTool.isPending}
          />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={handleClose} disabled={createTool.isPending}>
          Cancel
        </Button>
        <Button
          variant="contained"
          onClick={handleSubmit}
          disabled={!name.trim() || createTool.isPending}
        >
          {createTool.isPending ? 'Registering...' : 'Register'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
