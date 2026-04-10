import { useState, useMemo } from 'react';
import {
  Box,
  Button,
  Paper,
  Typography,
  Stack,
  Chip,
  CircularProgress,
  Alert,
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import Editor from '@monaco-editor/react';
import { useTheme } from '@mui/material/styles';
import apiClient from '@/api/axios';
import type { ToolFormData } from './index';

interface TestPanelProps {
  toolData: ToolFormData;
}

interface TestResult {
  success: boolean;
  output: unknown;
  error?: string;
  latency_ms: number;
}

function getSampleInputs(toolType: string, config: Record<string, unknown>): string {
  switch (toolType) {
    case 'Database': {
      const connStr = (config.connection_string as string) || '';
      const dbMatch = connStr.match(/\/([^/?]+)$/);
      const db = dbMatch?.[1] || 'sakila';
      if (db.toLowerCase() === 'sakila') {
        return JSON.stringify(
          {
            query:
              'SELECT a.first_name, a.last_name, COUNT(*) AS film_count FROM actor a JOIN film_actor fa ON a.actor_id = fa.actor_id GROUP BY a.actor_id ORDER BY film_count DESC LIMIT 5',
          },
          null,
          2,
        );
      }
      return JSON.stringify(
        {
          query: 'SELECT * FROM your_table LIMIT 10',
        },
        null,
        2,
      );
    }
    case 'API': {
      const method = ((config.http_method as string) || 'GET').toUpperCase();
      if (method === 'GET') {
        return JSON.stringify({ query_params: { q: 'example' } }, null, 2);
      }
      return JSON.stringify(
        {
          body: { key: 'value' },
          query_params: {},
        },
        null,
        2,
      );
    }
    case 'GitHub': {
      const action = (config.action as string) || 'search_code';
      switch (action) {
        case 'read_file':
          return JSON.stringify({ file_path: 'README.md' }, null, 2);
        case 'list_prs':
          return JSON.stringify({}, null, 2);
        case 'create_issue':
          return JSON.stringify(
            { title: 'Test Issue', body: 'Created from PMOS tool test panel.' },
            null,
            2,
          );
        case 'search_code':
          return JSON.stringify({ query: 'function' }, null, 2);
        default:
          return JSON.stringify({ query: 'fastapi stars:>1000' }, null, 2);
      }
    }
    case 'Python': {
      const hasCode = !!(config.code as string)?.includes('def execute');
      if (hasCode) {
        return JSON.stringify(
          { message: 'Hello from PMOS', numbers: [1, 2, 3, 4, 5] },
          null,
          2,
        );
      }
      // No code configured yet — provide a complete working example
      return JSON.stringify(
        {
          code: 'def execute(inputs):\n    nums = inputs.get("numbers", [])\n    return {"sum": sum(nums), "count": len(nums), "avg": sum(nums)/len(nums) if nums else 0}',
          numbers: [10, 20, 30, 40, 50],
        },
        null,
        2,
      );
    }
    case 'WebService': {
      const method = ((config.http_method as string) || 'GET').toUpperCase();
      if (method === 'GET') {
        return JSON.stringify({ query_params: { q: 'test' } }, null, 2);
      }
      return JSON.stringify({ body: { key: 'value' } }, null, 2);
    }
    default:
      return '{\n  \n}';
  }
}

function getToolTypeHint(toolType: string): string {
  switch (toolType) {
    case 'Database':
      return 'Provide a SQL query in the "query" field. Parameters can be passed as "params" array.';
    case 'API':
      return 'Pass "query_params" for GET requests, "body" for POST/PUT/PATCH, or "headers" to override.';
    case 'GitHub':
      return 'Inputs depend on the configured action (read_file, list_prs, search_code, etc.).';
    case 'Python':
      return 'Write Python code in the Configuration tab, or pass "code" directly in the inputs below. Your code must define execute(inputs) -> dict.';
    case 'WebService':
      return 'Pass "query_params", "body", or "headers" as needed for the configured endpoint.';
    default:
      return '';
  }
}

export default function TestPanel({ toolData }: TestPanelProps) {
  const theme = useTheme();
  const isDark = theme.palette.mode === 'dark';

  const defaultInputs = useMemo(
    () => getSampleInputs(toolData.tool_type, toolData.config),
    [toolData.tool_type, toolData.config],
  );

  const [inputs, setInputs] = useState(defaultInputs);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<TestResult | null>(null);

  const hint = getToolTypeHint(toolData.tool_type);

  // Map UI tool type back to backend enum
  const backendToolType: Record<string, string> = {
    API: 'API',
    Database: 'DATABASE',
    Python: 'PYTHON',
    GitHub: 'GITHUB',
    WebService: 'WEBSERVICE',
  };

  const handleRunTest = async () => {
    setRunning(true);
    setResult(null);
    const start = Date.now();

    try {
      let parsedInputs: Record<string, unknown> = {};
      try {
        parsedInputs = JSON.parse(inputs);
      } catch {
        setResult({
          success: false,
          output: null,
          error: 'Invalid JSON in inputs',
          latency_ms: Date.now() - start,
        });
        setRunning(false);
        return;
      }

      const { data } = await apiClient.post('/v1/tools/test', {
        tool_id: toolData.tool_id,
        tool_type: backendToolType[toolData.tool_type] || toolData.tool_type,
        config: toolData.config,
        inputs: parsedInputs,
        source: 'manual',
      });

      setResult({
        success: data.success ?? true,
        output: data.success === false ? null : data.output ?? data,
        error: data.error,
        latency_ms: data.latency_ms ?? Date.now() - start,
      });
    } catch (err: unknown) {
      // Extract error from axios response if available (e.g. 422 responses)
      const axiosErr = err as { response?: { data?: { error?: string; output?: unknown; latency_ms?: number; success?: boolean } } };
      const respData = axiosErr?.response?.data;
      if (respData && typeof respData === 'object' && 'error' in respData) {
        setResult({
          success: false,
          output: respData.output ?? null,
          error: respData.error || 'Tool execution failed',
          latency_ms: respData.latency_ms ?? Date.now() - start,
        });
      } else {
        const errorMsg =
          err instanceof Error ? err.message : 'Unknown error occurred';
        setResult({
          success: false,
          output: null,
          error: errorMsg,
          latency_ms: Date.now() - start,
        });
      }
    } finally {
      setRunning(false);
    }
  };

  const handleLoadSample = () => {
    setInputs(getSampleInputs(toolData.tool_type, toolData.config));
  };

  return (
    <Stack spacing={3} sx={{ maxWidth: 900 }}>
      {hint && (
        <Alert severity="info" variant="outlined" sx={{ fontSize: '0.82rem' }}>
          <strong>{toolData.tool_type} Tool:</strong> {hint}
        </Alert>
      )}

      {/* Sample Inputs */}
      <Box>
        <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 0.5 }}>
          <Typography variant="subtitle2">Test Inputs</Typography>
          <Button size="small" onClick={handleLoadSample} sx={{ textTransform: 'none' }}>
            Load Sample
          </Button>
        </Stack>
        <Paper variant="outlined" sx={{ overflow: 'hidden', borderRadius: 1 }}>
          <Editor
            height={180}
            language="json"
            theme={isDark ? 'vs-dark' : 'light'}
            value={inputs}
            onChange={(v) => setInputs(v ?? '{}')}
            options={{
              minimap: { enabled: false },
              fontSize: 13,
              lineNumbers: 'off',
              scrollBeyondLastLine: false,
              wordWrap: 'on',
              tabSize: 2,
            }}
          />
        </Paper>
      </Box>

      {/* Run Button */}
      <Box>
        <Button
          variant="contained"
          startIcon={running ? <CircularProgress size={16} color="inherit" /> : <PlayArrowIcon />}
          onClick={handleRunTest}
          disabled={running || !toolData.tool_id}
        >
          {running ? 'Running...' : 'Run Test'}
        </Button>
        {!toolData.tool_id && (
          <Typography variant="caption" color="text.secondary" sx={{ ml: 2 }}>
            Save the tool first to enable testing
          </Typography>
        )}
      </Box>

      {/* Output */}
      {result && (
        <Box>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
            <Typography variant="subtitle2">Output</Typography>
            <Chip
              label={result.success ? 'Success' : 'Error'}
              size="small"
              color={result.success ? 'success' : 'error'}
              variant="outlined"
            />
            <Chip
              label={`${result.latency_ms}ms`}
              size="small"
              variant="outlined"
            />
          </Stack>
          <Paper
            variant="outlined"
            sx={{
              overflow: 'hidden',
              borderRadius: 1,
              bgcolor: result.success
                ? (isDark ? 'rgba(0,80,0,0.1)' : 'rgba(0,128,0,0.02)')
                : (isDark ? 'rgba(80,0,0,0.1)' : 'rgba(255,0,0,0.02)'),
            }}
          >
            <Editor
              height={300}
              language="json"
              theme={isDark ? 'vs-dark' : 'light'}
              value={
                result.error
                  ? JSON.stringify({ error: result.error }, null, 2)
                  : JSON.stringify(result.output, null, 2)
              }
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
        </Box>
      )}
    </Stack>
  );
}
