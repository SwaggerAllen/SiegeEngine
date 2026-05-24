import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import {
  useCreateProject,
  useImportProject,
} from '../hooks/mutations/useProjectMutations';
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

// Match the backend's _MAX_EXTRACTED_BYTES so the user gets a fast
// client-side reject instead of waiting on the upload + a 400.
const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;

function looksLikeArchive(name: string): boolean {
  const n = name.toLowerCase();
  return n.endsWith('.tar') || n.endsWith('.tar.gz') || n.endsWith('.tgz') || n.endsWith('.zip');
}

type Mode = 'remote' | 'upload';

export function ProjectCreatePage() {
  const createProjectMutation = useCreateProject();
  const importProjectMutation = useImportProject();
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>('remote');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [content, setContent] = useState('');
  const [remoteUrl, setRemoteUrl] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState('');

  const derivedSlug = deriveGithubSlug(remoteUrl);
  const remoteLooksWrong = remoteUrl.trim().length > 0 && !derivedSlug;
  const isSubmitting =
    createProjectMutation.isPending || importProjectMutation.isPending;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      setError('Project name is required');
      return;
    }
    setError('');
    try {
      if (mode === 'remote') {
        if (!content.trim()) {
          setError('Project document is required');
          return;
        }
        if (remoteLooksWrong) {
          setError(
            "GitHub URL doesn't look like a github.com clone URL. " +
              'Expected shapes: https://github.com/owner/repo[.git] or git@github.com:owner/repo.git',
          );
          return;
        }
        const project = await createProjectMutation.mutateAsync({
          name,
          description: description || null,
          content,
          remoteUrl: remoteUrl.trim() || null,
          githubRepoSlug: derivedSlug,
        });
        navigate(`/projects/${project.id}`);
      } else {
        if (!file) {
          setError('Choose a tarball or zip to upload.');
          return;
        }
        if (!looksLikeArchive(file.name)) {
          setError('Upload must be a .tar / .tar.gz / .tgz / .zip archive.');
          return;
        }
        if (file.size > MAX_UPLOAD_BYTES) {
          setError(
            `Archive is larger than the ${MAX_UPLOAD_BYTES / (1024 * 1024)} MB limit.`,
          );
          return;
        }
        const project = await importProjectMutation.mutateAsync({
          name,
          description: description || null,
          file,
        });
        navigate(`/projects/${project.id}`);
      }
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

        <div
          role="tablist"
          aria-label="Create-project source"
          className="inline-flex rounded border border-gray-600 overflow-hidden mb-6"
        >
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'remote'}
            onClick={() => setMode('remote')}
            className={`px-4 py-2 text-sm ${
              mode === 'remote'
                ? 'bg-blue-600 text-white'
                : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
            }`}
          >
            GitHub URL
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'upload'}
            onClick={() => setMode('upload')}
            className={`px-4 py-2 text-sm border-l border-gray-600 ${
              mode === 'upload'
                ? 'bg-blue-600 text-white'
                : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
            }`}
          >
            Upload artifacts
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label htmlFor="project-name" className="block text-sm text-gray-300 mb-1">
              Project Name
            </label>
            <input
              id="project-name"
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

          {mode === 'remote' ? (
            <>
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
                <label htmlFor="project-doc" className="block text-sm text-gray-300 mb-1">
                  Project Document (Markdown)
                </label>
                <textarea
                  id="project-doc"
                  value={content}
                  onChange={(e) => setContent(e.target.value)}
                  className="w-full h-96 px-3 py-2 bg-gray-800 text-white rounded border border-gray-600 focus:border-blue-500 focus:outline-none font-mono text-sm"
                  placeholder="# My Project&#10;&#10;Describe your project here..."
                  required
                />
              </div>
            </>
          ) : (
            <div>
              <label htmlFor="project-archive" className="block text-sm text-gray-300 mb-1">
                Project archive
              </label>
              <input
                id="project-archive"
                type="file"
                accept=".tar,.tar.gz,.tgz,.zip"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="w-full text-sm text-gray-300 file:mr-3 file:rounded file:border-0 file:bg-gray-700 file:px-3 file:py-2 file:text-sm file:text-white hover:file:bg-gray-600"
              />
              <p className="mt-1 text-xs text-gray-500">
                Tar your project directory <em>including</em> <code>.git/</code> and
                upload it (<code>tar -czf out.tgz &lt;project&gt;/</code>). The substrate
                under <code>state/</code> + <code>ids/</code> must be present at HEAD. The
                resulting project is read-only — the GitHub writer endpoints don't apply,
                but the dashboard's read projections render normally.
              </p>
            </div>
          )}

          {error && <p className="text-red-400 text-sm">{error}</p>}

          <div className="flex gap-3">
            <button
              type="submit"
              disabled={isSubmitting}
              className="px-6 py-2 bg-blue-600 hover:bg-blue-700 rounded font-medium disabled:opacity-50"
            >
              {isSubmitting
                ? mode === 'upload'
                  ? 'Uploading...'
                  : 'Creating...'
                : mode === 'upload'
                  ? 'Import Project'
                  : 'Create Project'}
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
