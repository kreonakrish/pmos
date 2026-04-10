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
  Paper,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import Editor from '@monaco-editor/react';
import { useTheme } from '@mui/material/styles';

type DbType = 'MySQL' | 'PostgreSQL' | 'MongoDB' | 'Redis';

interface ParamBinding {
  name: string;
  type: string;
}

interface DatabaseConfigProps {
  config: Record<string, unknown>;
  onChange: (partial: Record<string, unknown>) => void;
}

const PARAM_TYPES = ['string', 'integer', 'float', 'boolean', 'datetime', 'json'];

export default function DatabaseConfig({ config, onChange }: DatabaseConfigProps) {
  const theme = useTheme();
  const isDark = theme.palette.mode === 'dark';

  const dbType = (config.db_type as DbType) ?? 'MySQL';
  const connectionString = (config.connection_string as string) ?? '';
  const queryTemplate = (config.query_template as string) ?? '-- Write your query here\nSELECT * FROM table_name WHERE id = :id;';
  const params = (config.parameters as ParamBinding[]) ?? [];
  const maxRows = (config.max_rows as number) ?? 1000;

  const [newParamName, setNewParamName] = useState('');
  const [newParamType, setNewParamType] = useState('string');

  const addParam = () => {
    if (!newParamName.trim()) return;
    onChange({ parameters: [...params, { name: newParamName.trim(), type: newParamType }] });
    setNewParamName('');
    setNewParamType('string');
  };

  const removeParam = (idx: number) => {
    onChange({ parameters: params.filter((_, i) => i !== idx) });
  };

  const editorLang = dbType === 'MongoDB' ? 'javascript' : 'sql';

  return (
    <Stack spacing={3} sx={{ maxWidth: 800 }}>
      {/* DB Type */}
      <FormControl size="small" sx={{ maxWidth: 200 }}>
        <InputLabel>Database Type</InputLabel>
        <Select
          value={dbType}
          label="Database Type"
          onChange={(e) => onChange({ db_type: e.target.value })}
        >
          {(['MySQL', 'PostgreSQL', 'MongoDB', 'Redis'] as DbType[]).map((t) => (
            <MenuItem key={t} value={t}>
              {t}
            </MenuItem>
          ))}
        </Select>
      </FormControl>

      {/* Connection String */}
      <TextField
        label="Connection String"
        fullWidth
        size="small"
        type="password"
        value={connectionString}
        onChange={(e) => onChange({ connection_string: e.target.value })}
        placeholder={
          dbType === 'MySQL'
            ? 'mysql://user:pass@host:3306/dbname'
            : dbType === 'PostgreSQL'
              ? 'postgresql://user:pass@host:5432/dbname'
              : dbType === 'MongoDB'
                ? 'mongodb://user:pass@host:27017/dbname'
                : 'redis://host:6379'
        }
      />

      {/* Query Template */}
      <Box>
        <Typography variant="subtitle2" gutterBottom>
          Query Template
        </Typography>
        <Paper variant="outlined" sx={{ overflow: 'hidden', borderRadius: 1 }}>
          <Editor
            height={250}
            language={editorLang}
            theme={isDark ? 'vs-dark' : 'light'}
            value={queryTemplate}
            onChange={(v) => onChange({ query_template: v ?? '' })}
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

      {/* Parameter Bindings */}
      <Box>
        <Typography variant="subtitle2" gutterBottom>
          Parameter Bindings
        </Typography>
        {params.length > 0 && (
          <Stack spacing={0.5} sx={{ mb: 1 }}>
            {params.map((p, idx) => (
              <Stack key={idx} direction="row" spacing={1} alignItems="center">
                <Typography variant="body2" sx={{ minWidth: 120, fontFamily: 'monospace' }}>
                  :{p.name}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {p.type}
                </Typography>
                <IconButton size="small" onClick={() => removeParam(idx)}>
                  <DeleteOutlineIcon fontSize="small" />
                </IconButton>
              </Stack>
            ))}
          </Stack>
        )}
        <Stack direction="row" spacing={1} alignItems="center">
          <TextField
            size="small"
            placeholder="Parameter name"
            value={newParamName}
            onChange={(e) => setNewParamName(e.target.value)}
            sx={{ flex: 1, maxWidth: 200 }}
          />
          <FormControl size="small" sx={{ minWidth: 120 }}>
            <Select value={newParamType} onChange={(e) => setNewParamType(e.target.value)}>
              {PARAM_TYPES.map((t) => (
                <MenuItem key={t} value={t}>
                  {t}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <IconButton size="small" onClick={addParam} color="primary">
            <AddIcon />
          </IconButton>
        </Stack>
      </Box>

      {/* Max Rows */}
      <TextField
        label="Max Rows Limit"
        type="number"
        size="small"
        value={maxRows}
        onChange={(e) => onChange({ max_rows: Number(e.target.value) })}
        sx={{ maxWidth: 200 }}
        inputProps={{ min: 1, max: 100000 }}
      />
    </Stack>
  );
}
