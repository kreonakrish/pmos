import { useEffect, useMemo, useState } from 'react';
import {
  Box, Paper, Typography, Button, IconButton, Chip, Table, TableHead, TableRow, TableCell,
  TableBody, Dialog, DialogTitle, DialogContent, DialogActions, TextField, MenuItem,
  FormControl, InputLabel, Select, OutlinedInput, Checkbox, ListItemText, Alert, Snackbar,
  CircularProgress, Tooltip,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import EditIcon from '@mui/icons-material/Edit';
import DeleteIcon from '@mui/icons-material/Delete';
import VpnKeyIcon from '@mui/icons-material/VpnKey';
import BadgeIcon from '@mui/icons-material/Badge';
import {
  listUsers, listRoles, createUser, updateUser, deleteUser,
  setUserRoles, resetUserPassword, type AdminUser, type RoleWithPerms,
} from '@/api/adminUsers';
import { useAuthStore } from '@/store/authStore';

type DialogMode = null | { kind: 'create' } | { kind: 'edit'; user: AdminUser }
  | { kind: 'roles'; user: AdminUser } | { kind: 'reset'; user: AdminUser };

export default function AdminUsersPage() {
  const me = useAuthStore((s) => s.user);
  const has = useAuthStore((s) => s.has);

  const [users, setUsers] = useState<AdminUser[]>([]);
  const [roles, setRoles] = useState<RoleWithPerms[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [toast, setToast] = useState('');
  const [dialog, setDialog] = useState<DialogMode>(null);

  const canWrite  = has('users.write');
  const canDelete = has('users.delete');
  const canAssign = has('roles.assign');

  const refresh = async () => {
    setLoading(true); setError('');
    try {
      const [u, r] = await Promise.all([listUsers(), listRoles()]);
      setUsers(u); setRoles(r);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load users');
    } finally { setLoading(false); }
  };

  useEffect(() => { refresh(); }, []);

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
        <Typography variant="h5" fontWeight={700}>Users</Typography>
        <Box sx={{ ml: 'auto' }}>
          {canWrite && (
            <Button startIcon={<AddIcon />} variant="contained" onClick={() => setDialog({ kind: 'create' })}>
              New user
            </Button>
          )}
        </Box>
      </Box>

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      <Paper variant="outlined">
        {loading ? (
          <Box sx={{ p: 4, display: 'flex', justifyContent: 'center' }}><CircularProgress /></Box>
        ) : (
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Username</TableCell>
                <TableCell>Name</TableCell>
                <TableCell>Email</TableCell>
                <TableCell>Roles</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Last login</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {users.map((u) => (
                <TableRow key={u.id} hover>
                  <TableCell>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      {u.username}
                      {u.is_system && <Chip size="small" label="system" variant="outlined" />}
                      {u.id === me?.id && <Chip size="small" label="you" color="primary" variant="outlined" />}
                    </Box>
                  </TableCell>
                  <TableCell>{u.full_name ?? '—'}</TableCell>
                  <TableCell>{u.email}</TableCell>
                  <TableCell>
                    <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                      {u.roles.map((r) => <Chip key={r.id} size="small" label={r.name} />)}
                    </Box>
                  </TableCell>
                  <TableCell>
                    <Chip
                      size="small"
                      label={u.status}
                      color={u.status === 'active' ? 'success' : u.status === 'disabled' ? 'default' : 'error'}
                    />
                  </TableCell>
                  <TableCell>{u.last_login_at ? new Date(u.last_login_at).toLocaleString() : 'never'}</TableCell>
                  <TableCell align="right">
                    {canWrite && (
                      <Tooltip title="Edit user"><IconButton size="small" onClick={() => setDialog({ kind: 'edit', user: u })}><EditIcon fontSize="small" /></IconButton></Tooltip>
                    )}
                    {canAssign && (
                      <Tooltip title="Assign roles"><IconButton size="small" onClick={() => setDialog({ kind: 'roles', user: u })}><BadgeIcon fontSize="small" /></IconButton></Tooltip>
                    )}
                    {canWrite && (
                      <Tooltip title="Reset password"><IconButton size="small" onClick={() => setDialog({ kind: 'reset', user: u })}><VpnKeyIcon fontSize="small" /></IconButton></Tooltip>
                    )}
                    {canDelete && !u.is_system && u.id !== me?.id && (
                      <Tooltip title="Delete user"><IconButton size="small" onClick={async () => {
                        if (!confirm(`Delete user ${u.username}?`)) return;
                        try { await deleteUser(u.id); setToast('User deleted'); refresh(); }
                        catch (e: unknown) { setError(e instanceof Error ? e.message : 'Delete failed'); }
                      }}><DeleteIcon fontSize="small" /></IconButton></Tooltip>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Paper>

      {dialog?.kind === 'create' && (
        <CreateUserDialog roles={roles} onClose={() => setDialog(null)}
          onDone={(msg) => { setToast(msg); setDialog(null); refresh(); }} />
      )}
      {dialog?.kind === 'edit' && (
        <EditUserDialog user={dialog.user} onClose={() => setDialog(null)}
          onDone={(msg) => { setToast(msg); setDialog(null); refresh(); }} />
      )}
      {dialog?.kind === 'roles' && (
        <RolesDialog user={dialog.user} allRoles={roles} onClose={() => setDialog(null)}
          onDone={(msg) => { setToast(msg); setDialog(null); refresh(); }} />
      )}
      {dialog?.kind === 'reset' && (
        <ResetPasswordDialog user={dialog.user} onClose={() => setDialog(null)}
          onDone={(msg) => { setToast(msg); setDialog(null); }} />
      )}

      <Snackbar open={!!toast} autoHideDuration={3000} onClose={() => setToast('')}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}>
        <Alert severity="success" variant="filled" onClose={() => setToast('')}>{toast}</Alert>
      </Snackbar>
    </Box>
  );
}

// ---------------------- dialogs ----------------------
function CreateUserDialog({ roles, onClose, onDone }: {
  roles: RoleWithPerms[]; onClose: () => void; onDone: (msg: string) => void;
}) {
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [fullName, setFullName] = useState('');
  const [password, setPassword] = useState('');
  const [selectedRoles, setSelectedRoles] = useState<string[]>(['user']);
  const [mustChange, setMustChange] = useState(true);
  const [err, setErr] = useState(''); const [busy, setBusy] = useState(false);

  const save = async () => {
    setErr(''); setBusy(true);
    try {
      await createUser({
        username, email, full_name: fullName || undefined,
        password, roles: selectedRoles, must_change_password: mustChange,
      });
      onDone(`User '${username}' created`);
    } catch (e: unknown) {
      setErr(extractError(e, 'Create failed'));
    } finally { setBusy(false); }
  };

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Create user</DialogTitle>
      <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
        {err && <Alert severity="error">{err}</Alert>}
        <TextField label="Username" value={username} onChange={(e) => setUsername(e.target.value)} required />
        <TextField label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <TextField label="Full name" value={fullName} onChange={(e) => setFullName(e.target.value)} />
        <TextField label="Initial password" type="password" value={password}
          onChange={(e) => setPassword(e.target.value)}
          helperText="Minimum 8 characters" required />
        <RolesMultiSelect roles={roles} value={selectedRoles} onChange={setSelectedRoles} />
        <Box sx={{ display: 'flex', alignItems: 'center' }}>
          <Checkbox checked={mustChange} onChange={(e) => setMustChange(e.target.checked)} />
          <Typography variant="body2">User must change password on next login</Typography>
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={save}
          disabled={busy || !username || !email || password.length < 8}>
          {busy ? <CircularProgress size={20} /> : 'Create'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

function EditUserDialog({ user, onClose, onDone }: {
  user: AdminUser; onClose: () => void; onDone: (msg: string) => void;
}) {
  const [email, setEmail] = useState(user.email);
  const [fullName, setFullName] = useState(user.full_name ?? '');
  const [status, setStatus] = useState(user.status);
  const [err, setErr] = useState(''); const [busy, setBusy] = useState(false);

  const save = async () => {
    setErr(''); setBusy(true);
    try {
      await updateUser(user.id, { email, full_name: fullName || null, status });
      onDone('User updated');
    } catch (e: unknown) {
      setErr(extractError(e, 'Update failed'));
    } finally { setBusy(false); }
  };

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Edit user — {user.username}</DialogTitle>
      <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
        {err && <Alert severity="error">{err}</Alert>}
        <TextField label="Email" value={email} onChange={(e) => setEmail(e.target.value)} />
        <TextField label="Full name" value={fullName} onChange={(e) => setFullName(e.target.value)} />
        <TextField select label="Status" value={status}
          onChange={(e) => setStatus(e.target.value as typeof status)}>
          <MenuItem value="active">active</MenuItem>
          <MenuItem value="disabled">disabled</MenuItem>
          <MenuItem value="locked">locked</MenuItem>
        </TextField>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={save} disabled={busy}>
          {busy ? <CircularProgress size={20} /> : 'Save'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

function RolesDialog({ user, allRoles, onClose, onDone }: {
  user: AdminUser; allRoles: RoleWithPerms[]; onClose: () => void; onDone: (msg: string) => void;
}) {
  const [selected, setSelected] = useState<string[]>(user.roles.map((r) => r.name));
  const [err, setErr] = useState(''); const [busy, setBusy] = useState(false);

  const save = async () => {
    setErr(''); setBusy(true);
    try {
      await setUserRoles(user.id, selected);
      onDone(`Roles updated for ${user.username}`);
    } catch (e: unknown) {
      setErr(extractError(e, 'Update failed'));
    } finally { setBusy(false); }
  };

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Assign roles — {user.username}</DialogTitle>
      <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
        {err && <Alert severity="error">{err}</Alert>}
        <RolesMultiSelect roles={allRoles} value={selected} onChange={setSelected} />
        <Typography variant="caption" color="text.secondary">
          Effective permissions are the union of all assigned roles' permissions.
        </Typography>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={save} disabled={busy}>
          {busy ? <CircularProgress size={20} /> : 'Save'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

function ResetPasswordDialog({ user, onClose, onDone }: {
  user: AdminUser; onClose: () => void; onDone: (msg: string) => void;
}) {
  const [pw, setPw] = useState('');
  const [err, setErr] = useState(''); const [busy, setBusy] = useState(false);

  const save = async () => {
    if (pw.length < 8) { setErr('Password must be at least 8 characters.'); return; }
    setErr(''); setBusy(true);
    try {
      await resetUserPassword(user.id, pw);
      onDone(`Password reset for ${user.username}. User will be prompted to change it on next login.`);
    } catch (e: unknown) {
      setErr(extractError(e, 'Reset failed'));
    } finally { setBusy(false); }
  };

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>Reset password — {user.username}</DialogTitle>
      <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
        {err && <Alert severity="error">{err}</Alert>}
        <TextField label="New temporary password" type="password" value={pw}
          onChange={(e) => setPw(e.target.value)} autoFocus
          helperText="User must change on next login." />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={save} disabled={busy}>
          {busy ? <CircularProgress size={20} /> : 'Reset'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

function RolesMultiSelect({ roles, value, onChange }: {
  roles: RoleWithPerms[]; value: string[]; onChange: (v: string[]) => void;
}) {
  const byName = useMemo(() => Object.fromEntries(roles.map((r) => [r.name, r])), [roles]);
  return (
    <FormControl>
      <InputLabel>Roles</InputLabel>
      <Select
        multiple value={value}
        onChange={(e) => {
          const v = e.target.value;
          onChange(typeof v === 'string' ? v.split(',') : v);
        }}
        input={<OutlinedInput label="Roles" />}
        renderValue={(selected) => (
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
            {(selected as string[]).map((name) => <Chip key={name} label={name} size="small" />)}
          </Box>
        )}
      >
        {roles.map((r) => (
          <MenuItem key={r.id} value={r.name}>
            <Checkbox checked={value.indexOf(r.name) > -1} />
            <ListItemText primary={r.name} secondary={byName[r.name]?.description} />
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  );
}

function extractError(err: unknown, fallback: string): string {
  if (err && typeof err === 'object' && 'response' in err) {
    const ax = err as { response?: { data?: { error?: string }; status?: number } };
    return ax.response?.data?.error ?? `${fallback} (status ${ax.response?.status ?? 'unknown'})`;
  }
  return fallback;
}
