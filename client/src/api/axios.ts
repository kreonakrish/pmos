import axios from 'axios';

// Resolution order:
//   1. window.__PMOS_CONFIG__.apiBaseUrl   (runtime, set by /config.js in prod container)
//   2. VITE_API_BASE_URL                   (build-time override)
//   3. '' (relative URLs — same-origin via Vite proxy in dev or nginx in prod)
const runtimeCfg = (typeof window !== 'undefined' && (window as any).__PMOS_CONFIG__) || {};
const API_BASE_URL: string = runtimeCfg.apiBaseUrl || import.meta.env.VITE_API_BASE_URL || '';

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
