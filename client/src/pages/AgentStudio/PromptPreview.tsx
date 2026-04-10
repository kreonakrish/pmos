import { Box, Typography, Paper } from '@mui/material';
import type { AgentFormData } from './index';

interface PromptPreviewProps {
  agentData: AgentFormData;
}

export default function PromptPreview({ agentData }: PromptPreviewProps) {
  const previewText = `== System Prompt (Assembled at Runtime) ==

You are "${agentData.name}", a specialized AI agent within the PMOS orchestration system.

== Role / Persona ==
${agentData.role || '(No role defined)'}

== Domains ==
${agentData.domains.length > 0 ? agentData.domains.join(', ') : '(No domains assigned)'}

== Provider / Model ==
${agentData.llm_provider} / ${agentData.llm_model}
Temperature: ${agentData.temperature} | Max Tokens: ${agentData.max_tokens}

== Memory Tiers (populated at runtime) ==
[SHORT_TERM] Recent context from the current conversation...
[LONG_TERM]  Persistent knowledge and learned patterns...
[REASONING]  Distilled reasoning templates and workflows...
[EPISODIC]   Historical execution episodes for few-shot examples...

== Tools Available ==
${agentData.tools.length > 0 ? agentData.tools.map((t) => `  - ${t}`).join('\n') : '  (No tools assigned)'}

== Scoring Weights ==
  Relevance:       ${agentData.scoring_weights.relevance.toFixed(2)}
  Accuracy:        ${agentData.scoring_weights.accuracy.toFixed(2)}
  Precision:       ${agentData.scoring_weights.precision.toFixed(2)}
  Latency:         ${agentData.scoring_weights.latency.toFixed(2)}
  Confidence:      ${agentData.scoring_weights.confidence.toFixed(2)}
  Knowledge Usage: ${agentData.scoring_weights.knowledge_usage.toFixed(2)}

Note: Actual prompts are assembled dynamically from all 4 memory tiers at runtime.
This preview is a static approximation of what the assembled prompt would look like.`;

  return (
    <Box>
      <Typography variant="subtitle2" gutterBottom>
        Prompt Preview (Read-Only)
      </Typography>
      <Typography variant="caption" color="text.secondary" sx={{ mb: 1, display: 'block' }}>
        Actual prompts are assembled dynamically from memory at runtime.
      </Typography>
      <Paper
        variant="outlined"
        sx={{
          p: 2,
          fontFamily: 'monospace',
          fontSize: '0.75rem',
          whiteSpace: 'pre-wrap',
          lineHeight: 1.6,
          maxHeight: 500,
          overflow: 'auto',
          bgcolor: (t) =>
            t.palette.mode === 'dark' ? 'rgba(0,0,0,0.3)' : 'rgba(0,0,0,0.02)',
        }}
      >
        {previewText}
      </Paper>
    </Box>
  );
}
