import { useCallback, useEffect, useState } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { ThemeProvider, CssBaseline, Box, Toolbar } from '@mui/material';
import { darkTheme, lightTheme } from '@/theme';
import { useUIStore } from '@/store/uiStore';
import { initSocket, disconnectSocket } from '@/ws/socket';

import Sidebar from '@/components/Layout/Sidebar';
import TopBar from '@/components/Layout/TopBar';
import Login from '@/pages/Login';

import HomePage from '@/pages/Home';
import ConversationsPage from '@/pages/Conversations';
import TaskDecompositionPage from '@/pages/TaskDecomposition';
import AgentInteractionPage from '@/pages/AgentInteraction';
import JobsPage from '@/pages/Jobs';
import ToolStudioPage from '@/pages/ToolStudio';
import AgentStudioPage from '@/pages/AgentStudio';
import TeamStudioPage from '@/pages/TeamStudio';
import GraphPage from '@/pages/Graph';
import ScoringPage from '@/pages/Scoring';
import MemoryPage from '@/pages/Memory';
import DocumentsPage from '@/pages/Documents';
import ModelGovernancePage from '@/pages/ModelGovernance';
import MLInsightsPage from '@/pages/MLInsights';
import DataCatalogPage from '@/pages/DataCatalog';
import SettingsPage from '@/pages/Settings';

export default function App() {
  const themeMode = useUIStore((s) => s.themeMode);
  const theme = themeMode === 'dark' ? darkTheme : lightTheme;

  const [authenticated, setAuthenticated] = useState<boolean>(
    () => !!localStorage.getItem('pmos_token'),
  );

  const handleLoginSuccess = useCallback(() => {
    setAuthenticated(true);
  }, []);

  /** Call this from anywhere (e.g. TopBar) to log out. */
  const handleLogout = useCallback(() => {
    localStorage.removeItem('pmos_token');
    setAuthenticated(false);
  }, []);

  // Initialize WebSocket on mount (only when authenticated)
  useEffect(() => {
    if (!authenticated) return;
    initSocket();
    return () => {
      disconnectSocket();
    };
  }, [authenticated]);

  // Expose logout on the window so TopBar or other components can call it
  useEffect(() => {
    (window as unknown as Record<string, unknown>).__pmosLogout = handleLogout;
    return () => {
      delete (window as unknown as Record<string, unknown>).__pmosLogout;
    };
  }, [handleLogout]);

  if (!authenticated) {
    return (
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <Login onLoginSuccess={handleLoginSuccess} />
      </ThemeProvider>
    );
  }

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <Box sx={{ display: 'flex', minHeight: '100vh' }}>
        <TopBar />
        <Sidebar />
        <Box
          component="main"
          sx={{
            flexGrow: 1,
            display: 'flex',
            flexDirection: 'column',
            overflow: 'auto',
            bgcolor: 'background.default',
          }}
        >
          {/* Spacer for fixed AppBar */}
          <Toolbar />
          <Box sx={{ flex: 1, p: 3 }}>
            <Routes>
              <Route path="/" element={<HomePage />} />
              <Route path="/conversations" element={<ConversationsPage />} />
              <Route path="/conversations/:id/decomposition" element={<TaskDecompositionPage />} />
              <Route path="/conversations/:id/interactions" element={<AgentInteractionPage />} />
              <Route path="/task-decomposition" element={<TaskDecompositionPage />} />
              <Route path="/agent-interaction" element={<AgentInteractionPage />} />
              <Route path="/tool-studio" element={<ToolStudioPage />} />
              <Route path="/agent-studio" element={<AgentStudioPage />} />
              <Route path="/team-studio" element={<TeamStudioPage />} />
              <Route path="/jobs" element={<JobsPage />} />
              <Route path="/graph" element={<GraphPage />} />
              <Route path="/scoring" element={<ScoringPage />} />
              <Route path="/memory" element={<MemoryPage />} />
              <Route path="/documents" element={<DocumentsPage />} />
              <Route path="/model-governance" element={<ModelGovernancePage />} />
              <Route path="/ml-insights" element={<MLInsightsPage />} />
              <Route path="/data-catalog" element={<DataCatalogPage />} />
              <Route path="/settings" element={<SettingsPage />} />
              {/* Legacy redirects */}
              <Route path="/chat" element={<Navigate to="/conversations" replace />} />
              <Route path="/agents" element={<Navigate to="/agent-studio" replace />} />
              <Route path="/tools" element={<Navigate to="/tool-studio" replace />} />
            </Routes>
          </Box>
        </Box>
      </Box>
    </ThemeProvider>
  );
}
