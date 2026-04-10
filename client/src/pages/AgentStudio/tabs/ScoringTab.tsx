import { useEffect } from 'react';
import {
  Box,
  Typography,
  Slider,
  Stack,
  Alert,
  Button,
  Paper,
  useTheme,
  CircularProgress,
} from '@mui/material';
import RestartAltIcon from '@mui/icons-material/RestartAlt';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, ResponsiveContainer, Tooltip } from 'recharts';
import { useScoreHistory, useScoringWeights, useScoreBand } from '@/api/scoring';
import type { AgentFormData, ScoringWeights } from '../index';

const WEIGHT_LABELS: { key: keyof ScoringWeights; label: string }[] = [
  { key: 'relevance', label: 'Relevance' },
  { key: 'accuracy', label: 'Accuracy' },
  { key: 'precision', label: 'Precision' },
  { key: 'latency', label: 'Latency' },
  { key: 'confidence', label: 'Confidence' },
  { key: 'knowledge_usage', label: 'Knowledge Usage' },
];

const DEFAULT_WEIGHTS: ScoringWeights = {
  relevance: 0.2,
  accuracy: 0.2,
  precision: 0.15,
  latency: 0.15,
  confidence: 0.15,
  knowledge_usage: 0.15,
};

// Map backend weight keys (w1-w6) to our UI keys
const BACKEND_WEIGHT_MAP: Record<string, keyof ScoringWeights> = {
  w1: 'relevance', w2: 'accuracy', w3: 'precision',
  w4: 'latency', w5: 'confidence', w6: 'knowledge_usage',
  relevance: 'relevance', accuracy: 'accuracy', precision: 'precision',
  latency: 'latency', confidence: 'confidence', knowledge_usage: 'knowledge_usage',
};

interface ScoringTabProps {
  agentData: AgentFormData;
  onChange: (partial: Partial<AgentFormData>) => void;
}

export default function ScoringTab({ agentData, onChange }: ScoringTabProps) {
  const theme = useTheme();
  const weights = agentData.scoring_weights;
  const agentId = agentData.id ?? 0;

  // Fetch real data from scoring service
  const { data: scoreHistory } = useScoreHistory(agentId);
  const { data: weightsData } = useScoringWeights(agentId);
  const { data: bandData } = useScoreBand(agentId, 'general');

  // Populate weights from backend on first load
  useEffect(() => {
    if (weightsData?.weights) {
      const backendWeights: Partial<ScoringWeights> = {};
      for (const [bk, val] of Object.entries(weightsData.weights)) {
        const uiKey = BACKEND_WEIGHT_MAP[bk];
        if (uiKey) backendWeights[uiKey] = val;
      }
      // Only update if we got meaningful weights
      if (Object.keys(backendWeights).length > 0) {
        onChange({ scoring_weights: { ...DEFAULT_WEIGHTS, ...backendWeights } });
      }
    }
  }, [weightsData]); // eslint-disable-line react-hooks/exhaustive-deps

  const weightSum = Object.values(weights).reduce((a, b) => a + b, 0);
  const sumOk = Math.abs(weightSum - 1.0) < 0.01;

  const handleWeightChange = (key: keyof ScoringWeights, value: number) => {
    onChange({ scoring_weights: { ...weights, [key]: value } });
  };

  const handleReset = () => {
    onChange({ scoring_weights: { ...DEFAULT_WEIGHTS } });
  };

  // Real score history for sparkline (last 10)
  const sparklineData = (scoreHistory ?? [])
    .slice(-10)
    .map((entry, i) => ({ idx: i + 1, score: entry.score }));

  // Real adaptive band
  const bandLow = bandData?.low ?? 0;
  const bandHigh = bandData?.high ?? 1;
  const bandWidth = bandHigh - bandLow;
  const hasBand = !!bandData;

  return (
    <Stack spacing={3} sx={{ maxWidth: 700 }}>
      {/* Weight Sliders */}
      <Box>
        <Typography variant="subtitle2" gutterBottom>
          Scoring Weight Distribution
        </Typography>
        <Typography variant="caption" color="text.secondary" sx={{ mb: 2, display: 'block' }}>
          S = w1*Relevance + w2*Accuracy + w3*Precision + w4*Latency + w5*Confidence + w6*Knowledge
        </Typography>

        {WEIGHT_LABELS.map(({ key, label }) => (
          <Box key={key} sx={{ mb: 1.5 }}>
            <Stack direction="row" justifyContent="space-between" alignItems="center">
              <Typography variant="body2">{label}</Typography>
              <Typography variant="body2" fontWeight={600} fontFamily="monospace">
                {weights[key].toFixed(2)}
              </Typography>
            </Stack>
            <Slider
              value={weights[key]}
              onChange={(_, v) => handleWeightChange(key, v as number)}
              min={0}
              max={1}
              step={0.05}
              size="small"
              sx={{ py: 0.5 }}
            />
          </Box>
        ))}

        {/* Weight Sum */}
        <Stack direction="row" spacing={2} alignItems="center" sx={{ mt: 1 }}>
          <Typography variant="body2" fontWeight={600}>
            Sum: {weightSum.toFixed(2)}
          </Typography>
          {!sumOk && (
            <Alert severity="warning" variant="outlined" sx={{ py: 0, px: 1 }}>
              Weights should sum to 1.0
            </Alert>
          )}
          {sumOk && (
            <Alert severity="success" variant="outlined" sx={{ py: 0, px: 1 }}>
              Weights sum to 1.0
            </Alert>
          )}
        </Stack>
      </Box>

      {/* Adaptive Bands */}
      <Box>
        <Typography variant="subtitle2" gutterBottom>
          Current Adaptive Band
        </Typography>
        {agentData.id && hasBand ? (
          <Paper variant="outlined" sx={{ p: 2 }}>
            <Box sx={{ position: 'relative', height: 32, bgcolor: 'action.hover', borderRadius: 1 }}>
              <Box
                sx={{
                  position: 'absolute',
                  left: `${bandLow * 100}%`,
                  width: `${bandWidth * 100}%`,
                  height: '100%',
                  bgcolor: 'primary.main',
                  opacity: 0.3,
                  borderRadius: 1,
                }}
              />
              <Typography
                variant="caption"
                sx={{
                  position: 'absolute',
                  left: `${bandLow * 100}%`,
                  bottom: -18,
                  transform: 'translateX(-50%)',
                  fontFamily: 'monospace',
                }}
              >
                {bandLow.toFixed(2)}
              </Typography>
              <Typography
                variant="caption"
                sx={{
                  position: 'absolute',
                  left: `${bandHigh * 100}%`,
                  bottom: -18,
                  transform: 'translateX(-50%)',
                  fontFamily: 'monospace',
                }}
              >
                {bandHigh.toFixed(2)}
              </Typography>
            </Box>
            <Stack direction="row" justifyContent="space-between" sx={{ mt: 3 }}>
              <Typography variant="caption" color="text.secondary">0.0</Typography>
              <Typography variant="caption" color="text.secondary">1.0</Typography>
            </Stack>
          </Paper>
        ) : (
          <Typography variant="caption" color="text.secondary">
            {agentData.id
              ? 'Adaptive bands will be computed after the agent starts receiving scores.'
              : 'Save the agent first to see adaptive bands.'}
          </Typography>
        )}
      </Box>

      {/* Last 10 Scores Sparkline */}
      {agentData.id && (
        <Box>
          <Typography variant="subtitle2" gutterBottom>
            Recent Scores ({sparklineData.length})
          </Typography>
          {sparklineData.length > 0 ? (
            <Paper variant="outlined" sx={{ p: 1.5 }}>
              <ResponsiveContainer width="100%" height={100}>
                <LineChart data={sparklineData}>
                  <CartesianGrid strokeDasharray="3 3" stroke={theme.palette.divider} />
                  <XAxis dataKey="idx" hide />
                  <YAxis domain={[0, 1]} hide />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: theme.palette.background.paper,
                      border: `1px solid ${theme.palette.divider}`,
                      borderRadius: 4,
                      fontSize: 12,
                    }}
                    formatter={(value: number) => [value.toFixed(3), 'Score']}
                  />
                  <Line
                    type="monotone"
                    dataKey="score"
                    stroke={theme.palette.primary.main}
                    strokeWidth={2}
                    dot={{ r: 3 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </Paper>
          ) : (
            <Typography variant="caption" color="text.secondary">
              No scores yet. Test the agent to generate scores.
            </Typography>
          )}
        </Box>
      )}

      {/* Reset Button */}
      <Box>
        <Button
          variant="outlined"
          startIcon={<RestartAltIcon />}
          onClick={handleReset}
        >
          Reset to Default Weights
        </Button>
      </Box>
    </Stack>
  );
}
