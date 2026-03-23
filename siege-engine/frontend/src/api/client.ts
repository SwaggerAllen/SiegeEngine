import axios from 'axios';
import { useErrorLogStore } from '../store/errorLogStore';

const api = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('siege_engine_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    // Log all API errors to the error log for mobile debugging
    const url = error.config?.url || 'unknown';
    const method = (error.config?.method || 'unknown').toUpperCase();
    const status = error.response?.status;
    const label = status
      ? `API ${status} ${method} ${url}`
      : `API Network Error ${method} ${url}`;
    useErrorLogStore.getState().pushError(label, error.message || error);

    if (error.response?.status === 401) {
      // Don't intercept 401s from auth endpoints — let LoginPage handle those
      const url = error.config?.url || '';
      if (!url.startsWith('/auth/login') && !url.startsWith('/auth/register')) {
        localStorage.removeItem('siege_engine_token');
        localStorage.removeItem('siege_engine_user');
        import('../store/authStore')
          .then(({ useAuthStore }) => {
            useAuthStore.getState().logout();
          })
          .catch(() => {}); // prevent unhandled rejection if import fails during redirect
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

export default api;
