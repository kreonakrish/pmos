import { create } from 'zustand';

export interface Role {
  id: number;
  name: string;
  description: string;
  is_system: boolean;
}

export interface AuthUser {
  id: number;
  username: string;
  email: string;
  full_name: string | null;
  status: 'active' | 'disabled' | 'locked';
  must_change_password: boolean;
  last_login_at: string | null;
  created_at: string;
}

interface AuthState {
  user: AuthUser | null;
  roles: Role[];
  permissions: Set<string>;
  loaded: boolean; // true after /auth/me resolves at least once
  setAccess: (user: AuthUser, roles: Role[], permissions: string[]) => void;
  clear: () => void;
  has: (perm: string) => boolean;
  hasAny: (...perms: string[]) => boolean;
  hasAll: (...perms: string[]) => boolean;
  hasRole: (role: string) => boolean;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  roles: [],
  permissions: new Set(),
  loaded: false,
  setAccess: (user, roles, permissions) =>
    set({ user, roles, permissions: new Set(permissions), loaded: true }),
  clear: () =>
    set({ user: null, roles: [], permissions: new Set(), loaded: false }),
  has: (perm) => get().permissions.has(perm),
  hasAny: (...perms) => perms.some((p) => get().permissions.has(p)),
  hasAll: (...perms) => perms.every((p) => get().permissions.has(p)),
  hasRole: (role) => get().roles.some((r) => r.name === role),
}));
