import { useState, type FormEvent } from 'react';
import { Box, Paper, Typography, TextField, Button, Alert, CircularProgress } from '@mui/material';
import { changePassword } from '@/api/auth';

export default function ChangePasswordTab() {
  const [current, setCurrent] = useState('');
  const [next, setNext]       = useState('');
  const [confirm, setConfirm] = useState('');
  const [err, setErr]   = useState('');
  const [ok, setOk]     = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setErr(''); setOk('');
    if (next.length < 8)      { setErr('New password must be at least 8 characters.'); return; }
    if (next !== confirm)     { setErr('Passwords do not match.'); return; }
    setBusy(true);
    try {
      await changePassword(current, next);
      setOk('Password updated.');
      setCurrent(''); setNext(''); setConfirm('');
    } catch (e: unknown) {
      if (e && typeof e === 'object' && 'response' in e) {
        const ax = e as { response?: { data?: { error?: string } } };
        setErr(ax.response?.data?.error ?? 'Password change failed.');
      } else {
        setErr('Password change failed.');
      }
    } finally { setBusy(false); }
  };

  return (
    <Paper variant="outlined" sx={{ p: 3, maxWidth: 480 }}>
      <Typography variant="h6" fontWeight={600} gutterBottom>Change password</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Use a unique password of at least 8 characters.
      </Typography>
      {err && <Alert severity="error" sx={{ mb: 2 }}>{err}</Alert>}
      {ok  && <Alert severity="success" sx={{ mb: 2 }}>{ok}</Alert>}
      <Box component="form" onSubmit={submit} sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        <TextField label="Current password" type="password" autoComplete="current-password"
          value={current} onChange={(e) => setCurrent(e.target.value)} required />
        <TextField label="New password" type="password" autoComplete="new-password"
          value={next} onChange={(e) => setNext(e.target.value)} required />
        <TextField label="Confirm new password" type="password" autoComplete="new-password"
          value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
        <Button type="submit" variant="contained" disabled={busy || !current || !next || !confirm}
          sx={{ alignSelf: 'flex-start' }}>
          {busy ? <CircularProgress size={20} /> : 'Update password'}
        </Button>
      </Box>
    </Paper>
  );
}
