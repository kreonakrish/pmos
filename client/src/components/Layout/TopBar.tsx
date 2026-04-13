import { useState } from 'react';
import {
  AppBar,
  Toolbar,
  Typography,
  IconButton,
  Box,
  Avatar,
  Menu,
  MenuItem,
  Divider,
  ListItemIcon,
  ListItemText,
  Chip,
  useTheme,
} from '@mui/material';
import MenuIcon from '@mui/icons-material/Menu';
import Brightness4Icon from '@mui/icons-material/Brightness4';
import Brightness7Icon from '@mui/icons-material/Brightness7';
import LogoutIcon from '@mui/icons-material/Logout';
import AccountCircleIcon from '@mui/icons-material/AccountCircle';
import VpnKeyIcon from '@mui/icons-material/VpnKey';
import { useNavigate } from 'react-router-dom';
import { useUIStore } from '@/store/uiStore';
import { useAuthStore } from '@/store/authStore';
import HealthBar from './HealthBar';

export default function TopBar() {
  const theme = useTheme();
  const navigate = useNavigate();
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);
  const toggleTheme = useUIStore((s) => s.toggleTheme);
  const themeMode = useUIStore((s) => s.themeMode);
  const user = useAuthStore((s) => s.user);
  const roles = useAuthStore((s) => s.roles);

  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null);
  const open = Boolean(anchorEl);

  const initials =
    (user?.full_name ?? user?.username ?? 'U')
      .split(/[\s_.-]+/)
      .map((w) => w.charAt(0))
      .join('')
      .slice(0, 2)
      .toUpperCase();

  const handleLogout = () => {
    setAnchorEl(null);
    const fn = (window as unknown as Record<string, () => void>).__pmosLogout;
    if (typeof fn === 'function') fn();
  };

  const go = (path: string) => {
    setAnchorEl(null);
    navigate(path);
  };

  return (
    <AppBar position="fixed" elevation={0} sx={{ zIndex: theme.zIndex.drawer + 1 }}>
      <Toolbar sx={{ gap: 2 }}>
        <IconButton edge="start" onClick={toggleSidebar} sx={{ color: theme.palette.text.primary }}>
          <MenuIcon />
        </IconButton>

        <Typography
          variant="h6" noWrap
          onClick={() => navigate('/')}
          sx={{
            fontWeight: 700,
            color: theme.palette.primary.main,
            letterSpacing: 1, cursor: 'pointer',
            '&:hover': { opacity: 0.8 },
          }}
        >
          PMOS
        </Typography>

        <Box sx={{ flex: 1, display: 'flex', justifyContent: 'center' }}>
          <HealthBar />
        </Box>

        <IconButton onClick={toggleTheme} sx={{ color: theme.palette.text.secondary }}>
          {themeMode === 'dark' ? <Brightness7Icon /> : <Brightness4Icon />}
        </IconButton>

        <IconButton onClick={(e) => setAnchorEl(e.currentTarget)} size="small" sx={{ ml: 0.5 }}>
          <Avatar sx={{ width: 32, height: 32, bgcolor: theme.palette.primary.main, fontSize: '0.875rem' }}>
            {initials}
          </Avatar>
        </IconButton>

        <Menu
          anchorEl={anchorEl} open={open} onClose={() => setAnchorEl(null)}
          anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
          transformOrigin={{ vertical: 'top', horizontal: 'right' }}
          slotProps={{ paper: { sx: { minWidth: 240, mt: 0.5 } } }}
        >
          <Box sx={{ px: 2, py: 1.5 }}>
            <Typography variant="subtitle2" fontWeight={700} noWrap>
              {user?.full_name || user?.username || 'Unknown user'}
            </Typography>
            {user?.email && (
              <Typography variant="caption" color="text.secondary" noWrap>
                {user.email}
              </Typography>
            )}
            <Box sx={{ mt: 1, display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
              {roles.map((r) => (
                <Chip key={r.id} label={r.name} size="small" variant="outlined" />
              ))}
              {roles.length === 0 && (
                <Chip label="no roles" size="small" color="warning" variant="outlined" />
              )}
            </Box>
          </Box>
          <Divider />
          <MenuItem onClick={() => go('/settings?tab=access')}>
            <ListItemIcon><AccountCircleIcon fontSize="small" /></ListItemIcon>
            <ListItemText>My Access</ListItemText>
          </MenuItem>
          <MenuItem onClick={() => go('/settings?tab=password')}>
            <ListItemIcon><VpnKeyIcon fontSize="small" /></ListItemIcon>
            <ListItemText>Change Password</ListItemText>
          </MenuItem>
          <Divider />
          <MenuItem onClick={handleLogout}>
            <ListItemIcon><LogoutIcon fontSize="small" /></ListItemIcon>
            <ListItemText>Sign out</ListItemText>
          </MenuItem>
        </Menu>
      </Toolbar>
    </AppBar>
  );
}
