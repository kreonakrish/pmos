import { Box, Typography, Button, Paper, Stack, Chip, useTheme } from '@mui/material';
import ChatIcon from '@mui/icons-material/Chat';
import GroupWorkIcon from '@mui/icons-material/GroupWork';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import BuildIcon from '@mui/icons-material/Build';
import { useNavigate } from 'react-router-dom';

export default function HomePage() {
  const theme = useTheme();
  const navigate = useNavigate();

  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: 'calc(100vh - 200px)',
        textAlign: 'center',
        px: 3,
      }}
    >
      <Typography
        variant="h3"
        sx={{
          fontWeight: 800,
          background: `linear-gradient(135deg, ${theme.palette.primary.main}, ${theme.palette.secondary.main})`,
          backgroundClip: 'text',
          WebkitBackgroundClip: 'text',
          WebkitTextFillColor: 'transparent',
          mb: 2,
        }}
      >
        PMOS
      </Typography>
      <Typography variant="h6" color="text.secondary" sx={{ mb: 1, maxWidth: 600 }}>
        Perpetual Multi-Agent Orchestration System
      </Typography>
      <Typography variant="body1" color="text.secondary" sx={{ mb: 4, maxWidth: 550 }}>
        A living cognitive infrastructure where AI agents collaborate, use tools,
        score each other's outputs, and evolve their capabilities with every execution.
      </Typography>

      <Stack direction="row" spacing={1.5} sx={{ mb: 5 }} flexWrap="wrap" justifyContent="center" useFlexGap>
        <Chip label="Multi-Agent Teams" size="small" variant="outlined" />
        <Chip label="Tool Integration" size="small" variant="outlined" />
        <Chip label="Living Neo4j Graph" size="small" variant="outlined" />
        <Chip label="4-Tier Memory" size="small" variant="outlined" />
        <Chip label="Adaptive Scoring" size="small" variant="outlined" />
        <Chip label="RAG Documents" size="small" variant="outlined" />
      </Stack>

      <Button
        variant="contained"
        size="large"
        startIcon={<ChatIcon />}
        onClick={() => navigate('/conversations')}
        sx={{ px: 4, py: 1.5, fontSize: '1rem', borderRadius: 2, mb: 4 }}
      >
        Start a Conversation
      </Button>

      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ maxWidth: 700, width: '100%' }}>
        {[
          { icon: <SmartToyIcon />, title: 'Agent Studio', desc: 'Configure AI agents with tools, memory, and scoring', path: '/agent-studio' },
          { icon: <GroupWorkIcon />, title: 'Team Studio', desc: 'Build hierarchical agent teams with orchestrators', path: '/team-studio' },
          { icon: <BuildIcon />, title: 'Tool Studio', desc: 'Manage tools — databases, APIs, Python, GitHub', path: '/tool-studio' },
        ].map((card) => (
          <Paper
            key={card.path}
            variant="outlined"
            sx={{
              flex: 1,
              p: 2.5,
              cursor: 'pointer',
              transition: 'all 0.2s',
              '&:hover': {
                borderColor: theme.palette.primary.main,
                transform: 'translateY(-2px)',
                boxShadow: `0 4px 12px ${theme.palette.primary.main}20`,
              },
            }}
            onClick={() => navigate(card.path)}
          >
            <Box sx={{ color: 'primary.main', mb: 1 }}>{card.icon}</Box>
            <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 0.5 }}>
              {card.title}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {card.desc}
            </Typography>
          </Paper>
        ))}
      </Stack>
    </Box>
  );
}
