import { useState, type FormEvent } from 'react';
import {
  Box,
  Card,
  CardContent,
  TextField,
  Button,
  Typography,
  Alert,
  CircularProgress,
} from '@mui/material';
import LockOutlinedIcon from '@mui/icons-material/LockOutlined';
import { login, fetchMe, changePassword } from '@/api/auth';

interface LoginProps {
  onLoginSuccess: () => void;
}

export default function Login({ onLoginSuccess }: LoginProps) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [mustChangeStep, setMustChangeStep] = useState(false);
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  function extractError(err: unknown, fallback: string): string {
    if (err && typeof err === 'object' && 'response' in err) {
      const axiosErr = err as { response?: { data?: { error?: string }; status?: number } };
      return axiosErr.response?.data?.error ?? `${fallback} (status ${axiosErr.response?.status ?? 'unknown'})`;
    }
    return 'Unable to connect to the server. Please try again.';
  }

  const finishLogin = async () => {
    await fetchMe();
    onLoginSuccess();
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await login(username, password);
      if (res.user.must_change_password) {
        setMustChangeStep(true);
        setLoading(false);
        return;
      }
      await finishLogin();
    } catch (err: unknown) {
      setError(extractError(err, 'Login failed'));
    } finally {
      setLoading(false);
    }
  };

  const handleChangePassword = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    if (newPassword.length < 8) { setError('New password must be at least 8 characters.'); return; }
    if (newPassword !== confirmPassword) { setError('Passwords do not match.'); return; }
    setLoading(true);
    try {
      await changePassword(password, newPassword);
      await finishLogin();
    } catch (err: unknown) {
      setError(extractError(err, 'Password change failed'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box
      sx={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        bgcolor: 'background.default',
      }}
    >
      <Card
        elevation={8}
        sx={{
          width: '100%',
          maxWidth: 420,
          mx: 2,
        }}
      >
        <CardContent sx={{ p: 4 }}>
          <Box
            sx={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              mb: 3,
            }}
          >
            <Box
              sx={{
                width: 48,
                height: 48,
                borderRadius: '50%',
                bgcolor: 'primary.main',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                mb: 2,
              }}
            >
              <LockOutlinedIcon sx={{ color: 'primary.contrastText' }} />
            </Box>
            <Typography variant="h4" component="h1" fontWeight={700}>
              PMOS
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
              Perpetual Multi-Agent Orchestration System
            </Typography>
          </Box>

          {error && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {error}
            </Alert>
          )}

          {!mustChangeStep ? (
            <Box component="form" onSubmit={handleSubmit} noValidate>
              <TextField
                label="Username"
                fullWidth required autoFocus autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                sx={{ mb: 2 }}
              />
              <TextField
                label="Password" type="password"
                fullWidth required autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                sx={{ mb: 3 }}
              />
              <Button type="submit" variant="contained" fullWidth size="large"
                disabled={loading || !username || !password}>
                {loading ? <CircularProgress size={24} color="inherit" /> : 'Sign In'}
              </Button>
            </Box>
          ) : (
            <Box component="form" onSubmit={handleChangePassword} noValidate>
              <Alert severity="info" sx={{ mb: 2 }}>
                You must set a new password before continuing.
              </Alert>
              <TextField
                label="New password" type="password"
                fullWidth required autoFocus autoComplete="new-password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                helperText="Minimum 8 characters"
                sx={{ mb: 2 }}
              />
              <TextField
                label="Confirm new password" type="password"
                fullWidth required autoComplete="new-password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                sx={{ mb: 3 }}
              />
              <Button type="submit" variant="contained" fullWidth size="large"
                disabled={loading || !newPassword || !confirmPassword}>
                {loading ? <CircularProgress size={24} color="inherit" /> : 'Set new password'}
              </Button>
            </Box>
          )}
        </CardContent>
      </Card>
    </Box>
  );
}
