import {
  Box,
  Typography,
  RadioGroup,
  Radio,
  FormControlLabel,
  TextField,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Chip,
  Stack,
  IconButton,
  Divider,
  Paper,
  Slide,
  useTheme,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import type { Node } from 'reactflow';
import type { Agent } from '@/types';

type ExecutionMode = 'sequential' | 'parallel' | 'conditional';
type Criticality = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';

interface NodeRules {
  executionMode: ExecutionMode;
  condition: string;
  maxRetries: number;
  criticality: Criticality;
  timeout: number;
  fallbackAgentId: number | null;
}

interface HierarchyRulesPanelProps {
  open: boolean;
  onClose: () => void;
  selectedNode: Node | null;
  rules: NodeRules;
  onRulesChange: (rules: NodeRules) => void;
  agents: Agent[];
}

const CRITICALITY_OPTIONS: Criticality[] = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'];

const CRITICALITY_COLORS: Record<Criticality, string> = {
  LOW: 'success',
  MEDIUM: 'info',
  HIGH: 'warning',
  CRITICAL: 'error',
};

export default function HierarchyRulesPanel({
  open,
  onClose,
  selectedNode,
  rules,
  onRulesChange,
  agents,
}: HierarchyRulesPanelProps) {
  const theme = useTheme();

  if (!selectedNode) return null;

  const handleChange = <K extends keyof NodeRules>(key: K, value: NodeRules[K]) => {
    onRulesChange({ ...rules, [key]: value });
  };

  return (
    <Slide direction="left" in={open} mountOnEnter unmountOnExit>
      <Paper
        elevation={8}
        sx={{
          position: 'absolute',
          top: 0,
          right: 0,
          width: 300,
          height: '100%',
          zIndex: 10,
          display: 'flex',
          flexDirection: 'column',
          borderLeft: `1px solid ${theme.palette.divider}`,
          bgcolor: 'background.paper',
          overflow: 'auto',
        }}
      >
        {/* Header */}
        <Box
          sx={{
            p: 2,
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            borderBottom: `1px solid ${theme.palette.divider}`,
          }}
        >
          <Box>
            <Typography variant="subtitle2" fontWeight={700}>
              Node Rules
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {selectedNode.data?.agentName || 'Unassigned node'}
            </Typography>
          </Box>
          <IconButton size="small" onClick={onClose}>
            <CloseIcon fontSize="small" />
          </IconButton>
        </Box>

        {/* Content */}
        <Box sx={{ p: 2, display: 'flex', flexDirection: 'column', gap: 2.5 }}>
          {/* Execution Mode */}
          <Box>
            <Typography variant="caption" fontWeight={600} color="text.secondary" sx={{ mb: 0.5 }}>
              Execution Mode
            </Typography>
            <RadioGroup
              value={rules.executionMode}
              onChange={(e) => handleChange('executionMode', e.target.value as ExecutionMode)}
            >
              <FormControlLabel
                value="sequential"
                control={<Radio size="small" />}
                label={<Typography variant="body2">Sequential</Typography>}
              />
              <FormControlLabel
                value="parallel"
                control={<Radio size="small" />}
                label={<Typography variant="body2">Parallel</Typography>}
              />
              <FormControlLabel
                value="conditional"
                control={<Radio size="small" />}
                label={<Typography variant="body2">Conditional</Typography>}
              />
            </RadioGroup>
          </Box>

          {/* Condition expression (shown only for conditional) */}
          {rules.executionMode === 'conditional' && (
            <TextField
              label="Condition Expression"
              size="small"
              fullWidth
              multiline
              rows={2}
              value={rules.condition}
              onChange={(e) => handleChange('condition', e.target.value)}
              placeholder="e.g., score > 0.7 && status == 'success'"
            />
          )}

          <Divider />

          {/* Max Retries */}
          <TextField
            label="Max Retries"
            type="number"
            size="small"
            fullWidth
            value={rules.maxRetries}
            onChange={(e) => handleChange('maxRetries', Math.max(0, parseInt(e.target.value) || 0))}
            inputProps={{ min: 0, max: 10 }}
          />

          {/* Criticality */}
          <Box>
            <Typography variant="caption" fontWeight={600} color="text.secondary" sx={{ mb: 1, display: 'block' }}>
              Criticality
            </Typography>
            <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
              {CRITICALITY_OPTIONS.map((c) => (
                <Chip
                  key={c}
                  label={c}
                  size="small"
                  variant={rules.criticality === c ? 'filled' : 'outlined'}
                  color={CRITICALITY_COLORS[c] as 'success' | 'info' | 'warning' | 'error'}
                  onClick={() => handleChange('criticality', c)}
                  sx={{ cursor: 'pointer', fontWeight: 600 }}
                />
              ))}
            </Stack>
          </Box>

          {/* Timeout */}
          <TextField
            label="Timeout (seconds)"
            type="number"
            size="small"
            fullWidth
            value={rules.timeout}
            onChange={(e) => handleChange('timeout', Math.max(1, parseInt(e.target.value) || 30))}
            inputProps={{ min: 1, max: 600 }}
          />

          <Divider />

          {/* Fallback Agent */}
          <FormControl size="small" fullWidth>
            <InputLabel>Fallback Agent</InputLabel>
            <Select
              value={rules.fallbackAgentId ?? ''}
              label="Fallback Agent"
              onChange={(e) =>
                handleChange('fallbackAgentId', e.target.value === '' ? null : Number(e.target.value))
              }
            >
              <MenuItem value="">
                <em>None</em>
              </MenuItem>
              {agents.map((agent) => (
                <MenuItem key={agent.id} value={agent.id}>
                  {agent.name}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        </Box>
      </Paper>
    </Slide>
  );
}

export type { NodeRules, ExecutionMode, Criticality };
