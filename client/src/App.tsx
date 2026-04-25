import { useCallback, useEffect, useState } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { ThemeProvider, CssBaseline, Box, Toolbar } from '@mui/material';
import { darkTheme, lightTheme } from '@/theme';
import { useUIStore } from '@/store/uiStore';
import { initSocket, disconnectSocket } from '@/ws/socket';

import Sidebar from '@/components/Layout/Sidebar';
import TopBar from '@/components/Layout/TopBar';
import Login from '@/pages/Login';
import { fetchMe, logoutClient } from '@/api/auth';
import { useAuthStore } from '@/store/authStore';
import PermissionGate from '@/components/Auth/PermissionGate';
import AdminUsersPage from '@/pages/Admin/Users';
import AdminRolesPage from '@/pages/Admin/Roles';

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
import AuditorIssuesPage from '@/pages/AuditorIssues';
import MLInsightsPage from '@/pages/MLInsights';
import DataCatalogPage from '@/pages/DataCatalog';
import SchemaGraphPage from '@/pages/SchemaGraph';
import TranslatorPage from '@/pages/Translator';
import SettingsPage from '@/pages/Settings';
import LogsPage from '@/pages/Logs';

export default function App() {
  const themeMode = useUIStore((s) => s.themeMode);
  const theme = themeMode === 'dark' ? darkTheme : lightTheme;

  const [authenticated, setAuthenticated] = useState<boolean>(
    () => !!localStorage.getItem('pmos_token'),
  );
  const authLoaded = useAuthStore((s) => s.loaded);

  // Hydrate /auth/me whenever we're authenticated but the store has no access yet
  useEffect(() => {
    if (!authenticated || authLoaded) return;
    fetchMe().catch(() => {
      // token invalid/stale → force logout
      logoutClient();
      setAuthenticated(false);
    });
  }, [authenticated, authLoaded]);

  const handleLoginSuccess = useCallback(() => {
    setAuthenticated(true);
  }, []);

  /** Call this from anywhere (e.g. TopBar) to log out. */
  const handleLogout = useCallback(() => {
    logoutClient();
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
              <Route path="/conversations" element={
                <PermissionGate anyOf={['conversations.read']} redirect><ConversationsPage /></PermissionGate>
              } />
              <Route path="/conversations/:id/decomposition" element={
                <PermissionGate anyOf={['conversations.read']} redirect><TaskDecompositionPage /></PermissionGate>
              } />
              <Route path="/conversations/:id/interactions" element={
                <PermissionGate anyOf={['conversations.read']} redirect><AgentInteractionPage /></PermissionGate>
              } />
              <Route path="/task-decomposition" element={
                <PermissionGate anyOf={['conversations.read']} redirect><TaskDecompositionPage /></PermissionGate>
              } />
              <Route path="/agent-interaction" element={
                <PermissionGate anyOf={['conversations.read']} redirect><AgentInteractionPage /></PermissionGate>
              } />
              <Route path="/tool-studio" element={
                <PermissionGate anyOf={['tools.read']} redirect><ToolStudioPage /></PermissionGate>
              } />
              <Route path="/agent-studio" element={
                <PermissionGate anyOf={['agents.read']} redirect><AgentStudioPage /></PermissionGate>
              } />
              <Route path="/team-studio" element={
                <PermissionGate anyOf={['teams.read']} redirect><TeamStudioPage /></PermissionGate>
              } />
              <Route path="/jobs" element={
                <PermissionGate anyOf={['jobs.read']} redirect><JobsPage /></PermissionGate>
              } />
              <Route path="/graph" element={
                <PermissionGate anyOf={['graph.read']} redirect><GraphPage /></PermissionGate>
              } />
              <Route path="/scoring" element={
                <PermissionGate anyOf={['scoring.read']} redirect><ScoringPage /></PermissionGate>
              } />
              <Route path="/memory" element={
                <PermissionGate anyOf={['memory.read']} redirect><MemoryPage /></PermissionGate>
              } />
              <Route path="/documents" element={
                <PermissionGate anyOf={['documents.read']} redirect><DocumentsPage /></PermissionGate>
              } />
              <Route path="/model-governance" element={
                <PermissionGate anyOf={['models.read']} redirect><ModelGovernancePage /></PermissionGate>
              } />
              <Route path="/auditor-issues" element={
                <PermissionGate anyOf={['models.read']} redirect><AuditorIssuesPage /></PermissionGate>
              } />
              <Route path="/ml-insights" element={
                <PermissionGate anyOf={['ml_insights.read']} redirect><MLInsightsPage /></PermissionGate>
              } />
              <Route path="/data-catalog" element={
                <PermissionGate anyOf={['catalog.read']} redirect><DataCatalogPage /></PermissionGate>
              } />
              <Route path="/schema-graph" element={
                <PermissionGate anyOf={['catalog.read']} redirect><SchemaGraphPage /></PermissionGate>
              } />
              <Route path="/translator" element={
                <PermissionGate anyOf={['catalog.read']} redirect><TranslatorPage /></PermissionGate>
              } />
              <Route path="/logs" element={
                <PermissionGate anyOf={['logs.read']} redirect><LogsPage /></PermissionGate>
              } />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="/admin/users" element={
                <PermissionGate anyOf={['users.read']} redirect><AdminUsersPage /></PermissionGate>
              } />
              <Route path="/admin/roles" element={
                <PermissionGate anyOf={['roles.read']} redirect><AdminRolesPage /></PermissionGate>
              } />
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
