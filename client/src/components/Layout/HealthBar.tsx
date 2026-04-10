import { Box, Tooltip, useTheme } from '@mui/material';
import { useNavigate } from 'react-router-dom';
import { useHealthStatus } from '@/api/health';

interface ServiceDef {
  key: string;
  label: string;
  port: number;
}

const SERVICES: ServiceDef[] = [
  { key: 'gateway', label: 'Gateway', port: 4000 },
  { key: 'orchestrator', label: 'Orchestrator', port: 8000 },
  { key: 'memory', label: 'Memory', port: 8001 },
  { key: 'rag', label: 'RAG', port: 8002 },
  { key: 'scoring', label: 'Scoring', port: 8003 },
  { key: 'agent-mgmt', label: 'Agent Mgmt', port: 4001 },
  { key: 'meta-assembly', label: 'Meta-Assembly', port: 8004 },
];

export default function HealthBar() {
  const theme = useTheme();
  const navigate = useNavigate();
  const { data: healthData, isLoading } = useHealthStatus();

  // healthData is the full response: { status, services: { key: { status, latency_ms } } }
  const getService = (serviceKey: string): { status: string; latency_ms?: number } | null => {
    if (!healthData) return null;

    // Gateway is special: if we got any response at all, the gateway is up
    if (serviceKey === 'gateway') {
      return healthData ? { status: 'ok' } : null;
    }

    const services = healthData.services as
      | Record<string, { status: string; latency_ms: number }>
      | undefined;
    if (services && services[serviceKey]) {
      return services[serviceKey];
    }
    return null;
  };

  const getStatusColor = (serviceKey: string): string => {
    if (isLoading || !healthData) return theme.palette.action.disabled;
    const entry = getService(serviceKey);
    if (!entry) return theme.palette.action.disabled;
    if (entry.status === 'ok' || entry.status === 'healthy') return theme.palette.success.main;
    if (entry.status === 'degraded') return theme.palette.warning.main;
    return theme.palette.error.main;
  };

  const getTooltip = (svc: ServiceDef): string => {
    if (isLoading) return `${svc.label} (port ${svc.port}) - loading...`;
    const entry = getService(svc.key);
    if (!entry) return `${svc.label} (port ${svc.port}) - unknown`;
    const latency = entry.latency_ms != null ? ` - ${entry.latency_ms}ms` : '';
    return `${svc.label} (port ${svc.port}) - ${entry.status}${latency}`;
  };

  const handleClick = () => {
    navigate('/settings');
  };

  return (
    <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
      {SERVICES.map((svc) => (
        <Tooltip key={svc.key} title={getTooltip(svc)} arrow>
          <Box
            onClick={handleClick}
            sx={{
              width: 10,
              height: 10,
              borderRadius: '50%',
              bgcolor: getStatusColor(svc.key),
              transition: 'background-color 0.3s',
              cursor: 'pointer',
            }}
          />
        </Tooltip>
      ))}
    </Box>
  );
}
