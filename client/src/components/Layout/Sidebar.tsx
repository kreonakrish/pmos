import { useLocation, useNavigate } from 'react-router-dom';
import {
  Drawer,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Toolbar,
  Typography,
  Box,
  useTheme,
} from '@mui/material';
import ChatIcon from '@mui/icons-material/Chat';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import SwapHorizIcon from '@mui/icons-material/SwapHoriz';
import BuildIcon from '@mui/icons-material/Build';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import GroupsIcon from '@mui/icons-material/Groups';
import HubIcon from '@mui/icons-material/Hub';
import AnalyticsIcon from '@mui/icons-material/Analytics';
import MemoryIcon from '@mui/icons-material/Memory';
import DescriptionIcon from '@mui/icons-material/Description';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import PolicyIcon from '@mui/icons-material/Policy';
import ScienceIcon from '@mui/icons-material/Science';
import StorageIcon from '@mui/icons-material/Storage';
import SettingsIcon from '@mui/icons-material/Settings';
import PeopleIcon from '@mui/icons-material/People';
import VerifiedUserIcon from '@mui/icons-material/VerifiedUser';
import { useUIStore } from '@/store/uiStore';
import { useAuthStore } from '@/store/authStore';

const DRAWER_WIDTH_OPEN = 220;
const DRAWER_WIDTH_COLLAPSED = 64;

interface NavItem {
  label: string;
  path: string;
  icon: React.ReactElement;
  /** Item is shown only if the user has at least one of these permissions. Empty = always shown. */
  anyOf?: string[];
}

interface NavSection {
  title: string;
  items: NavItem[];
}

const NAV_SECTIONS: NavSection[] = [
  {
    title: 'Converse',
    items: [
      { label: 'Conversations',      path: '/conversations',      icon: <ChatIcon />,         anyOf: ['conversations.read'] },
      { label: 'Task Decomposition', path: '/task-decomposition', icon: <AccountTreeIcon />,  anyOf: ['conversations.read'] },
      { label: 'Agent Interaction',  path: '/agent-interaction',  icon: <SwapHorizIcon />,    anyOf: ['conversations.read'] },
    ],
  },
  {
    title: 'Build',
    items: [
      { label: 'Tool Studio',  path: '/tool-studio',  icon: <BuildIcon />,    anyOf: ['tools.read'] },
      { label: 'Agent Studio', path: '/agent-studio', icon: <SmartToyIcon />, anyOf: ['agents.read'] },
      { label: 'Team Studio',  path: '/team-studio',  icon: <GroupsIcon />,   anyOf: ['teams.read'] },
    ],
  },
  {
    title: 'Monitor',
    items: [
      { label: 'Pipeline Jobs',   path: '/jobs',      icon: <PlayArrowIcon />,  anyOf: ['jobs.read'] },
      { label: 'Live Graph',      path: '/graph',     icon: <HubIcon />,        anyOf: ['graph.read'] },
      { label: 'Scoring & RL',    path: '/scoring',   icon: <AnalyticsIcon />,  anyOf: ['scoring.read'] },
      { label: 'Memory Explorer', path: '/memory',    icon: <MemoryIcon />,     anyOf: ['memory.read'] },
      { label: 'Documents',       path: '/documents', icon: <DescriptionIcon />, anyOf: ['documents.read'] },
    ],
  },
  {
    title: 'Data Sources',
    items: [
      { label: 'Data Catalog', path: '/data-catalog', icon: <StorageIcon />, anyOf: ['catalog.read'] },
    ],
  },
  {
    title: 'Govern',
    items: [
      { label: 'Model Governance', path: '/model-governance', icon: <PolicyIcon />,  anyOf: ['models.read'] },
      { label: 'ML Insights',      path: '/ml-insights',      icon: <ScienceIcon />, anyOf: ['ml_insights.read'] },
    ],
  },
  {
    title: 'Administration',
    items: [
      { label: 'Users',  path: '/admin/users', icon: <PeopleIcon />,        anyOf: ['users.read'] },
      { label: 'Roles',  path: '/admin/roles', icon: <VerifiedUserIcon />,  anyOf: ['roles.read'] },
    ],
  },
  {
    title: 'System',
    items: [
      { label: 'Settings', path: '/settings', icon: <SettingsIcon /> },
    ],
  },
];

export default function Sidebar() {
  const theme = useTheme();
  const location = useLocation();
  const navigate = useNavigate();
  const collapsed = useUIStore((s) => s.sidebarCollapsed);
  const permissions = useAuthStore((s) => s.permissions);

  const width = collapsed ? DRAWER_WIDTH_COLLAPSED : DRAWER_WIDTH_OPEN;

  const canSee = (item: NavItem) =>
    !item.anyOf || item.anyOf.some((p) => permissions.has(p));

  const visibleSections = NAV_SECTIONS
    .map((s) => ({ ...s, items: s.items.filter(canSee) }))
    .filter((s) => s.items.length > 0);

  const isActive = (path: string) => {
    if (path === '/conversations') {
      return location.pathname === '/conversations' || location.pathname.startsWith('/conversations/');
    }
    return location.pathname.startsWith(path);
  };

  return (
    <Drawer
      variant="permanent"
      sx={{
        width,
        flexShrink: 0,
        '& .MuiDrawer-paper': {
          width,
          boxSizing: 'border-box',
          overflowX: 'hidden',
          transition: theme.transitions.create('width', {
            easing: theme.transitions.easing.sharp,
            duration: theme.transitions.duration.enteringScreen,
          }),
        },
      }}
    >
      {/* Spacer to push content below TopBar */}
      <Toolbar />

      <Box sx={{ px: collapsed ? 0.5 : 1, mt: 1 }}>
        {visibleSections.map((section) => (
          <Box key={section.title} sx={{ mb: 1.5 }}>
            {/* Section header */}
            {!collapsed && (
              <Typography
                variant="caption"
                sx={{
                  px: 1.5,
                  py: 0.5,
                  display: 'block',
                  color: 'text.secondary',
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  letterSpacing: 1,
                  fontSize: '0.625rem',
                }}
              >
                {section.title}
              </Typography>
            )}

            <List disablePadding>
              {section.items.map((item) => {
                const active = isActive(item.path);
                return (
                  <ListItemButton
                    key={item.path}
                    selected={active}
                    onClick={() => navigate(item.path)}
                    sx={{
                      borderRadius: 2,
                      mb: 0.25,
                      minHeight: 40,
                      justifyContent: collapsed ? 'center' : 'flex-start',
                      px: collapsed ? 1.5 : 2,
                      '&.Mui-selected': {
                        bgcolor: (t) =>
                          t.palette.mode === 'dark'
                            ? 'rgba(92, 156, 230, 0.12)'
                            : 'rgba(25, 118, 210, 0.08)',
                      },
                    }}
                  >
                    <ListItemIcon
                      sx={{
                        minWidth: collapsed ? 0 : 36,
                        color: active
                          ? theme.palette.primary.main
                          : theme.palette.text.secondary,
                        justifyContent: 'center',
                      }}
                    >
                      {item.icon}
                    </ListItemIcon>
                    {!collapsed && (
                      <ListItemText
                        primary={item.label}
                        primaryTypographyProps={{
                          fontSize: '0.8125rem',
                          fontWeight: active ? 600 : 400,
                          color: active
                            ? theme.palette.text.primary
                            : theme.palette.text.secondary,
                          noWrap: true,
                        }}
                      />
                    )}
                  </ListItemButton>
                );
              })}
            </List>
          </Box>
        ))}
      </Box>
    </Drawer>
  );
}
