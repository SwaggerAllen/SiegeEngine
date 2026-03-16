import { useEffect, useState } from 'react';
import api from '../../api/client';

interface GitHubStatus {
  connected: boolean;
  github_username?: string;
}

export function ProjectSettingsPanel({ projectId }: { projectId: string }) {
  const [remoteUrl, setRemoteUrl] = useState('');
  const [repoSlug, setRepoSlug] = useState('');
  const [autoPush, setAutoPush] = useState(false);
  const [ghStatus, setGhStatus] = useState<GitHubStatus | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');

  useEffect(() => {
    // Load project details for current remote config
    api.get(`/projects/${projectId}`).then(({ data }) => {
      setRemoteUrl(data.remote_url || '');
      setRepoSlug(data.github_repo_slug || '');
      setAutoPush(data.auto_push_enabled || false);
    }).catch(() => setMessage('Failed to load project settings'));
    // Check GitHub connection
    api.get('/github/status').then(({ data }) => setGhStatus(data)).catch(() => {});
  }, [projectId]);

  const saveRemote = async () => {
    setSaving(true);
    setMessage('');
    try {
      await api.post(`/projects/${projectId}/remote`, {
        remote_url: remoteUrl,
        github_repo_slug: repoSlug,
        auto_push_enabled: autoPush,
      });
      setMessage('Remote saved');
    } catch (err: any) {
      setMessage(err.response?.data?.detail || 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  const connectGitHub = async () => {
    try {
      const { data } = await api.get('/github/authorize');
      // Open popup for GitHub OAuth
      const popup = window.open(data.authorize_url, 'github-oauth', 'width=600,height=700');

      // Listen for the callback page to post the code back
      const handleMessage = async (event: MessageEvent) => {
        if (event.origin !== window.location.origin) return;
        if (event.data?.type !== 'github-oauth') return;
        window.removeEventListener('message', handleMessage);
        const { code, state } = event.data;
        if (code && state) {
          try {
            const { data: result } = await api.post('/github/connect', { code, state });
            setGhStatus({ connected: true, github_username: result.github_username });
          } catch {
            setMessage('Failed to complete GitHub connection');
          }
        }
      };
      window.addEventListener('message', handleMessage);

      // Clean up listener if popup is closed without completing
      const checkClosed = setInterval(() => {
        if (!popup || popup.closed) {
          clearInterval(checkClosed);
          window.removeEventListener('message', handleMessage);
        }
      }, 1000);
    } catch {
      setMessage('Failed to start GitHub connection');
    }
  };

  return (
    <div className="p-4 max-w-xl space-y-6">
      <h2 className="text-lg font-bold text-white">Project Settings</h2>

      <div className="space-y-3">
        <h3 className="text-sm font-medium text-gray-300">Git Remote</h3>
        <div>
          <label className="block text-xs text-gray-400 mb-1">Remote URL</label>
          <input
            value={remoteUrl}
            onChange={(e) => setRemoteUrl(e.target.value)}
            placeholder="https://github.com/owner/repo.git"
            className="w-full px-3 py-2 bg-gray-700 text-white rounded border border-gray-600 focus:border-blue-500 focus:outline-none text-sm"
          />
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1">
            GitHub Repo Slug (owner/repo)
          </label>
          <input
            value={repoSlug}
            onChange={(e) => setRepoSlug(e.target.value)}
            placeholder="owner/repo"
            className="w-full px-3 py-2 bg-gray-700 text-white rounded border border-gray-600 focus:border-blue-500 focus:outline-none text-sm"
          />
        </div>
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={autoPush}
            onChange={(e) => setAutoPush(e.target.checked)}
            className="w-4 h-4 rounded border-gray-500 bg-gray-700 text-blue-500 focus:ring-blue-500 focus:ring-offset-0"
          />
          <span className="text-sm text-gray-300">Auto-push after each completed run</span>
        </label>
        <button
          onClick={saveRemote}
          disabled={saving}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded disabled:opacity-50"
        >
          {saving ? 'Saving...' : 'Save Remote'}
        </button>
        {message && <p className="text-sm text-green-400">{message}</p>}
      </div>

      <div className="space-y-3 border-t border-gray-700 pt-4">
        <h3 className="text-sm font-medium text-gray-300">GitHub Connection</h3>
        {ghStatus?.connected ? (
          <p className="text-sm text-green-400">
            Connected as @{ghStatus.github_username}
          </p>
        ) : (
          <div>
            <p className="text-sm text-gray-400 mb-2">
              Connect your GitHub account to push branches and open PRs.
            </p>
            <button
              onClick={connectGitHub}
              className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white text-sm rounded"
            >
              Connect GitHub
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
