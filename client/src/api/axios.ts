import axios from 'axios';

// In dev mode, use empty baseURL so requests go through Vite's proxy (/v1 → localhost:4000)
// In production (Docker/nginx), the proxy is handled by nginx.conf
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '';

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30_000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor: attach JWT token if available
apiClient.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('pmos_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error),
);

// Response interceptor: handle 401
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('pmos_token');
      window.location.reload();
    }
    return Promise.reject(error);
  },
);

export default apiClient;
