import { useState } from 'react';
import {
  Box,
  TextField,
  Button,
  Switch,
  FormControlLabel,
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
import type { AgentFormData } from './index';
import IdentityTab from './tabs/IdentityTab';
import LLMConfigTab from './tabs/LLMConfigTab';
import ToolsTab from './tabs/ToolsTab';
import MemoryTab from './tabs/MemoryTab';
import ScoringTab from './tabs/ScoringTab';
import PerformanceTab from './tabs/PerformanceTab';
import TestAgentPanel from './tabs/TestAgentPanel';
import HistoryTab from './tabs/HistoryTab';

interface AgentEditorProps {
  agentData: AgentFormData | null;
  isCreating: boolean;
  onChange: (data: AgentFormData) => void;
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

export default function AgentEditor({
  agentData,
  isCreating,
  onChange,
  onSave,
  onDelete,
  onDuplicate,
}: AgentEditorProps) {
  const theme = useTheme();
  const [activeTab, setActiveTab] = useState(0);

  if (!agentData) {
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
            No Agent Selected
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Select an agent from the list or create a new one to get started.
          </Typography>
        </Paper>
      </Box>
    );
  }

  const update = (partial: Partial<AgentFormData>) => {
    onChange({ ...agentData, ...partial });
  };

  const handleToggleStatus = () => {
    update({ status: agentData.status === 'ACTIVE' ? 'IDLE' : 'ACTIVE' });
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
          value={agentData.name}
          onChange={(e) => update({ name: e.target.value })}
          variant="standard"
          placeholder="Agent Name"
          InputProps={{
            sx: { fontSize: '1.25rem', fontWeight: 600 },
            disableUnderline: false,
          }}
          sx={{ minWidth: 200, flex: 1, maxWidth: 400 }}
        />

        <FormControlLabel
          control={
            <Switch
              checked={agentData.status === 'ACTIVE'}
              onChange={handleToggleStatus}
              color="success"
              size="small"
            />
          }
          label={
            <Chip
              label={agentData.status === 'ACTIVE' ? 'Active' : 'Inactive'}
              size="small"
              color={agentData.status === 'ACTIVE' ? 'success' : 'default'}
              variant="outlined"
            />
          }
        />

        <Box sx={{ flex: 1 }} />

        <Stack direction="row" spacing={1}>
          <Tooltip title="Test Agent">
            <IconButton size="small" color="info" onClick={() => setActiveTab(6)}>
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
          variant="scrollable"
          scrollButtons="auto"
          sx={{ minHeight: 40, '& .MuiTab-root': { minHeight: 40, py: 0 } }}
        >
          <Tab label="Identity" />
          <Tab label="LLM Config" />
          <Tab label="Tools" />
          <Tab label="Memory" />
          <Tab label="Scoring" />
          <Tab label="Performance" />
          <Tab label="Test Agent" />
          <Tab label="History" />
        </Tabs>
      </Box>

      {/* Tab Content */}
      <TabPanel value={activeTab} index={0}>
        <IdentityTab agentData={agentData} onChange={update} />
      </TabPanel>
      <TabPanel value={activeTab} index={1}>
        <LLMConfigTab agentData={agentData} onChange={update} />
      </TabPanel>
      <TabPanel value={activeTab} index={2}>
        <ToolsTab agentData={agentData} onChange={update} />
      </TabPanel>
      <TabPanel value={activeTab} index={3}>
        <MemoryTab agentData={agentData} onChange={update} />
      </TabPanel>
      <TabPanel value={activeTab} index={4}>
        <ScoringTab agentData={agentData} onChange={update} />
      </TabPanel>
      <TabPanel value={activeTab} index={5}>
        <PerformanceTab agentId={agentData.id} />
      </TabPanel>
      <TabPanel value={activeTab} index={6}>
        <TestAgentPanel key={agentData.agent_id ?? 'new'} agentData={agentData} />
      </TabPanel>
      <TabPanel value={activeTab} index={7}>
        <HistoryTab agentId={agentData.agent_id} />
      </TabPanel>
    </Box>
  );
}
