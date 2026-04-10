import {
  Box,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Typography,
  Slider,
  TextField,
  Stack,
  Paper,
} from '@mui/material';
import type { AgentFormData } from '../index';

const PROVIDERS = ['OpenAI', 'Anthropic', 'Google', 'Ollama'] as const;

const MODELS_BY_PROVIDER: Record<string, string[]> = {
  OpenAI: ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo'],
  Anthropic: ['claude-opus-4-6', 'claude-sonnet-4-6', 'claude-haiku-4-5'],
  Google: ['gemini-2.0-flash', 'gemini-2.0-pro', 'gemini-1.5-pro'],
  Ollama: ['llama3', 'mistral', 'codellama', 'mixtral'],
};

interface LLMConfigTabProps {
  agentData: AgentFormData;
  onChange: (partial: Partial<AgentFormData>) => void;
}

const SAMPLE_PROMPT = `You are a specialized data analysis agent within the PMOS orchestration system.

== Role ==
{agent.role}

== Domain Expertise ==
{agent.domains}

== Long-Term Memory ==
[Retrieved patterns from previous executions...]

== Short-Term Context ==
[Recent conversation messages...]

== Reasoning Patterns ==
[Distilled reasoning templates...]

== Task ==
Analyze the provided dataset and produce insights.

Note: Actual prompts are assembled dynamically from memory at runtime.`;

export default function LLMConfigTab({ agentData, onChange }: LLMConfigTabProps) {
  const models = MODELS_BY_PROVIDER[agentData.llm_provider] ?? [];

  const handleProviderChange = (provider: string) => {
    const newModels = MODELS_BY_PROVIDER[provider] ?? [];
    onChange({
      llm_provider: provider,
      llm_model: newModels[0] ?? '',
    });
  };

  return (
    <Stack spacing={3} sx={{ maxWidth: 700 }}>
      {/* Provider */}
      <FormControl size="small" sx={{ maxWidth: 250 }}>
        <InputLabel>Provider</InputLabel>
        <Select
          value={agentData.llm_provider}
          label="Provider"
          onChange={(e) => handleProviderChange(e.target.value)}
        >
          {PROVIDERS.map((p) => (
            <MenuItem key={p} value={p}>
              {p}
            </MenuItem>
          ))}
        </Select>
      </FormControl>

      {/* Model */}
      <FormControl size="small" sx={{ maxWidth: 300 }}>
        <InputLabel>Model</InputLabel>
        <Select
          value={agentData.llm_model}
          label="Model"
          onChange={(e) => onChange({ llm_model: e.target.value })}
        >
          {models.map((m) => (
            <MenuItem key={m} value={m}>
              {m}
            </MenuItem>
          ))}
        </Select>
      </FormControl>

      {/* Temperature */}
      <Box>
        <Typography variant="subtitle2" gutterBottom>
          Temperature: {agentData.temperature.toFixed(1)}
        </Typography>
        <Slider
          value={agentData.temperature}
          onChange={(_, v) => onChange({ temperature: v as number })}
          min={0}
          max={1}
          step={0.1}
          marks={[
            { value: 0, label: '0.0' },
            { value: 0.5, label: '0.5' },
            { value: 1, label: '1.0' },
          ]}
          sx={{ maxWidth: 400 }}
        />
      </Box>

      {/* Max Tokens */}
      <TextField
        label="Max Tokens"
        type="number"
        size="small"
        value={agentData.max_tokens}
        onChange={(e) => onChange({ max_tokens: Number(e.target.value) })}
        sx={{ maxWidth: 200 }}
        inputProps={{ min: 256, max: 128000, step: 256 }}
      />

      {/* System Prompt Preview */}
      <Box>
        <Typography variant="subtitle2" gutterBottom>
          System Prompt Preview
        </Typography>
        <Typography variant="caption" color="text.secondary" sx={{ mb: 1, display: 'block' }}>
          Actual prompts are assembled dynamically from memory tiers at runtime.
        </Typography>
        <Paper
          variant="outlined"
          sx={{
            p: 2,
            fontFamily: 'monospace',
            fontSize: '0.75rem',
            whiteSpace: 'pre-wrap',
            lineHeight: 1.6,
            maxHeight: 300,
            overflow: 'auto',
            bgcolor: (t) =>
              t.palette.mode === 'dark' ? 'rgba(0,0,0,0.3)' : 'rgba(0,0,0,0.02)',
          }}
        >
          {SAMPLE_PROMPT}
        </Paper>
      </Box>
    </Stack>
  );
}
