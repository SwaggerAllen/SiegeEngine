import { useAuthStore } from './authStore';

// Mock the API client
vi.mock('../api/client', () => ({
  default: {
    post: vi.fn(),
    get: vi.fn(),
  },
}));

import api from '../api/client';

// Helper: create a fake JWT with a configurable payload
function fakeJWT(payload: Record<string, unknown>): string {
  const header = btoa(JSON.stringify({ alg: 'HS256' }));
  const body = btoa(JSON.stringify(payload));
  return `${header}.${body}.fake-signature`;
}

const futureExp = Math.floor(Date.now() / 1000) + 3600; // 1 hour from now
const pastExp = Math.floor(Date.now() / 1000) - 3600; // 1 hour ago
const validToken = fakeJWT({ sub: '1', exp: futureExp });
const expiredToken = fakeJWT({ sub: '1', exp: pastExp });
const testUser = { id: '1', username: 'admin' };

describe('authStore', () => {
  beforeEach(() => {
    useAuthStore.setState({
      token: null,
      user: null,
      isAuthenticated: false,
      hasUser: null,
    });
    vi.clearAllMocks();
  });

  describe('login', () => {
    it('sets token, user, isAuthenticated and writes localStorage', async () => {
      vi.mocked(api.post).mockResolvedValue({
        data: { token: validToken, user: testUser },
      });

      await useAuthStore.getState().login('admin', 'pass');

      const state = useAuthStore.getState();
      expect(state.token).toBe(validToken);
      expect(state.user).toEqual(testUser);
      expect(state.isAuthenticated).toBe(true);
      expect(localStorage.getItem('siege_engine_token')).toBe(validToken);
      expect(localStorage.getItem('siege_engine_user')).toBe(JSON.stringify(testUser));
    });

    it('does not set state if login API call rejects', async () => {
      vi.mocked(api.post).mockRejectedValue(new Error('401'));

      await expect(useAuthStore.getState().login('bad', 'creds')).rejects.toThrow();

      const state = useAuthStore.getState();
      expect(state.isAuthenticated).toBe(false);
      expect(state.token).toBeNull();
    });
  });

  describe('register', () => {
    it('sets token, user, isAuthenticated, and hasUser on success', async () => {
      vi.mocked(api.post).mockResolvedValue({
        data: { token: validToken, user: testUser },
      });

      await useAuthStore.getState().register('admin', 'pass', 'invite-123');

      const state = useAuthStore.getState();
      expect(state.token).toBe(validToken);
      expect(state.user).toEqual(testUser);
      expect(state.isAuthenticated).toBe(true);
      expect(state.hasUser).toBe(true);
      expect(vi.mocked(api.post)).toHaveBeenCalledWith('/auth/register', {
        username: 'admin',
        password: 'pass',
        invite_token: 'invite-123',
      });
    });
  });

  describe('logout', () => {
    it('clears token, user, isAuthenticated and localStorage', () => {
      // Pre-set authenticated state
      useAuthStore.setState({ token: validToken, user: testUser, isAuthenticated: true });
      localStorage.setItem('siege_engine_token', validToken);
      localStorage.setItem('siege_engine_user', JSON.stringify(testUser));

      useAuthStore.getState().logout();

      const state = useAuthStore.getState();
      expect(state.token).toBeNull();
      expect(state.user).toBeNull();
      expect(state.isAuthenticated).toBe(false);
      expect(localStorage.getItem('siege_engine_token')).toBeNull();
      expect(localStorage.getItem('siege_engine_user')).toBeNull();
    });
  });

  describe('loadFromStorage', () => {
    it('hydrates state from localStorage when token is valid', () => {
      localStorage.setItem('siege_engine_token', validToken);
      localStorage.setItem('siege_engine_user', JSON.stringify(testUser));

      useAuthStore.getState().loadFromStorage();

      const state = useAuthStore.getState();
      expect(state.token).toBe(validToken);
      expect(state.user).toEqual(testUser);
      expect(state.isAuthenticated).toBe(true);
    });

    it('does NOT hydrate when token is expired', () => {
      localStorage.setItem('siege_engine_token', expiredToken);
      localStorage.setItem('siege_engine_user', JSON.stringify(testUser));

      useAuthStore.getState().loadFromStorage();

      const state = useAuthStore.getState();
      expect(state.isAuthenticated).toBe(false);
      expect(state.token).toBeNull();
      expect(localStorage.getItem('siege_engine_token')).toBeNull();
    });

    it('clears storage on malformed token', () => {
      localStorage.setItem('siege_engine_token', 'not-a-jwt');
      localStorage.setItem('siege_engine_user', JSON.stringify(testUser));

      useAuthStore.getState().loadFromStorage();

      const state = useAuthStore.getState();
      expect(state.isAuthenticated).toBe(false);
      expect(localStorage.getItem('siege_engine_token')).toBeNull();
    });

    it('does nothing when localStorage is empty', () => {
      useAuthStore.getState().loadFromStorage();

      const state = useAuthStore.getState();
      expect(state.isAuthenticated).toBe(false);
      expect(state.token).toBeNull();
    });
  });

  describe('checkTokenExpiry', () => {
    it('clears state when token is expired', () => {
      localStorage.setItem('siege_engine_token', expiredToken);
      useAuthStore.setState({ token: expiredToken, user: testUser, isAuthenticated: true });

      useAuthStore.getState().checkTokenExpiry();

      const state = useAuthStore.getState();
      expect(state.isAuthenticated).toBe(false);
      expect(state.token).toBeNull();
      expect(localStorage.getItem('siege_engine_token')).toBeNull();
    });

    it('does nothing when no token exists', () => {
      useAuthStore.getState().checkTokenExpiry();

      const state = useAuthStore.getState();
      expect(state.isAuthenticated).toBe(false);
    });

    it('clears state on malformed token in localStorage', () => {
      localStorage.setItem('siege_engine_token', 'broken');
      useAuthStore.setState({ token: 'broken', isAuthenticated: true, user: testUser });

      useAuthStore.getState().checkTokenExpiry();

      const state = useAuthStore.getState();
      expect(state.isAuthenticated).toBe(false);
      expect(state.token).toBeNull();
    });
  });

  describe('checkStatus', () => {
    it('sets hasUser from API response', async () => {
      vi.mocked(api.get).mockResolvedValue({ data: { has_user: true } });

      await useAuthStore.getState().checkStatus();

      expect(useAuthStore.getState().hasUser).toBe(true);
    });
  });
});
