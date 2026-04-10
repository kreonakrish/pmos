import { useState } from 'react';
import {
  Box,
  Button,
  Paper,
  Typography,
  Stack,
  Chip,
  CircularProgress,
  TextField,
  Alert,
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import Editor from '@monaco-editor/react';
import { useTheme } from '@mui/material/styles';
import { useTestAgent } from '@/api/agents';
import type { AgentFormData } from '../index';

interface TestAgentPanelProps {
  agentData: AgentFormData;
}

export default function TestAgentPanel({ agentData }: TestAgentPanelProps) {
  const theme = useTheme();
  const isDark = theme.palette.mode === 'dark';
  const testAgent = useTestAgent();

  const [prompt, setPrompt] = useState('');
  const [systemPrompt, setSystemPrompt] = useState(
    agentData.role
      ? `You are ${agentData.name}. ${agentData.role}`
      : `You are ${agentData.name}, an AI assistant.`,
  );
  const [result, setResult] = useState<{
    success: boolean;
    response?: string;
    error?: string;
    latency_ms: number;
    model?: string;
    tokens_used?: number;
  } | null>(null);

  const handleTest = async () => {
    if (!prompt.trim() || !agentData.agent_id) return;
    setResult(null);

    testAgent.mutate(
      {
        agentId: agentData.agent_id,
        payload: {
          prompt: prompt.trim(),
          system_prompt: systemPrompt.trim() || undefined,
          provider: agentData.llm_provider,
          model: agentData.llm_model,
          temperature: agentData.temperature,
          max_tokens: agentData.max_tokens,
        },
      },
      {
        onSuccess: (data) => {
          setResult({
            success: data.success,
            response: data.response,
            error: data.error,
            latency_ms: data.latency_ms,
            model: data.model,
            tokens_used: data.tokens_used,
          });
        },
        onError: (err) => {
          const axiosErr = err as { response?: { data?: { error?: string; latency_ms?: number } } };
          const respData = axiosErr?.response?.data;
          setResult({
            success: false,
            error: respData?.error || err.message,
            latency_ms: respData?.latency_ms || 0,
          });
        },
      },
    );
  };

  return (
    <Stack spacing={2.5} sx={{ maxWidth: 900 }}>
      <Alert severity="info" variant="outlined" sx={{ fontSize: '0.82rem' }}>
        Test <strong>{agentData.name}</strong> by sending a prompt. Uses <strong>{agentData.llm_model}</strong> with
        temperature {agentData.temperature}. Results are saved to execution history.
      </Alert>

      {/* System Prompt */}
      <Box>
        <Typography variant="subtitle2" gutterBottom>
          System Prompt
        </Typography>
        <TextField
          fullWidth
          multiline
          rows={3}
          size="small"
          value={systemPrompt}
          onChange={(e) => setSystemPrompt(e.target.value)}
          placeholder="Describe the agent's role and capabilities..."
          sx={{ fontSize: '0.85rem' }}
        />
      </Box>

      {/* User Prompt */}
      <Box>
        <Typography variant="subtitle2" gutterBottom>
          Test Prompt
        </Typography>
        <TextField
          fullWidth
          multiline
          rows={3}
          size="small"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="Enter a test message for the agent..."
          autoFocus
        />
      </Box>

      {/* Run Button */}
      <Box>
        <Button
          variant="contained"
          startIcon={testAgent.isPending ? <CircularProgress size={16} color="inherit" /> : <PlayArrowIcon />}
          onClick={handleTest}
          disabled={testAgent.isPending || !prompt.trim() || !agentData.agent_id}
        >
          {testAgent.isPending ? 'Running...' : 'Send to Agent'}
        </Button>
        {!agentData.agent_id && (
          <Typography variant="caption" color="text.secondary" sx={{ ml: 2 }}>
            Save the agent first to enable testing
          </Typography>
        )}
      </Box>

      {/* Response */}
      {result && (
        <Box>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
            <Typography variant="subtitle2">Response</Typography>
            <Chip
              label={result.success ? 'Success' : 'Error'}
              size="small"
              color={result.success ? 'success' : 'error'}
              variant="outlined"
            />
            <Chip label={`${result.latency_ms}ms`} size="small" variant="outlined" />
            {result.model && <Chip label={result.model} size="small" variant="outlined" />}
            {result.tokens_used && (
              <Chip label={`${result.tokens_used} tokens`} size="small" variant="outlined" />
            )}
          </Stack>

          {result.error && (
            <Alert severity="error" variant="outlined" sx={{ mb: 1.5, fontSize: '0.82rem' }}>
              {result.error}
            </Alert>
          )}

          {result.response && (
            <Paper
              variant="outlined"
              sx={{ overflow: 'hidden', borderRadius: 1 }}
            >
              <Editor
                height={280}
                language="markdown"
                theme={isDark ? 'vs-dark' : 'light'}
                value={result.response}
                options={{
                  readOnly: true,
                  minimap: { enabled: false },
                  fontSize: 13,
                  lineNumbers: 'off',
                  scrollBeyondLastLine: false,
                  wordWrap: 'on',
                  tabSize: 2,
                }}
              />
            </Paper>
          )}
        </Box>
      )}
    </Stack>
  );
}
