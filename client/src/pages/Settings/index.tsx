import { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Box,
  Typography,
  Paper,
  Table,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
  TableContainer,
  TextField,
  MenuItem,
  Slider,
  Button,
  Skeleton,
  Stack,
  Alert,
  Tabs,
  Tab,
} from '@mui/material';
import SaveIcon from '@mui/icons-material/Save';
import RefreshIcon from '@mui/icons-material/Refresh';
import { useHealth } from '@/api/health';
import MyAccessTab from './MyAccessTab';
import ChangePasswordTab from './ChangePasswordTab';
import { useAuthStore } from '@/store/authStore';

const SERVICES = [
  { name: 'Gateway', key: 'gateway', port: 4000 },
  { name: 'Agent Management', key: 'agent-mgmt', port: 4001 },
  { name: 'Orchestrator', key: 'orchestrator', port: 8000 },
  { name: 'Memory', key: 'memory', port: 8001 },
  { name: 'RAG', key: 'rag', port: 8002 },
  { name: 'Scoring', key: 'scoring', port: 8003 },
  { name: 'Meta-Assembly', key: 'meta-assembly', port: 8004 },
];

const LLM_MODELS = [
  'gpt-4o',
  'gpt-4o-mini',
  'gpt-4-turbo',
  'claude-3-opus',
  'claude-3-sonnet',
  'claude-3-haiku',
];

const RETRY_STRATEGIES = ['LINEAR', 'EXPONENTIAL', 'FIBONACCI'] as const;

function statusDot(status: string) {
  const color =
    status === 'ok' ? 'success.main' : status === 'degraded' ? 'warning.main' : 'error.main';
  return (
    <Box
      component="span"
      sx={{
        width: 10,
        height: 10,
        borderRadius: '50%',
        bgcolor: color,
        display: 'inline-block',
        mr: 1,
      }}
    />
  );
}

type TabKey = 'system' | 'access' | 'password';

export default function SettingsPage() {
  const healthQuery = useHealth();
  const healthData = healthQuery.data;
  const [searchParams, setSearchParams] = useSearchParams();
  const canSeeSystem = useAuthStore((s) => s.has('settings.read'));
  const initialTab = (searchParams.get('tab') as TabKey) || (canSeeSystem ? 'system' : 'access');
  const [tab, setTab] = useState<TabKey>(initialTab);
  useEffect(() => {
    const current = (searchParams.get('tab') as TabKey) || null;
    if (current !== tab) {
      const next = new URLSearchParams(searchParams);
      next.set('tab', tab);
      setSearchParams(next, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  // LLM config
  const [model, setModel] = useState('gpt-4o');
  const [temperature, setTemperature] = useState(0.7);
  const [maxTokens, setMaxTokens] = useState(4096);

  // Retry config
  const [retryStrategy, setRetryStrategy] = useState<string>('EXPONENTIAL');
  const [maxAttempts, setMaxAttempts] = useState(3);

  // Rate limiting
  const [rpm, setRpm] = useState(60);

  // Save status
  const [saved, setSaved] = useState(false);

  const handleSave = () => {
    // Would call agent-mgmt API to persist settings
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  };

  return (
    <Box sx={{ p: 3, maxWidth: 900, mx: 'auto' }}>
      <Typography variant="h5" fontWeight={700} sx={{ mb: 2 }}>
        Settings
      </Typography>

      <Tabs value={tab} onChange={(_, v: TabKey) => setTab(v)} sx={{ mb: 3, borderBottom: 1, borderColor: 'divider' }}>
        {canSeeSystem && <Tab value="system" label="System" />}
        <Tab value="access" label="My Access" />
        <Tab value="password" label="Change Password" />
      </Tabs>

      {tab === 'access'   && <MyAccessTab />}
      {tab === 'password' && <ChangePasswordTab />}

      {tab === 'system' && canSeeSystem && <>
      {saved && (
        <Alert severity="success" sx={{ mb: 2 }}>
          Settings saved successfully.
        </Alert>
      )}

      {/* Section 1: Service Status */}
      <Paper sx={{ p: 2, mb: 3 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
          <Typography variant="h6" fontWeight={600}>
            Service Status
          </Typography>
          <Button
            size="small"
            startIcon={<RefreshIcon />}
            onClick={() => healthQuery.refetch()}
            disabled={healthQuery.isRefetching}
          >
            Refresh
          </Button>
        </Box>

        {healthQuery.isLoading ? (
          <Skeleton variant="rectangular" height={280} sx={{ borderRadius: 1 }} />
        ) : healthQuery.isError ? (
          <Box sx={{ py: 3, textAlign: 'center' }}>
            <Typography variant="body2" color="text.secondary" gutterBottom>
              Unable to reach health endpoint.
            </Typography>
            <Button
              variant="outlined"
              size="small"
              startIcon={<RefreshIcon />}
              onClick={() => healthQuery.refetch()}
            >
              Retry
            </Button>
          </Box>
        ) : (
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Service</TableCell>
                  <TableCell>Port</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell align="right">Latency</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {SERVICES.map((svc) => {
                  const info = healthData?.services?.[svc.key];
                  // Gateway is the health endpoint itself — if we got data, it's up
                  const isGateway = svc.key === 'gateway';
                  const status = isGateway
                    ? (healthData ? 'ok' : 'down')
                    : (info?.status ?? 'down');
                  const latency = isGateway ? null : info?.latency_ms;
                  return (
                    <TableRow key={svc.name}>
                      <TableCell>
                        <Typography variant="body2" fontWeight={500}>
                          {svc.name}
                        </Typography>
                      </TableCell>
                      <TableCell>{svc.port}</TableCell>
                      <TableCell>
                        {statusDot(status)}
                        {status}
                      </TableCell>
                      <TableCell align="right">
                        {latency != null ? `${latency}ms` : (isGateway && healthData ? 'self' : '--')}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </Paper>

      {/* Section 2: LLM Configuration */}
      <Paper sx={{ p: 2, mb: 3 }}>
        <Typography variant="h6" fontWeight={600} sx={{ mb: 2 }}>
          LLM Configuration
        </Typography>
        <Stack spacing={3}>
          <TextField
            select
            label="Model"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            size="small"
            sx={{ maxWidth: 300 }}
          >
            {LLM_MODELS.map((m) => (
              <MenuItem key={m} value={m}>
                {m}
              </MenuItem>
            ))}
          </TextField>

          <Box>
            <Typography variant="body2" gutterBottom>
              Temperature: {temperature.toFixed(2)}
            </Typography>
            <Slider
              value={temperature}
              onChange={(_, v) => setTemperature(v as number)}
              min={0}
              max={1}
              step={0.01}
              valueLabelDisplay="auto"
              sx={{ maxWidth: 400 }}
            />
          </Box>

          <TextField
            label="Max Tokens"
            type="number"
            value={maxTokens}
            onChange={(e) => setMaxTokens(Number(e.target.value))}
            size="small"
            inputProps={{ min: 256, max: 128000, step: 256 }}
            sx={{ maxWidth: 200 }}
          />
        </Stack>
      </Paper>

      {/* Section 3: Retry Configuration */}
      <Paper sx={{ p: 2, mb: 3 }}>
        <Typography variant="h6" fontWeight={600} sx={{ mb: 2 }}>
          Retry Configuration
        </Typography>
        <Stack spacing={3}>
          <TextField
            select
            label="Strategy"
            value={retryStrategy}
            onChange={(e) => setRetryStrategy(e.target.value)}
            size="small"
            sx={{ maxWidth: 300 }}
          >
            {RETRY_STRATEGIES.map((s) => (
              <MenuItem key={s} value={s}>
                {s}
              </MenuItem>
            ))}
          </TextField>

          <Box>
            <Typography variant="body2" gutterBottom>
              Max Attempts: {maxAttempts}
            </Typography>
            <Slider
              value={maxAttempts}
              onChange={(_, v) => setMaxAttempts(v as number)}
              min={1}
              max={10}
              step={1}
              marks
              valueLabelDisplay="auto"
              sx={{ maxWidth: 400 }}
            />
          </Box>
        </Stack>
      </Paper>

      {/* Section 4: Rate Limiting */}
      <Paper sx={{ p: 2, mb: 3 }}>
        <Typography variant="h6" fontWeight={600} sx={{ mb: 2 }}>
          Rate Limiting
        </Typography>
        <Box>
          <Typography variant="body2" gutterBottom>
            Requests Per Minute: {rpm}
          </Typography>
          <Slider
            value={rpm}
            onChange={(_, v) => setRpm(v as number)}
            min={10}
            max={500}
            step={10}
            valueLabelDisplay="auto"
            sx={{ maxWidth: 400 }}
          />
        </Box>
      </Paper>

      {/* Save */}
      <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
        <Button
          variant="contained"
          size="large"
          startIcon={<SaveIcon />}
          onClick={handleSave}
        >
          Save Settings
        </Button>
      </Box>
      </>}
    </Box>
  );
}
