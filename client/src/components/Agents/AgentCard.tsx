import {
  Card,
  CardActionArea,
  CardContent,
  Typography,
  Chip,
  Box,
  Stack,
} from '@mui/material';
import { useTheme } from '@mui/material/styles';
import type { Agent } from '@/types';
import ScoreBandViz from './ScoreBandViz';

interface Props {
  agent: Agent;
  onClick: (agent: Agent) => void;
}

const statusColorMap: Record<Agent['status'], 'success' | 'info' | 'warning' | 'error' | 'default'> = {
  IDLE: 'default',
  ACTIVE: 'success',
  BUSY: 'info',
  DEGRADED: 'warning',
  DEPRECATED: 'error',
};

export default function AgentCard({ agent, onClick }: Props) {
  const theme = useTheme();

  return (
    <Card
      sx={{
        height: '100%',
        transition: 'box-shadow 0.2s, transform 0.2s',
        '&:hover': {
          boxShadow: theme.shadows[6],
          transform: 'translateY(-2px)',
        },
      }}
    >
      <CardActionArea
        onClick={() => onClick(agent)}
        sx={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'stretch' }}
      >
        <CardContent sx={{ flexGrow: 1, display: 'flex', flexDirection: 'column', gap: 1.5 }}>
          {/* Header */}
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <Typography variant="subtitle1" fontWeight={700} noWrap sx={{ flex: 1, mr: 1 }}>
              {agent.name}
            </Typography>
            <Chip
              label={agent.status}
              color={statusColorMap[agent.status]}
              size="small"
              sx={{ fontWeight: 600, fontSize: '0.7rem' }}
            />
          </Box>

          {/* Model chip */}
          <Box>
            <Chip
              label={agent.foundation_model}
              variant="outlined"
              size="small"
              sx={{ fontSize: '0.7rem' }}
            />
          </Box>

          {/* Score band */}
          <Box sx={{ mt: 0.5 }}>
            <Typography variant="caption" color="text.secondary" sx={{ mb: 0.5, display: 'block' }}>
              Score Band
            </Typography>
            <ScoreBandViz
              bandLow={agent.health_score * 0.8}
              bandHigh={Math.min(1, agent.health_score * 1.2)}
              currentScore={agent.health_score}
            />
          </Box>

          {/* Stats row */}
          <Stack direction="row" spacing={2} sx={{ mt: 'auto', pt: 1 }}>
            <Box>
              <Typography variant="caption" color="text.secondary">Executions</Typography>
              <Typography variant="body2" fontWeight={600}>{agent.total_executions}</Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">Accuracy</Typography>
              <Typography variant="body2" fontWeight={600}>
                {(agent.accuracy_rate * 100).toFixed(1)}%
              </Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">Success</Typography>
              <Typography variant="body2" fontWeight={600}>
                {(agent.success_rate * 100).toFixed(1)}%
              </Typography>
            </Box>
          </Stack>

          {/* Domain tags */}
          {agent.description && (
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mt: 0.5 }}>
              {agent.description.split(',').slice(0, 3).map((tag: string) => (
                <Chip
                  key={tag.trim()}
                  label={tag.trim()}
                  size="small"
                  sx={{ fontSize: '0.65rem', height: 20 }}
                />
              ))}
            </Box>
          )}
        </CardContent>
      </CardActionArea>
    </Card>
  );
}
