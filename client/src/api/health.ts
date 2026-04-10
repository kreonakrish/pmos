import { useQuery } from '@tanstack/react-query';
import apiClient from '@/api/axios';
import type { HealthStatus } from '@/types';

export function useHealthStatus() {
  return useQuery<Record<string, unknown>>({
    queryKey: ['health'],
    queryFn: async () => {
      const { data } = await apiClient.get('/health');
      return data;
    },
    refetchInterval: 30_000,
  });
}

export function useHealth() {
  return useQuery<HealthStatus>({
    queryKey: ['health-aggregated'],
    queryFn: async () => {
      const { data } = await apiClient.get('/health');
      return data;
    },
    refetchInterval: 30_000,
  });
}
