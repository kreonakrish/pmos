import apiClient from './axios';
import type { AuthUser, Role } from '@/store/authStore';

export interface AdminUser extends AuthUser {
  roles: Role[];
  permissions: string[];
  is_system: boolean;
}

export interface RoleWithPerms {
  id: number;
  name: string;
  description: string;
  is_system: boolean;
  permissions: string[];
}

export interface Permission {
  id: number;
  name: string;
  resource: string;
  action: string;
  description: string;
}

export async function listUsers(): Promise<AdminUser[]> {
  const { data } = await apiClient.get<{ users: AdminUser[] }>('/v1/users');
  return data.users;
}

export async function listRoles(): Promise<RoleWithPerms[]> {
  const { data } = await apiClient.get<{ roles: RoleWithPerms[] }>('/v1/roles');
  return data.roles;
}

export async function listPermissions(): Promise<Permission[]> {
  const { data } = await apiClient.get<{ permissions: Permission[] }>('/v1/permissions');
  return data.permissions;
}

export async function createUser(body: {
  username: string;
  email: string;
  full_name?: string;
  password: string;
  roles?: string[];
  must_change_password?: boolean;
}): Promise<AdminUser> {
  const { data } = await apiClient.post<AdminUser>('/v1/users', body);
  return data;
}

export async function updateUser(id: number, body: {
  email?: string;
  full_name?: string | null;
  status?: 'active' | 'disabled' | 'locked';
}): Promise<AdminUser> {
  const { data } = await apiClient.patch<AdminUser>(`/v1/users/${id}`, body);
  return data;
}

export async function setUserRoles(id: number, roles: string[]): Promise<void> {
  await apiClient.put(`/v1/users/${id}/roles`, { roles });
}

export async function resetUserPassword(id: number, new_password: string): Promise<void> {
  await apiClient.post(`/v1/users/${id}/reset-password`, { new_password });
}

export async function deleteUser(id: number): Promise<void> {
  await apiClient.delete(`/v1/users/${id}`);
}
