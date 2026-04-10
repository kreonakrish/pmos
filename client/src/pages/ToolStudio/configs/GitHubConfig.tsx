import {
  Box,
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Typography,
  Stack,
} from '@mui/material';

type GitHubAction = 'read_file' | 'create_issue' | 'list_prs' | 'run_workflow' | 'search_code';

interface GitHubConfigProps {
  config: Record<string, unknown>;
  onChange: (partial: Record<string, unknown>) => void;
}

const ACTIONS: { value: GitHubAction; label: string }[] = [
  { value: 'read_file', label: 'Read File' },
  { value: 'create_issue', label: 'Create Issue' },
  { value: 'list_prs', label: 'List PRs' },
  { value: 'run_workflow', label: 'Run Workflow' },
  { value: 'search_code', label: 'Search Code' },
];

export default function GitHubConfig({ config, onChange }: GitHubConfigProps) {
  const repoUrl = (config.repo_url as string) ?? '';
  const branch = (config.branch as string) ?? 'main';
  const pat = (config.pat as string) ?? '';
  const action = (config.action as GitHubAction) ?? 'read_file';
  const actionConfig = (config.action_config as Record<string, string>) ?? {};

  const renderActionFields = () => {
    switch (action) {
      case 'read_file':
        return (
          <TextField
            label="File Path"
            size="small"
            fullWidth
            value={actionConfig.file_path ?? ''}
            onChange={(e) =>
              onChange({ action_config: { ...actionConfig, file_path: e.target.value } })
            }
            placeholder="src/main.py"
            sx={{ maxWidth: 500 }}
          />
        );
      case 'create_issue':
        return (
          <Stack spacing={2}>
            <TextField
              label="Issue Title Template"
              size="small"
              fullWidth
              value={actionConfig.title_template ?? ''}
              onChange={(e) =>
                onChange({ action_config: { ...actionConfig, title_template: e.target.value } })
              }
              placeholder="[Auto] {{summary}}"
              sx={{ maxWidth: 500 }}
            />
            <TextField
              label="Labels (comma-separated)"
              size="small"
              value={actionConfig.labels ?? ''}
              onChange={(e) =>
                onChange({ action_config: { ...actionConfig, labels: e.target.value } })
              }
              placeholder="bug, automated"
              sx={{ maxWidth: 400 }}
            />
          </Stack>
        );
      case 'list_prs':
        return (
          <Stack direction="row" spacing={2}>
            <FormControl size="small" sx={{ minWidth: 140 }}>
              <InputLabel>State</InputLabel>
              <Select
                value={actionConfig.state ?? 'open'}
                label="State"
                onChange={(e) =>
                  onChange({
                    action_config: { ...actionConfig, state: e.target.value as string },
                  })
                }
              >
                <MenuItem value="open">Open</MenuItem>
                <MenuItem value="closed">Closed</MenuItem>
                <MenuItem value="all">All</MenuItem>
              </Select>
            </FormControl>
            <TextField
              label="Max Results"
              type="number"
              size="small"
              value={actionConfig.max_results ?? '30'}
              onChange={(e) =>
                onChange({ action_config: { ...actionConfig, max_results: e.target.value } })
              }
              sx={{ width: 120 }}
            />
          </Stack>
        );
      case 'run_workflow':
        return (
          <Stack spacing={2}>
            <TextField
              label="Workflow File"
              size="small"
              value={actionConfig.workflow_file ?? ''}
              onChange={(e) =>
                onChange({ action_config: { ...actionConfig, workflow_file: e.target.value } })
              }
              placeholder="ci.yml"
              sx={{ maxWidth: 300 }}
            />
            <TextField
              label="Inputs (JSON)"
              size="small"
              multiline
              minRows={2}
              value={actionConfig.inputs_json ?? '{}'}
              onChange={(e) =>
                onChange({ action_config: { ...actionConfig, inputs_json: e.target.value } })
              }
              sx={{ maxWidth: 500 }}
            />
          </Stack>
        );
      case 'search_code':
        return (
          <TextField
            label="Search Query"
            size="small"
            fullWidth
            value={actionConfig.search_query ?? ''}
            onChange={(e) =>
              onChange({ action_config: { ...actionConfig, search_query: e.target.value } })
            }
            placeholder="function authenticate"
            sx={{ maxWidth: 500 }}
          />
        );
      default:
        return null;
    }
  };

  return (
    <Stack spacing={3} sx={{ maxWidth: 700 }}>
      {/* Repository */}
      <TextField
        label="Repository URL"
        fullWidth
        size="small"
        value={repoUrl}
        onChange={(e) => onChange({ repo_url: e.target.value })}
        placeholder="https://github.com/owner/repo"
      />

      {/* Branch */}
      <TextField
        label="Branch"
        size="small"
        value={branch}
        onChange={(e) => onChange({ branch: e.target.value })}
        sx={{ maxWidth: 250 }}
      />

      {/* PAT */}
      <TextField
        label="Personal Access Token"
        size="small"
        type="password"
        value={pat}
        onChange={(e) => onChange({ pat: e.target.value })}
        sx={{ maxWidth: 400 }}
      />

      {/* Action Selector */}
      <FormControl size="small" sx={{ maxWidth: 250 }}>
        <InputLabel>Action</InputLabel>
        <Select
          value={action}
          label="Action"
          onChange={(e) =>
            onChange({ action: e.target.value, action_config: {} })
          }
        >
          {ACTIONS.map((a) => (
            <MenuItem key={a.value} value={a.value}>
              {a.label}
            </MenuItem>
          ))}
        </Select>
      </FormControl>

      {/* Action-specific Fields */}
      <Box>
        <Typography variant="subtitle2" gutterBottom>
          Action Configuration
        </Typography>
        {renderActionFields()}
      </Box>
    </Stack>
  );
}
