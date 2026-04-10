import {
  AppBar,
  Toolbar,
  Typography,
  IconButton,
  Box,
  Avatar,
  useTheme,
} from '@mui/material';
import MenuIcon from '@mui/icons-material/Menu';
import Brightness4Icon from '@mui/icons-material/Brightness4';
import Brightness7Icon from '@mui/icons-material/Brightness7';
import { useNavigate } from 'react-router-dom';
import { useUIStore } from '@/store/uiStore';
import HealthBar from './HealthBar';

export default function TopBar() {
  const theme = useTheme();
  const navigate = useNavigate();
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);
  const toggleTheme = useUIStore((s) => s.toggleTheme);
  const themeMode = useUIStore((s) => s.themeMode);

  return (
    <AppBar
      position="fixed"
      elevation={0}
      sx={{
        zIndex: theme.zIndex.drawer + 1,
      }}
    >
      <Toolbar sx={{ gap: 2 }}>
        {/* Sidebar toggle */}
        <IconButton
          edge="start"
          onClick={toggleSidebar}
          sx={{ color: theme.palette.text.primary }}
        >
          <MenuIcon />
        </IconButton>

        {/* Logo / Title */}
        <Typography
          variant="h6"
          noWrap
          onClick={() => navigate('/')}
          sx={{
            fontWeight: 700,
            color: theme.palette.primary.main,
            letterSpacing: 1,
            cursor: 'pointer',
            '&:hover': { opacity: 0.8 },
          }}
        >
          PMOS
        </Typography>

        {/* Center: Health bar */}
        <Box sx={{ flex: 1, display: 'flex', justifyContent: 'center' }}>
          <HealthBar />
        </Box>

        {/* Right: theme toggle + avatar */}
        <IconButton
          onClick={toggleTheme}
          sx={{ color: theme.palette.text.secondary }}
        >
          {themeMode === 'dark' ? <Brightness7Icon /> : <Brightness4Icon />}
        </IconButton>

        <Avatar
          sx={{
            width: 32,
            height: 32,
            bgcolor: theme.palette.primary.main,
            fontSize: '0.875rem',
          }}
        >
          U
        </Avatar>
      </Toolbar>
    </AppBar>
  );
}
