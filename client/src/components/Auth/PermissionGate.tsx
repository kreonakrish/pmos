import React from 'react';
import { Navigate } from 'react-router-dom';
import { Box, Alert, Typography } from '@mui/material';
import { useAuthStore } from '@/store/authStore';

interface PermissionGateProps {
  /** All of these permissions must be held. */
  allOf?: string[];
  /** At least one of these permissions must be held. */
  anyOf?: string[];
  /** Role-based gate (alternative to permission-based). */
  role?: string;
  /** When used to gate a route, redirect to / if no access. */
  redirect?: boolean;
  /** Inline content to show when access is denied (default: Alert). */
  fallback?: React.ReactNode;
  children: React.ReactNode;
}

/**
 * Render its children only if the authenticated user satisfies the access
 * requirement. When `redirect` is true, an unauthorized access sends the user
 * to the home page (used for route-level gating). Otherwise, renders `fallback`
 * (or a default Alert) in place.
 */
export default function PermissionGate({
  allOf,
  anyOf,
  role,
  redirect = false,
  fallback,
  children,
}: PermissionGateProps) {
  const loaded      = useAuthStore((s) => s.loaded);
  const permissions = useAuthStore((s) => s.permissions);
  const roles       = useAuthStore((s) => s.roles);

  if (!loaded) return null; // wait for /auth/me

  const hasAll = !allOf || allOf.every((p) => permissions.has(p));
  const hasAny = !anyOf || anyOf.some((p) => permissions.has(p));
  const hasRole = !role  || roles.some((r) => r.name === role);
  const authorized = hasAll && hasAny && hasRole;

  if (authorized) return <>{children}</>;

  if (redirect) return <Navigate to="/" replace />;

  if (fallback) return <>{fallback}</>;

  return (
    <Box sx={{ p: 3 }}>
      <Alert severity="warning">
        <Typography variant="body2">
          You do not have permission to view this page. Contact your administrator
          if you believe this is a mistake.
        </Typography>
      </Alert>
    </Box>
  );
}
