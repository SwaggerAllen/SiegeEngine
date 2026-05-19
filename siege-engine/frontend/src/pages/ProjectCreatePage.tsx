import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useCreateProject } from '../hooks/mutations/useProjectMutations';
import { describeApiError } from '../lib/describeApiError';

// Derive the owner/repo slug from a GitHub clone URL. Mirrors
// backend.projects.service.derive_github_slug; the backend will redo
// it server-side (the source of truth), but having a client-side
// version lets us preview the slug + validate the URL before submit.
function deriveGithubSlug(url: string): string | null {
  if (!url) return null;
  const m = url
    .trim()
    .match(/github\.com[:/]+([A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)\/([A-Za-z0-9._-]+?)(?:\.git)?\/?$/);
  return m ? `${m[1]}/${m[2]}` : null;
}

export function ProjectCreatePage() {
  const createProjectMutation = useCreateProject();
  const navigate = useNavigate();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [content, setContent] = useState('');
  const [remoteUrl, setRemoteUrl] = useState('');
  const [error, setError] = useState('');

  const derivedSlug = deriveGithubSlug(remoteUrl);
  const remoteLooksWrong = remoteUrl.trim().length > 0 && !derivedSlug;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !content.trim()) {
      setError('Name and project document are required');
      return;
    }
    if (remoteLooksWrong) {
      setError(
        "GitHub URL doesn't look like a github.com clone URL. " +
          'Expected shapes: https://github.com/owner/repo[.git] or git@github.com:owner/repo.git',
      );
      return;
    }
    setError('');
    try {
      const project = await createProjectMutation.mutateAsync({
        name,
        description: description || null,
        content,
        remoteUrl: remoteUrl.trim() || null,
        // Server re-derives but pass the client guess for clarity in
        // the network panel and as a sanity check.
        githubRepoSlug: derivedSlug,
      });
      navigate(`/projects/${project.id}`);
    } catch (err: unknown) {
      setError(describeApiError(err, 'Failed to create project'));
    }
  };

  return (
    <div className="min-h-screen bg-gray-900 text-white">
      <header className="border-b border-gray-700 px-6 py-4">
        <Link to="/projects" className="text-gray-400 hover:text-white text-sm">
          &larr; Back to Projects
        </Link>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-8">
        <h2 className="text-2xl font-semibold mb-6">New Project</h2>

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="block text-sm text-gray-300 mb-1">Project Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full px-3 py-2 bg-gray-800 text-white rounded border border-gray-600 focus:border-blue-500 focus:outline-none"
              placeholder="My Project"
              required
            />
          </div>

          <div>
            <label className="block text-sm text-gray-300 mb-1">Description (optional)</label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full px-3 py-2 bg-gray-800 text-white rounded border border-gray-600 focus:border-blue-500 focus:outline-none"
              placeholder="Brief project description"
            />
          </div>

          <div>
            <label className="block text-sm text-gray-300 mb-1">
              GitHub repo URL (optional)
            </label>
            <input
              type="text"
              value={remoteUrl}
              onChange={(e) => setRemoteUrl(e.target.value)}
              className="w-full px-3 py-2 bg-gray-800 text-white rounded border border-gray-600 focus:border-blue-500 focus:outline-none font-mono text-xs"
              placeholder="https://github.com/owner/repo.git  ·  or leave blank to wire later"
              autoComplete="off"
            />
            <p className="mt-1 text-xs text-gray-500">
              Sets the local clone's <code>origin</code> at creation time and lets the
              dashboard open PRs against the repo. The repo should exist on GitHub
              already; an empty (no initial commit) repo is the cleanest starting
              point.{' '}
              {derivedSlug && (
                <span className="text-green-400">
                  → repo slug: <code>{derivedSlug}</code>
                </span>
              )}
              {remoteLooksWrong && (
                <span className="text-amber-400">
                  → URL doesn't match the expected GitHub clone-URL shape.
                </span>
              )}
            </p>
          </div>

          <div>
            <label className="block text-sm text-gray-300 mb-1">
              Project Document (Markdown)
            </label>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              className="w-full h-96 px-3 py-2 bg-gray-800 text-white rounded border border-gray-600 focus:border-blue-500 focus:outline-none font-mono text-sm"
              placeholder="# My Project&#10;&#10;Describe your project here..."
              required
            />
          </div>

          {error && <p className="text-red-400 text-sm">{error}</p>}

          <div className="flex gap-3">
            <button
              type="submit"
              disabled={createProjectMutation.isPending}
              className="px-6 py-2 bg-blue-600 hover:bg-blue-700 rounded font-medium disabled:opacity-50"
            >
              {createProjectMutation.isPending ? 'Creating...' : 'Create Project'}
            </button>
            <Link
              to="/projects"
              className="px-6 py-2 bg-gray-700 hover:bg-gray-600 rounded font-medium"
            >
              Cancel
            </Link>
          </div>
        </form>
      </main>
    </div>
  );
}
