import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  useProjectSettings,
  useUpdateProjectSettings,
} from '../hooks/queries/useProjectSettings';
import { useProject } from '../hooks/queries/useProjectQueries';
import { describeApiError } from '../lib/describeApiError';

const MIN_TIMEOUT_SECONDS = 60;
const MAX_TIMEOUT_SECONDS = 3600;

export function ProjectSettingsPage() {
  const { id: projectId } = useParams<{ id: string }>();
  if (!projectId) return null;
  return <SettingsShell projectId={projectId} />;
}

function SettingsShell({ projectId }: { projectId: string }) {
  const { data: project } = useProject(projectId);
  const { data: settings, error, isLoading } = useProjectSettings(projectId);
  const updateMutation = useUpdateProjectSettings(projectId);

  // Local form state: minutes rather than seconds so the UI is
  // humane. The backend contract is still seconds; we convert on
  // read and on submit.
  const [timeoutMinutes, setTimeoutMinutes] = useState<string>('');
  const [validationError, setValidationError] = useState<string | null>(null);
  const [savedOnce, setSavedOnce] = useState(false);

  useEffect(() => {
    if (settings) {
      setTimeoutMinutes(String(Math.round(settings.generation_timeout_seconds / 60)));
    }
  }, [settings]);

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setValidationError(null);
    const parsed = Number.parseInt(timeoutMinutes, 10);
    if (!Number.isFinite(parsed) || parsed <= 0) {
      setValidationError('Timeout must be a positive number of minutes.');
      return;
    }
    const seconds = parsed * 60;
    if (seconds < MIN_TIMEOUT_SECONDS || seconds > MAX_TIMEOUT_SECONDS) {
      setValidationError(
        `Timeout must be between ${MIN_TIMEOUT_SECONDS / 60} and ${
          MAX_TIMEOUT_SECONDS / 60
        } minutes.`
      );
      return;
    }
    updateMutation.mutate(
      { generation_timeout_seconds: seconds },
      {
        onSuccess: () => setSavedOnce(true),
      }
    );
  };

  return (
    <div className="min-h-screen bg-gray-900 text-white">
      <header className="border-b border-gray-700 px-3 py-2 flex items-center gap-3 shrink-0">
        <Link
          to={`/projects/${projectId}`}
          className="text-sm text-gray-400 hover:text-white"
        >
          ← Dashboard
        </Link>
        <div className="flex-1 min-w-0">
          <h1 className="text-sm font-bold truncate">
            {project?.name ? `${project.name} — Settings` : 'Project Settings'}
          </h1>
        </div>
      </header>

      <main className="max-w-2xl mx-auto px-6 py-8 space-y-6">
        <div>
          <h2 className="text-lg font-semibold mb-1">Generation</h2>
          <p className="text-xs text-gray-400">
            Controls that affect how feature-expansion and future
            generation jobs run for this project.
          </p>
        </div>

        {isLoading ? (
          <p className="text-sm text-gray-400">Loading settings…</p>
        ) : error ? (
          <p className="text-sm text-red-400">
            {describeApiError(error, 'Failed to load settings')}
          </p>
        ) : (
          <form onSubmit={onSubmit} noValidate className="space-y-4">
            <div>
              <label
                htmlFor="timeout-minutes"
                className="block text-sm font-medium mb-1"
              >
                Generation timeout
              </label>
              <div className="flex items-center gap-2">
                <input
                  id="timeout-minutes"
                  type="number"
                  min={MIN_TIMEOUT_SECONDS / 60}
                  max={MAX_TIMEOUT_SECONDS / 60}
                  step={1}
                  value={timeoutMinutes}
                  onChange={(e) => setTimeoutMinutes(e.target.value)}
                  className="w-24 bg-gray-800 border border-gray-700 rounded p-2 text-sm"
                  disabled={updateMutation.isPending}
                />
                <span className="text-sm text-gray-400">minutes</span>
              </div>
              <p className="text-xs text-gray-500 mt-1">
                How long a single LLM call may run before the worker
                kills it. Between 1 and 60 minutes. Default: 15
                minutes.
              </p>
            </div>

            {validationError && (
              <p className="text-sm text-red-400">{validationError}</p>
            )}
            {updateMutation.error && (
              <p className="text-sm text-red-400">
                {describeApiError(updateMutation.error, 'Failed to save settings')}
              </p>
            )}
            {savedOnce && !updateMutation.isPending && !updateMutation.error && (
              <p className="text-sm text-green-400">Saved.</p>
            )}

            <div className="flex items-center gap-2">
              <button
                type="submit"
                disabled={updateMutation.isPending}
                className="px-4 py-2 text-sm rounded bg-blue-700 hover:bg-blue-600 disabled:opacity-40"
              >
                {updateMutation.isPending ? 'Saving…' : 'Save'}
              </button>
            </div>
          </form>
        )}
      </main>
    </div>
  );
}
