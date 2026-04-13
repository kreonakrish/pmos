import apiClient from './axios';
import { useAuthStore, type AuthUser, type Role } from '@/store/authStore';

export interface LoginResponse {
  token: string;
  user: { sub: string; uid: number; roles: string[]; permissions: string[]; must_change_password?: boolean };
  expires_in: number;
}

export async function login(username: string, password: string): Promise<LoginResponse> {
  const { data } = await apiClient.post<LoginResponse>('/v1/auth/login', { username, password });
  localStorage.setItem('pmos_token', data.token);
  return data;
}

export async function fetchMe(): Promise<{ user: AuthUser; roles: Role[]; permissions: string[] }> {
  const { data } = await apiClient.get<{ user: AuthUser; roles: Role[]; permissions: string[] }>('/v1/auth/me');
  useAuthStore.getState().setAccess(data.user, data.roles, data.permissions);
  return data;
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  await apiClient.post('/v1/auth/change-password', {
    current_password: currentPassword,
    new_password: newPassword,
  });
}

export function logoutClient(): void {
  localStorage.removeItem('pmos_token');
  useAuthStore.getState().clear();
}
