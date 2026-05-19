import { useEffect, useState } from 'react';
import api from '../api/client';
import { describeApiError } from '../lib/describeApiError';
import { useProject } from '../hooks/queries/useProjectQueries';
import { useQueryClient } from '@tanstack/react-query';
import { projectKeys } from '../hooks/queries/useProjectQueries';

/**
 * Per-project remote-repo wire-up. Lives on Project Settings as the
 * backfill path for projects created before the create-page gained
 * the "GitHub repo URL" field — and as the edit path for any project
 * that needs to be repointed.
 *
 * Hits POST /api/projects/{id}/remote which sets remote_url +
 * github_repo_slug + auto_push_enabled on the Project row and calls
 * git_manager.add_remote on the local clone.
 */

// Client-side mirror of backend.projects.service.derive_github_slug.
// Backend is the source of truth; this is for the preview.
function deriveGithubSlug(url: string): string | null {
  if (!url) return null;
  const m = url
    .trim()
    .match(/github\.com[:/]+([A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)\/([A-Za-z0-9._-]+?)(?:\.git)?\/?$/);
  return m ? `${m[1]}/${m[2]}` : null;
}

export default function ProjectRemotePanel({ projectId }: { projectId: string }) {
  const { data: project } = useProject(projectId);
  const queryClient = useQueryClient();

  const [remoteUrl, setRemoteUrl] = useState('');
  const [autoPush, setAutoPush] = useState(false);
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [error, setError] = useState<string | null>(null);

  // Sync the form when the project loads or refreshes.
  useEffect(() => {
    if (!project) return;
    setRemoteUrl(project.remote_url ?? '');
    setAutoPush(project.auto_push_enabled ?? false);
  }, [project]);

  const derivedSlug = deriveGithubSlug(remoteUrl);
  const dirty =
    project != null &&
    ((remoteUrl.trim() || null) !== (project.remote_url ?? null) ||
      autoPush !== (project.auto_push_enabled ?? false));

  const onSave = async () => {
    if (!remoteUrl.trim()) {
      setError('Remote URL is required to wire a repository.');
      setStatus('error');
      return;
    }
    setStatus('saving');
    setError(null);
    try {
      await api.post(`/projects/${projectId}/remote`, {
        remote_url: remoteUrl.trim(),
        github_repo_slug: derivedSlug,
        auto_push_enabled: autoPush,
      });
      await queryClient.invalidateQueries({ queryKey: projectKeys.detail(projectId) });
      setStatus('saved');
      window.setTimeout(() => setStatus('idle'), 2000);
    } catch (err: unknown) {
      setError(describeApiError(err, 'Failed to save repository config'));
      setStatus('error');
    }
  };

  const connected = !!project?.remote_url;

  return (
    <section className="mb-6 rounded border border-gray-800 bg-gray-900 p-4">
      <div className="flex items-baseline justify-between mb-2">
        <h2 className="text-sm font-semibold text-gray-200">Repository</h2>
        {connected && (
          <span className="text-xs text-green-400">
            wired to <code>{project?.github_repo_slug ?? '(unknown slug)'}</code>
          </span>
        )}
      </div>

      <p className="mb-3 text-sm text-gray-400">
        The git remote this project pushes to and the GitHub repo the dashboard opens PRs against.
        New projects can set this at creation time; existing projects backfill here.
      </p>

      <div className="space-y-3 text-sm">
        <div>
          <label className="block text-xs uppercase tracking-wide text-gray-500 mb-1">
            Remote URL
          </label>
          <input
            type="text"
            value={remoteUrl}
            onChange={(e) => setRemoteUrl(e.target.value)}
            className="w-full px-3 py-1.5 bg-gray-950 text-gray-200 rounded border border-gray-700 focus:border-blue-500 focus:outline-none font-mono text-xs"
            placeholder="https://github.com/owner/repo.git"
            autoComplete="off"
          />
          {derivedSlug && (
            <p className="mt-1 text-xs text-gray-500">
              → repo slug: <code className="text-gray-300">{derivedSlug}</code>
            </p>
          )}
          {remoteUrl.trim() && !derivedSlug && (
            <p className="mt-1 text-xs text-amber-400">
              Doesn't match the expected GitHub clone-URL shape. PR features need a github.com URL;
              push will still work for any host.
            </p>
          )}
        </div>

        <label className="flex items-center gap-2 text-sm text-gray-300">
          <input
            type="checkbox"
            checked={autoPush}
            onChange={(e) => setAutoPush(e.target.checked)}
            className="rounded"
          />
          Auto-push after approved generations
        </label>

        {error && (
          <div className="rounded border border-red-800 bg-red-950/40 p-2 text-xs text-red-200">
            {error}
          </div>
        )}

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={onSave}
            disabled={!dirty || status === 'saving'}
            className="px-3 py-1.5 text-sm rounded bg-blue-700 hover:bg-blue-600 disabled:opacity-40 text-white"
          >
            {/* "Save repository" rather than "Save" so the
                generation-settings Save button below remains
                unambiguously findable by tests / a11y. */}
            {status === 'saving' ? 'Saving…' : 'Save repository'}
          </button>
          {status === 'saved' && <span className="text-xs text-green-400">Saved.</span>}
        </div>
      </div>
    </section>
  );
}
