import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuthStore } from '../store/authStore';
import api from '../api/client';

export function LoginPage() {
  const { login, register, checkStatus, hasUser, isAuthenticated } = useAuthStore();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const inviteToken = searchParams.get('invite');
  const [inviteValid, setInviteValid] = useState<boolean | null>(null);
  const [showRegister, setShowRegister] = useState(false);

  useEffect(() => {
    checkStatus().catch(() => {
      setError('Unable to reach the server. Please check that the backend is running.');
    });
  }, []);

  useEffect(() => {
    if (inviteToken) {
      api.get(`/auth/invite/${inviteToken}`).then(({ data }) => {
        setInviteValid(data.valid);
        if (data.valid) setShowRegister(true);
      });
    }
  }, [inviteToken]);

  useEffect(() => {
    if (isAuthenticated) navigate('/projects');
  }, [isAuthenticated]);

  // First user (no users yet) = always show register
  const isFirstUser = hasUser === false;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      if (isFirstUser || showRegister) {
        await register(username, password, inviteToken || undefined);
      } else {
        await login(username, password);
      }
      navigate('/projects');
    } catch (err: any) {
      if (err.response?.data?.detail) {
        setError(err.response.data.detail);
      } else if (err.request && !err.response) {
        setError('Unable to reach the server. Please check your connection.');
      } else {
        setError('Authentication failed. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  };

  const title = isFirstUser
    ? 'Create your admin account'
    : showRegister
      ? 'Create your account'
      : 'Sign in';

  const buttonText = isFirstUser || showRegister ? 'Create Account' : 'Sign In';

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-900">
      <div className="bg-gray-800 p-8 rounded-lg shadow-xl w-full max-w-md">
        <h1 className="text-3xl font-bold text-white mb-2 text-center">SiegeEngine</h1>
        <p className="text-gray-400 text-center mb-6">{title}</p>

        {inviteToken && inviteValid === false && (
          <p className="text-red-400 text-sm text-center mb-4">
            This invite link is invalid or has expired.
          </p>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm text-gray-300 mb-1">Username</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full px-3 py-2 bg-gray-700 text-white rounded border border-gray-600 focus:border-blue-500 focus:outline-none"
              required
            />
          </div>
          <div>
            <label className="block text-sm text-gray-300 mb-1">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-3 py-2 bg-gray-700 text-white rounded border border-gray-600 focus:border-blue-500 focus:outline-none"
              required
            />
          </div>
          {error && (
            <div className="bg-red-900/40 border border-red-500/50 rounded px-3 py-2">
              <p className="text-red-400 text-sm">{error}</p>
            </div>
          )}
          <button
            type="submit"
            disabled={loading || (!!inviteToken && inviteValid === false)}
            className="w-full py-2 bg-blue-600 hover:bg-blue-700 text-white rounded font-medium disabled:opacity-50"
          >
            {loading ? '...' : buttonText}
          </button>
        </form>
      </div>
    </div>
  );
}
