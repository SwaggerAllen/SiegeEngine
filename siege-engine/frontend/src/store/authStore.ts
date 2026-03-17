import { create } from 'zustand';
import api from '../api/client';

interface AuthState {
  token: string | null;
  user: { id: string; username: string; role?: string } | null;
  isAuthenticated: boolean;
  hasUser: boolean | null;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string, inviteToken?: string) => Promise<void>;
  logout: () => void;
  checkStatus: () => Promise<void>;
  loadFromStorage: () => void;
  checkTokenExpiry: () => void;
}

function getInitialAuth(): { token: string | null; user: AuthState['user']; isAuthenticated: boolean } {
  try {
    const token = localStorage.getItem('siege_engine_token');
    const userStr = localStorage.getItem('siege_engine_user');
    if (token && userStr) {
      const payload = JSON.parse(atob(token.split('.')[1]));
      if (payload.exp && payload.exp * 1000 < Date.now()) {
        localStorage.removeItem('siege_engine_token');
        localStorage.removeItem('siege_engine_user');
        return { token: null, user: null, isAuthenticated: false };
      }
      return { token, user: JSON.parse(userStr), isAuthenticated: true };
    }
  } catch {
    localStorage.removeItem('siege_engine_token');
    localStorage.removeItem('siege_engine_user');
  }
  return { token: null, user: null, isAuthenticated: false };
}

const initialAuth = getInitialAuth();

export const useAuthStore = create<AuthState>((set) => ({
  token: initialAuth.token,
  user: initialAuth.user,
  isAuthenticated: initialAuth.isAuthenticated,
  hasUser: null,

  checkTokenExpiry: () => {
    const token = localStorage.getItem('siege_engine_token');
    if (!token) return;
    try {
      const payload = JSON.parse(atob(token.split('.')[1]));
      if (payload.exp && payload.exp * 1000 < Date.now()) {
        localStorage.removeItem('siege_engine_token');
        localStorage.removeItem('siege_engine_user');
        set({ token: null, user: null, isAuthenticated: false });
        window.location.href = '/login';
      }
    } catch {
      // Invalid token format — clear it
      localStorage.removeItem('siege_engine_token');
      localStorage.removeItem('siege_engine_user');
      set({ token: null, user: null, isAuthenticated: false });
    }
  },

  loadFromStorage: () => {
    const token = localStorage.getItem('siege_engine_token');
    const userStr = localStorage.getItem('siege_engine_user');
    if (token && userStr) {
      // Check expiry before loading
      try {
        const payload = JSON.parse(atob(token.split('.')[1]));
        if (payload.exp && payload.exp * 1000 < Date.now()) {
          localStorage.removeItem('siege_engine_token');
          localStorage.removeItem('siege_engine_user');
          return;
        }
      } catch {
        localStorage.removeItem('siege_engine_token');
        localStorage.removeItem('siege_engine_user');
        return;
      }
      set({
        token,
        user: JSON.parse(userStr),
        isAuthenticated: true,
      });
    }
  },

  checkStatus: async () => {
    const { data } = await api.get('/auth/status');
    set({ hasUser: data.has_user });
  },

  login: async (username, password) => {
    const { data } = await api.post('/auth/login', { username, password });
    localStorage.setItem('siege_engine_token', data.token);
    localStorage.setItem('siege_engine_user', JSON.stringify(data.user));
    set({ token: data.token, user: data.user, isAuthenticated: true });
  },

  register: async (username, password, inviteToken) => {
    const { data } = await api.post('/auth/register', {
      username,
      password,
      invite_token: inviteToken,
    });
    localStorage.setItem('siege_engine_token', data.token);
    localStorage.setItem('siege_engine_user', JSON.stringify(data.user));
    set({ token: data.token, user: data.user, isAuthenticated: true, hasUser: true });
  },

  logout: () => {
    localStorage.removeItem('siege_engine_token');
    localStorage.removeItem('siege_engine_user');
    set({ token: null, user: null, isAuthenticated: false });
  },
}));
