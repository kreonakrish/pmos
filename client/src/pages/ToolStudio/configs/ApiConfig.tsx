import { useState } from 'react';
import {
  Box,
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Typography,
  Stack,
  IconButton,
  Table,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
  TableContainer,
  Paper,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import Editor from '@monaco-editor/react';
import { useTheme } from '@mui/material/styles';

type HttpMethod = 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH';
type AuthType = 'none' | 'api_key' | 'bearer' | 'basic' | 'oauth2';

interface HeaderPair {
  key: string;
  value: string;
}

interface ApiConfigProps {
  config: Record<string, unknown>;
  onChange: (partial: Record<string, unknown>) => void;
}

export default function ApiConfig({ config, onChange }: ApiConfigProps) {
  const theme = useTheme();
  const isDark = theme.palette.mode === 'dark';

  const baseUrl = (config.base_url as string) ?? '';
  const method = (config.http_method as HttpMethod) ?? 'GET';
  const headers = (config.headers as HeaderPair[]) ?? [];
  const authType = (config.auth_type as AuthType) ?? 'none';
  const authConfig = (config.auth_config as Record<string, string>) ?? {};
  const bodyTemplate = (config.body_template as string) ?? '{\n  \n}';
  const jsonPath = (config.response_jsonpath as string) ?? '';

  const [newHeaderKey, setNewHeaderKey] = useState('');
  const [newHeaderValue, setNewHeaderValue] = useState('');

  const addHeader = () => {
    if (!newHeaderKey.trim()) return;
    onChange({ headers: [...headers, { key: newHeaderKey.trim(), value: newHeaderValue.trim() }] });
    setNewHeaderKey('');
    setNewHeaderValue('');
  };

  const removeHeader = (idx: number) => {
    onChange({ headers: headers.filter((_, i) => i !== idx) });
  };

  const renderAuthFields = () => {
    switch (authType) {
      case 'api_key':
        return (
          <Stack spacing={2} sx={{ mt: 2 }}>
            <TextField
              label="Header Name"
              size="small"
              value={authConfig.header_name ?? 'X-API-Key'}
              onChange={(e) =>
                onChange({ auth_config: { ...authConfig, header_name: e.target.value } })
              }
              sx={{ maxWidth: 300 }}
            />
            <TextField
              label="API Key"
              size="small"
              type="password"
              value={authConfig.api_key ?? ''}
              onChange={(e) =>
                onChange({ auth_config: { ...authConfig, api_key: e.target.value } })
              }
              sx={{ maxWidth: 400 }}
            />
          </Stack>
        );
      case 'bearer':
        return (
          <TextField
            label="Bearer Token"
            size="small"
            type="password"
            fullWidth
            value={authConfig.token ?? ''}
            onChange={(e) =>
              onChange({ auth_config: { ...authConfig, token: e.target.value } })
            }
            sx={{ mt: 2, maxWidth: 500 }}
          />
        );
      case 'basic':
        return (
          <Stack direction="row" spacing={2} sx={{ mt: 2 }}>
            <TextField
              label="Username"
              size="small"
              value={authConfig.username ?? ''}
              onChange={(e) =>
                onChange({ auth_config: { ...authConfig, username: e.target.value } })
              }
            />
            <TextField
              label="Password"
              size="small"
              type="password"
              value={authConfig.password ?? ''}
              onChange={(e) =>
                onChange({ auth_config: { ...authConfig, password: e.target.value } })
              }
            />
          </Stack>
        );
      case 'oauth2':
        return (
          <Stack spacing={2} sx={{ mt: 2 }}>
            <TextField
              label="Token URL"
              size="small"
              fullWidth
              value={authConfig.token_url ?? ''}
              onChange={(e) =>
                onChange({ auth_config: { ...authConfig, token_url: e.target.value } })
              }
              sx={{ maxWidth: 500 }}
            />
            <Stack direction="row" spacing={2}>
              <TextField
                label="Client ID"
                size="small"
                value={authConfig.client_id ?? ''}
                onChange={(e) =>
                  onChange({ auth_config: { ...authConfig, client_id: e.target.value } })
                }
              />
              <TextField
                label="Client Secret"
                size="small"
                type="password"
                value={authConfig.client_secret ?? ''}
                onChange={(e) =>
                  onChange({
                    auth_config: { ...authConfig, client_secret: e.target.value },
                  })
                }
              />
            </Stack>
            <TextField
              label="Scopes (space-separated)"
              size="small"
              value={authConfig.scopes ?? ''}
              onChange={(e) =>
                onChange({ auth_config: { ...authConfig, scopes: e.target.value } })
              }
              sx={{ maxWidth: 400 }}
            />
          </Stack>
        );
      default:
        return null;
    }
  };

  return (
    <Stack spacing={3} sx={{ maxWidth: 800 }}>
      {/* Base URL */}
      <TextField
        label="Base URL"
        fullWidth
        size="small"
        value={baseUrl}
        onChange={(e) => onChange({ base_url: e.target.value })}
        placeholder="https://api.example.com/v1"
      />

      {/* HTTP Method */}
      <FormControl size="small" sx={{ maxWidth: 200 }}>
        <InputLabel>HTTP Method</InputLabel>
        <Select
          value={method}
          label="HTTP Method"
          onChange={(e) => onChange({ http_method: e.target.value })}
        >
          {(['GET', 'POST', 'PUT', 'DELETE', 'PATCH'] as HttpMethod[]).map((m) => (
            <MenuItem key={m} value={m}>
              {m}
            </MenuItem>
          ))}
        </Select>
      </FormControl>

      {/* Headers */}
      <Box>
        <Typography variant="subtitle2" gutterBottom>
          Headers
        </Typography>
        {headers.length > 0 && (
          <TableContainer component={Paper} variant="outlined" sx={{ mb: 1 }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Key</TableCell>
                  <TableCell>Value</TableCell>
                  <TableCell width={40} />
                </TableRow>
              </TableHead>
              <TableBody>
                {headers.map((h, idx) => (
                  <TableRow key={idx}>
                    <TableCell>{h.key}</TableCell>
                    <TableCell>{h.value}</TableCell>
                    <TableCell>
                      <IconButton size="small" onClick={() => removeHeader(idx)}>
                        <DeleteOutlineIcon fontSize="small" />
                      </IconButton>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
        <Stack direction="row" spacing={1} alignItems="center">
          <TextField
            size="small"
            placeholder="Key"
            value={newHeaderKey}
            onChange={(e) => setNewHeaderKey(e.target.value)}
            sx={{ flex: 1 }}
          />
          <TextField
            size="small"
            placeholder="Value"
            value={newHeaderValue}
            onChange={(e) => setNewHeaderValue(e.target.value)}
            sx={{ flex: 1 }}
          />
          <IconButton size="small" onClick={addHeader} color="primary">
            <AddIcon />
          </IconButton>
        </Stack>
      </Box>

      {/* Auth */}
      <Box>
        <FormControl size="small" sx={{ minWidth: 200 }}>
          <InputLabel>Authentication</InputLabel>
          <Select
            value={authType}
            label="Authentication"
            onChange={(e) =>
              onChange({ auth_type: e.target.value, auth_config: {} })
            }
          >
            <MenuItem value="none">None</MenuItem>
            <MenuItem value="api_key">API Key</MenuItem>
            <MenuItem value="bearer">Bearer Token</MenuItem>
            <MenuItem value="basic">Basic Auth</MenuItem>
            <MenuItem value="oauth2">OAuth2</MenuItem>
          </Select>
        </FormControl>
        {renderAuthFields()}
      </Box>

      {/* Request Body Template */}
      <Box>
        <Typography variant="subtitle2" gutterBottom>
          Request Body Template
        </Typography>
        <Paper variant="outlined" sx={{ overflow: 'hidden', borderRadius: 1 }}>
          <Editor
            height={200}
            language="json"
            theme={isDark ? 'vs-dark' : 'light'}
            value={bodyTemplate}
            onChange={(v) => onChange({ body_template: v ?? '' })}
            options={{
              minimap: { enabled: false },
              fontSize: 13,
              lineNumbers: 'on',
              scrollBeyondLastLine: false,
              wordWrap: 'on',
              tabSize: 2,
            }}
          />
        </Paper>
      </Box>

      {/* Response JSONPath */}
      <TextField
        label="Response JSONPath Expression"
        size="small"
        fullWidth
        value={jsonPath}
        onChange={(e) => onChange({ response_jsonpath: e.target.value })}
        placeholder="$.data.results[*]"
        helperText="Extract specific fields from the response using JSONPath"
        sx={{ maxWidth: 500 }}
      />
    </Stack>
  );
}
