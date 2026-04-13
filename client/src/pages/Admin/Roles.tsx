import { useEffect, useState } from 'react';
import {
  Box, Paper, Typography, Accordion, AccordionSummary, AccordionDetails, Chip,
  CircularProgress, Alert,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { listRoles, type RoleWithPerms } from '@/api/adminUsers';

export default function AdminRolesPage() {
  const [roles, setRoles] = useState<RoleWithPerms[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    (async () => {
      try { setRoles(await listRoles()); }
      catch (e: unknown) { setError(e instanceof Error ? e.message : 'Failed to load roles'); }
      finally { setLoading(false); }
    })();
  }, []);

  return (
    <Box>
      <Typography variant="h5" fontWeight={700} sx={{ mb: 2 }}>Roles & Permissions</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        System-defined roles and the permissions each one grants. To change which roles a user holds,
        use the Users admin page.
      </Typography>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {loading ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}><CircularProgress /></Box>
      ) : (
        <Paper variant="outlined">
          {roles.map((r) => (
            <Accordion key={r.id} disableGutters elevation={0} square
              sx={{ '&:before': { display: 'none' }, borderTop: (t) => `1px solid ${t.palette.divider}` }}>
              <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%' }}>
                  <Typography fontWeight={600}>{r.name}</Typography>
                  {r.is_system && <Chip label="system" size="small" variant="outlined" />}
                  <Typography variant="body2" color="text.secondary" sx={{ ml: 1 }}>
                    {r.description}
                  </Typography>
                  <Box sx={{ ml: 'auto' }}>
                    <Chip label={`${r.permissions.length} permissions`} size="small" />
                  </Box>
                </Box>
              </AccordionSummary>
              <AccordionDetails>
                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.75 }}>
                  {r.permissions.map((p) => (
                    <Chip key={p} label={p} size="small" variant="outlined" />
                  ))}
                  {r.permissions.length === 0 && (
                    <Typography variant="body2" color="text.secondary">
                      No permissions granted.
                    </Typography>
                  )}
                </Box>
              </AccordionDetails>
            </Accordion>
          ))}
        </Paper>
      )}
    </Box>
  );
}
