import { Box, TextField, Typography, Alert, Stack, Paper } from '@mui/material';
import Editor from '@monaco-editor/react';
import { useTheme } from '@mui/material/styles';

const DEFAULT_TEMPLATE = `def execute(inputs: dict) -> dict:
    # Your tool logic here
    return {"result": ...}
`;

const ALLOWED_IMPORTS =
  'requests, json, re, math, datetime, collections, itertools, functools, numpy, pandas';

interface PythonConfigProps {
  config: Record<string, unknown>;
  onChange: (partial: Record<string, unknown>) => void;
}

export default function PythonConfig({ config, onChange }: PythonConfigProps) {
  const theme = useTheme();
  const isDark = theme.palette.mode === 'dark';

  const code = (config.code as string) ?? DEFAULT_TEMPLATE;
  const dependencies = (config.dependencies as string) ?? '';

  return (
    <Stack spacing={3} sx={{ maxWidth: 900 }}>
      <Alert severity="info" variant="outlined">
        Allowed imports: {ALLOWED_IMPORTS}
      </Alert>

      {/* Code Editor */}
      <Box>
        <Typography variant="subtitle2" gutterBottom>
          Python Code
        </Typography>
        <Paper variant="outlined" sx={{ overflow: 'hidden', borderRadius: 1 }}>
          <Editor
            height={300}
            language="python"
            theme={isDark ? 'vs-dark' : 'light'}
            value={code}
            onChange={(v) => onChange({ code: v ?? '' })}
            options={{
              minimap: { enabled: false },
              fontSize: 13,
              lineNumbers: 'on',
              scrollBeyondLastLine: false,
              wordWrap: 'on',
              tabSize: 4,
              renderWhitespace: 'selection',
            }}
          />
        </Paper>
      </Box>

      {/* Dependencies */}
      <TextField
        label="Dependencies"
        size="small"
        fullWidth
        value={dependencies}
        onChange={(e) => onChange({ dependencies: e.target.value })}
        placeholder="requests, numpy, pandas"
        helperText="Comma-separated list of pip packages required by this tool"
        sx={{ maxWidth: 500 }}
      />
    </Stack>
  );
}
