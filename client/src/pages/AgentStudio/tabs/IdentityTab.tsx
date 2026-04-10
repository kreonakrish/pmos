import { useState } from 'react';
import {
  Box,
  TextField,
  Typography,
  Stack,
  Chip,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  useTheme,
} from '@mui/material';
import type { AgentFormData } from '../index';

const AVATAR_COLORS = [
  '#5c9ce6', '#4db6ac', '#f44336', '#ff9800', '#9c27b0',
  '#e91e63', '#00bcd4', '#8bc34a', '#ff5722', '#607d8b',
  '#3f51b5', '#009688', '#ffc107', '#795548', '#2196f3',
  '#cddc39',
];

const LANGUAGES = ['Python', 'TypeScript', 'SQL', 'Any'];

const DOMAIN_SUGGESTIONS = [
  'data-analysis', 'web-scraping', 'code-generation', 'database',
  'devops', 'security', 'ml-ops', 'documentation', 'testing',
  'api-integration', 'natural-language', 'finance',
];

interface IdentityTabProps {
  agentData: AgentFormData;
  onChange: (partial: Partial<AgentFormData>) => void;
}

export default function IdentityTab({ agentData, onChange }: IdentityTabProps) {
  const theme = useTheme();
  const [domainInput, setDomainInput] = useState('');

  const handleAddDomain = (domain: string) => {
    const tag = domain.trim().toLowerCase();
    if (tag && !agentData.domains.includes(tag)) {
      onChange({ domains: [...agentData.domains, tag] });
    }
    setDomainInput('');
  };

  const handleRemoveDomain = (tag: string) => {
    onChange({ domains: agentData.domains.filter((d) => d !== tag) });
  };

  const handleDomainKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleAddDomain(domainInput);
    }
  };

  // Suggestions not yet added
  const availableSuggestions = DOMAIN_SUGGESTIONS.filter(
    (s) => !agentData.domains.includes(s),
  );

  return (
    <Stack spacing={3} sx={{ maxWidth: 700 }}>
      {/* Avatar Color Picker */}
      <Box>
        <Typography variant="subtitle2" gutterBottom>
          Avatar Color
        </Typography>
        <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
          {AVATAR_COLORS.map((color) => (
            <Box
              key={color}
              onClick={() => onChange({ avatar_color: color })}
              sx={{
                width: 32,
                height: 32,
                borderRadius: '50%',
                bgcolor: color,
                cursor: 'pointer',
                border: agentData.avatar_color === color
                  ? `3px solid ${theme.palette.text.primary}`
                  : '3px solid transparent',
                transition: 'border-color 0.15s',
                '&:hover': {
                  border: `3px solid ${theme.palette.text.secondary}`,
                },
              }}
            />
          ))}
        </Stack>
      </Box>

      {/* Role / Persona */}
      <TextField
        label="Role / Persona"
        multiline
        minRows={3}
        maxRows={8}
        fullWidth
        value={agentData.role}
        onChange={(e) => onChange({ role: e.target.value })}
        helperText="This becomes part of every prompt assembled for this agent."
      />

      {/* Domain Tags */}
      <Box>
        <Typography variant="subtitle2" gutterBottom>
          Domain Tags
        </Typography>
        <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap sx={{ mb: 1 }}>
          {agentData.domains.map((d) => (
            <Chip key={d} label={d} size="small" onDelete={() => handleRemoveDomain(d)} />
          ))}
        </Stack>
        <TextField
          size="small"
          placeholder="Add domain tag and press Enter"
          value={domainInput}
          onChange={(e) => setDomainInput(e.target.value)}
          onKeyDown={handleDomainKeyDown}
          onBlur={() => {
            if (domainInput.trim()) handleAddDomain(domainInput);
          }}
          sx={{ maxWidth: 300, mb: 1 }}
        />
        {availableSuggestions.length > 0 && (
          <Box>
            <Typography variant="caption" color="text.secondary" sx={{ mb: 0.5, display: 'block' }}>
              Suggestions:
            </Typography>
            <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
              {availableSuggestions.slice(0, 8).map((s) => (
                <Chip
                  key={s}
                  label={s}
                  size="small"
                  variant="outlined"
                  onClick={() => handleAddDomain(s)}
                  sx={{ cursor: 'pointer' }}
                />
              ))}
            </Stack>
          </Box>
        )}
      </Box>

      {/* Primary Language */}
      <FormControl size="small" sx={{ maxWidth: 200 }}>
        <InputLabel>Primary Language</InputLabel>
        <Select
          value={agentData.primary_language}
          label="Primary Language"
          onChange={(e) => onChange({ primary_language: e.target.value })}
        >
          {LANGUAGES.map((l) => (
            <MenuItem key={l} value={l}>
              {l}
            </MenuItem>
          ))}
        </Select>
      </FormControl>
    </Stack>
  );
}
