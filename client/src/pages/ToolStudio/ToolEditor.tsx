import { useState } from 'react';
import {
  Box,
  TextField,
  Button,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Tabs,
  Tab,
  Paper,
  Typography,
  Chip,
  Stack,
  IconButton,
  Tooltip,
  useTheme,
} from '@mui/material';
import SaveIcon from '@mui/icons-material/Save';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import type { ToolFormData, ToolType } from './index';
import ApiConfig from './configs/ApiConfig';
import DatabaseConfig from './configs/DatabaseConfig';
import PythonConfig from './configs/PythonConfig';
import GitHubConfig from './configs/GitHubConfig';
import TestPanel from './TestPanel';
import HistoryPanel from './HistoryPanel';
import CoveragePanel from './CoveragePanel';

const TOOL_TYPES: ToolType[] = ['API', 'Database', 'Python', 'GitHub', 'WebService'];

interface ToolEditorProps {
  toolData: ToolFormData | null;
  isCreating: boolean;
  onChange: (data: ToolFormData) => void;
  onSave: () => void;
  onDelete: () => void;
  onDuplicate: () => void;
}

interface TabPanelProps {
  children: React.ReactNode;
  value: number;
  index: number;
}

function TabPanel({ children, value, index }: TabPanelProps) {
  return (
    <Box
      role="tabpanel"
      hidden={value !== index}
      sx={{ flex: 1, overflow: 'auto', p: 2.5 }}
    >
      {value === index && children}
    </Box>
  );
}

function getHealthColor(status: string): 'success' | 'warning' | 'error' | 'default' {
  switch (status) {
    case 'ACTIVE':
      return 'success';
    case 'DEGRADED':
      return 'warning';
    case 'OFFLINE':
      return 'error';
    default:
      return 'default';
  }
}

export default function ToolEditor({
  toolData,
  isCreating,
  onChange,
  onSave,
  onDelete,
  onDuplicate,
}: ToolEditorProps) {
  const theme = useTheme();
  const [activeTab, setActiveTab] = useState(0);
  const [domainInput, setDomainInput] = useState('');

  if (!toolData) {
    return (
      <Box
        sx={{
          flex: 1,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Paper sx={{ p: 6, textAlign: 'center', maxWidth: 400 }}>
          <Typography variant="h6" color="text.secondary" gutterBottom>
            No Tool Selected
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Select a tool from the list or create a new one to get started.
          </Typography>
        </Paper>
      </Box>
    );
  }

  const update = (partial: Partial<ToolFormData>) => {
    onChange({ ...toolData, ...partial });
  };

  const updateConfig = (partial: Record<string, unknown>) => {
    onChange({ ...toolData, config: { ...toolData.config, ...partial } });
  };

  const handleAddDomain = () => {
    const tag = domainInput.trim();
    if (tag && !toolData.domains.includes(tag)) {
      update({ domains: [...toolData.domains, tag] });
      setDomainInput('');
    }
  };

  const handleRemoveDomain = (tag: string) => {
    update({ domains: toolData.domains.filter((d) => d !== tag) });
  };

  const handleDomainKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleAddDomain();
    }
  };

  const renderConfigTab = () => {
    const config = toolData.config;
    switch (toolData.tool_type) {
      case 'API':
      case 'WebService':
        return <ApiConfig config={config} onChange={updateConfig} />;
      case 'Database':
        return <DatabaseConfig config={config} onChange={updateConfig} />;
      case 'Python':
        return <PythonConfig config={config} onChange={updateConfig} />;
      case 'GitHub':
        return <GitHubConfig config={config} onChange={updateConfig} />;
      default:
        return (
          <Typography variant="body2" color="text.secondary">
            Select a tool type to configure.
          </Typography>
        );
    }
  };

  return (
    <Box
      sx={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        bgcolor: theme.palette.background.default,
      }}
    >
      {/* Header */}
      <Box
        sx={{
          px: 2.5,
          py: 1.5,
          borderBottom: `1px solid ${theme.palette.divider}`,
          bgcolor: theme.palette.background.paper,
          display: 'flex',
          alignItems: 'center',
          gap: 2,
          flexWrap: 'wrap',
        }}
      >
        <TextField
          value={toolData.name}
          onChange={(e) => update({ name: e.target.value })}
          variant="standard"
          placeholder="Tool Name"
          InputProps={{
            sx: { fontSize: '1.25rem', fontWeight: 600 },
            disableUnderline: false,
          }}
          sx={{ minWidth: 200, flex: 1, maxWidth: 400 }}
        />

        <FormControl size="small" sx={{ minWidth: 140 }}>
          <InputLabel>Type</InputLabel>
          <Select
            value={toolData.tool_type}
            label="Type"
            onChange={(e) => update({ tool_type: e.target.value as ToolType, config: {} })}
          >
            {TOOL_TYPES.map((t) => (
              <MenuItem key={t} value={t}>
                {t}
              </MenuItem>
            ))}
          </Select>
        </FormControl>

        <Chip
          label={toolData.status}
          size="small"
          color={getHealthColor(toolData.status)}
          variant="outlined"
        />

        <Box sx={{ flex: 1 }} />

        <Stack direction="row" spacing={1}>
          <Tooltip title="Test Tool">
            <IconButton
              size="small"
              color="info"
              onClick={() => setActiveTab(3)}
            >
              <PlayArrowIcon />
            </IconButton>
          </Tooltip>
          <Tooltip title="Duplicate">
            <IconButton size="small" onClick={onDuplicate}>
              <ContentCopyIcon />
            </IconButton>
          </Tooltip>
          <Tooltip title="Delete">
            <IconButton size="small" color="error" onClick={onDelete}>
              <DeleteOutlineIcon />
            </IconButton>
          </Tooltip>
          <Button
            variant="contained"
            size="small"
            startIcon={<SaveIcon />}
            onClick={onSave}
          >
            {isCreating ? 'Create' : 'Save'}
          </Button>
        </Stack>
      </Box>

      {/* Tabs */}
      <Box sx={{ borderBottom: `1px solid ${theme.palette.divider}`, bgcolor: theme.palette.background.paper }}>
        <Tabs
          value={activeTab}
          onChange={(_, v) => setActiveTab(v)}
          sx={{ minHeight: 40, '& .MuiTab-root': { minHeight: 40, py: 0 } }}
        >
          <Tab label="General" />
          <Tab label="Configuration" />
          <Tab label="Coverage" />
          <Tab label="Test Panel" />
          <Tab label="History" />
        </Tabs>
      </Box>

      {/* Tab Content */}
      <TabPanel value={activeTab} index={0}>
        <Stack spacing={3} sx={{ maxWidth: 700 }}>
          <TextField
            label="Description"
            multiline
            minRows={3}
            maxRows={6}
            fullWidth
            value={toolData.description}
            onChange={(e) => update({ description: e.target.value })}
          />

          <Box>
            <Typography variant="subtitle2" gutterBottom>
              Domain Tags
            </Typography>
            <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap sx={{ mb: 1 }}>
              {toolData.domains.map((d) => (
                <Chip key={d} label={d} size="small" onDelete={() => handleRemoveDomain(d)} />
              ))}
            </Stack>
            <TextField
              size="small"
              placeholder="Add domain tag and press Enter"
              value={domainInput}
              onChange={(e) => setDomainInput(e.target.value)}
              onKeyDown={handleDomainKeyDown}
              onBlur={handleAddDomain}
              sx={{ maxWidth: 300 }}
            />
          </Box>

          <Stack direction="row" spacing={2}>
            <TextField
              label="Timeout (ms)"
              type="number"
              size="small"
              value={toolData.timeout_ms}
              onChange={(e) => update({ timeout_ms: Number(e.target.value) })}
              sx={{ width: 160 }}
            />
            <TextField
              label="Max Retries"
              type="number"
              size="small"
              value={toolData.max_retries}
              onChange={(e) => update({ max_retries: Number(e.target.value) })}
              sx={{ width: 160 }}
              inputProps={{ min: 0, max: 10 }}
            />
          </Stack>
        </Stack>
      </TabPanel>

      <TabPanel value={activeTab} index={1}>
        {renderConfigTab()}
      </TabPanel>

      <TabPanel value={activeTab} index={2}>
        <CoveragePanel toolId={toolData.tool_id} />
      </TabPanel>

      <TabPanel value={activeTab} index={3}>
        <TestPanel key={`${toolData.tool_id ?? 'new'}-${toolData.tool_type}`} toolData={toolData} />
      </TabPanel>

      <TabPanel value={activeTab} index={4}>
        <HistoryPanel toolId={toolData.tool_id} />
      </TabPanel>
    </Box>
  );
}

