import { Box, Paper, Typography, Chip, Divider, Stack, Alert } from '@mui/material';
import { useAuthStore } from '@/store/authStore';

export default function MyAccessTab() {
  const user = useAuthStore((s) => s.user);
  const roles = useAuthStore((s) => s.roles);
  const permissions = useAuthStore((s) => Array.from(s.permissions).sort());

  if (!user) return <Alert severity="info">Sign in to view your access.</Alert>;

  // Group permissions by resource for readability
  const byResource: Record<string, string[]> = {};
  for (const p of permissions) {
    const [res] = p.split('.');
    (byResource[res] ||= []).push(p);
  }

  return (
    <Box>
      <Paper variant="outlined" sx={{ p: 3, mb: 3 }}>
        <Typography variant="h6" fontWeight={600} gutterBottom>Profile</Typography>
        <Stack spacing={1}>
          <Row label="Username" value={user.username} />
          <Row label="Full name" value={user.full_name ?? '—'} />
          <Row label="Email" value={user.email} />
          <Row label="Status" value={user.status} />
          <Row label="Last login" value={user.last_login_at ? new Date(user.last_login_at).toLocaleString() : 'never'} />
          <Row label="Created" value={new Date(user.created_at).toLocaleString()} />
        </Stack>
      </Paper>

      <Paper variant="outlined" sx={{ p: 3, mb: 3 }}>
        <Typography variant="h6" fontWeight={600} gutterBottom>Roles</Typography>
        {roles.length === 0 ? (
          <Alert severity="warning">You have no roles assigned. Ask an administrator to grant access.</Alert>
        ) : (
          <Stack spacing={1.5}>
            {roles.map((r) => (
              <Box key={r.id}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <Chip label={r.name} color="primary" variant="outlined" />
                  {r.is_system && <Chip label="system" size="small" variant="outlined" />}
                </Box>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                  {r.description}
                </Typography>
              </Box>
            ))}
          </Stack>
        )}
      </Paper>

      <Paper variant="outlined" sx={{ p: 3 }}>
        <Typography variant="h6" fontWeight={600} gutterBottom>Effective Permissions</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Union of permissions granted by all your roles ({permissions.length} total).
        </Typography>
        {Object.keys(byResource).sort().map((res) => (
          <Box key={res} sx={{ mb: 2 }}>
            <Typography variant="subtitle2" sx={{ textTransform: 'uppercase', color: 'text.secondary', mb: 0.5 }}>
              {res}
            </Typography>
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
              {byResource[res].map((p) => (
                <Chip key={p} label={p} size="small" variant="outlined" />
              ))}
            </Box>
            <Divider sx={{ mt: 1.5 }} />
          </Box>
        ))}
        {permissions.length === 0 && (
          <Alert severity="warning">No permissions granted.</Alert>
        )}
      </Paper>
    </Box>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <Box sx={{ display: 'flex', gap: 2 }}>
      <Typography variant="body2" color="text.secondary" sx={{ width: 120 }}>{label}</Typography>
      <Typography variant="body2">{value}</Typography>
    </Box>
  );
}
