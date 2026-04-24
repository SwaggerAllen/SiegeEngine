import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  useProjectSettings,
  useUpdateProjectSettings,
} from '../hooks/queries/useProjectSettings';
import { useProject } from '../hooks/queries/useProjectQueries';
import { describeApiError } from '../lib/describeApiError';
import { type ProjectSettings } from '../api/projectSettings';

const MIN_TIMEOUT_SECONDS = 60;
const MAX_TIMEOUT_SECONDS = 14400;
const MIN_BUDGET_USD = 0.1;
const MAX_BUDGET_USD = 20;
const MIN_MAX_OUTPUT_TOKENS = 1000;
const MAX_MAX_OUTPUT_TOKENS = 400000;

export function ProjectSettingsPage() {
  const { id: projectId } = useParams<{ id: string }>();
  if (!projectId) return null;
  return <SettingsShell projectId={projectId} />;
}

function SettingsShell({ projectId }: { projectId: string }) {
  const { data: project } = useProject(projectId);
  const { data: settings, error, isLoading } = useProjectSettings(projectId);
  const updateMutation = useUpdateProjectSettings(projectId);

  // Local form state: minutes rather than seconds for the timeout
  // so the UI is humane. The backend contract is still seconds;
  // we convert on read and on submit. The budget is already USD
  // on both sides, so no conversion.
  const [timeoutMinutes, setTimeoutMinutes] = useState<string>('');
  const [budgetUsd, setBudgetUsd] = useState<string>('');
  const [maxOutputTokens, setMaxOutputTokens] = useState<string>('');
  const [validationError, setValidationError] = useState<string | null>(null);
  const [savedOnce, setSavedOnce] = useState(false);

  useEffect(() => {
    if (settings) {
      setTimeoutMinutes(String(Math.round(settings.generation_timeout_seconds / 60)));
      setBudgetUsd(settings.cli_max_budget_usd.toFixed(2));
      setMaxOutputTokens(String(settings.cli_max_output_tokens));
    }
  }, [settings]);

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setValidationError(null);

    const parsedMinutes = Number.parseInt(timeoutMinutes, 10);
    if (!Number.isFinite(parsedMinutes) || parsedMinutes <= 0) {
      setValidationError('Timeout must be a positive number of minutes.');
      return;
    }
    const seconds = parsedMinutes * 60;
    if (seconds < MIN_TIMEOUT_SECONDS || seconds > MAX_TIMEOUT_SECONDS) {
      setValidationError(
        `Timeout must be between ${MIN_TIMEOUT_SECONDS / 60} and ${
          MAX_TIMEOUT_SECONDS / 60
        } minutes.`
      );
      return;
    }

    const parsedBudget = Number.parseFloat(budgetUsd);
    if (!Number.isFinite(parsedBudget) || parsedBudget <= 0) {
      setValidationError('Budget must be a positive dollar amount.');
      return;
    }
    if (parsedBudget < MIN_BUDGET_USD || parsedBudget > MAX_BUDGET_USD) {
      setValidationError(
        `Budget must be between $${MIN_BUDGET_USD.toFixed(2)} and $${MAX_BUDGET_USD.toFixed(
          2
        )}.`
      );
      return;
    }

    const parsedOutputTokens = Number.parseInt(maxOutputTokens, 10);
    if (!Number.isFinite(parsedOutputTokens) || parsedOutputTokens <= 0) {
      setValidationError('Max output tokens must be a positive integer.');
      return;
    }
    if (
      parsedOutputTokens < MIN_MAX_OUTPUT_TOKENS ||
      parsedOutputTokens > MAX_MAX_OUTPUT_TOKENS
    ) {
      setValidationError(
        `Max output tokens must be between ${MIN_MAX_OUTPUT_TOKENS.toLocaleString()} and ${MAX_MAX_OUTPUT_TOKENS.toLocaleString()}.`
      );
      return;
    }

    if (!settings) {
      setValidationError('Settings are still loading.');
      return;
    }

    const payload: ProjectSettings = {
      generation_timeout_seconds: seconds,
      cli_max_budget_usd: parsedBudget,
      cli_max_output_tokens: parsedOutputTokens,
    };

    updateMutation.mutate(payload, {
      onSuccess: () => setSavedOnce(true),
    });
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
          <form onSubmit={onSubmit} noValidate className="space-y-6">
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
                kills it. Between 1 and 240 minutes. Default: 120
                minutes.
              </p>
            </div>

            <div>
              <label
                htmlFor="budget-usd"
                className="block text-sm font-medium mb-1"
              >
                Max budget per call
              </label>
              <div className="flex items-center gap-2">
                <span className="text-sm text-gray-400">$</span>
                <input
                  id="budget-usd"
                  type="number"
                  min={MIN_BUDGET_USD}
                  max={MAX_BUDGET_USD}
                  step={0.10}
                  value={budgetUsd}
                  onChange={(e) => setBudgetUsd(e.target.value)}
                  className="w-24 bg-gray-800 border border-gray-700 rounded p-2 text-sm"
                  disabled={updateMutation.isPending}
                />
                <span className="text-sm text-gray-400">USD</span>
              </div>
              <p className="text-xs text-gray-500 mt-1">
                Dollar cap passed to the Claude CLI's{' '}
                <code className="text-gray-400">--max-budget-usd</code>{' '}
                flag for a single generation attempt. Each parse-validate
                retry is a fresh call with a fresh budget. Between
                ${MIN_BUDGET_USD.toFixed(2)} and ${MAX_BUDGET_USD.toFixed(2)}.
                Default: $2.00.
              </p>
            </div>

            <div>
              <label
                htmlFor="max-output-tokens"
                className="block text-sm font-medium mb-1"
              >
                Max output tokens
              </label>
              <div className="flex items-center gap-2">
                <input
                  id="max-output-tokens"
                  type="number"
                  min={MIN_MAX_OUTPUT_TOKENS}
                  max={MAX_MAX_OUTPUT_TOKENS}
                  step={1000}
                  value={maxOutputTokens}
                  onChange={(e) => setMaxOutputTokens(e.target.value)}
                  className="w-32 bg-gray-800 border border-gray-700 rounded p-2 text-sm"
                  disabled={updateMutation.isPending}
                />
                <span className="text-sm text-gray-400">tokens</span>
              </div>
              <p className="text-xs text-gray-500 mt-1">
                Cap on output tokens per Claude CLI call, forwarded as
                the <code className="text-gray-400">CLAUDE_CODE_MAX_OUTPUT_TOKENS</code>{' '}
                env var. Between {MIN_MAX_OUTPUT_TOKENS.toLocaleString()}{' '}
                and {MAX_MAX_OUTPUT_TOKENS.toLocaleString()}. Default:
                128,000 — double the CLI's intrinsic 64,000 so
                sysarch / reqs / subcomparch runs on real-sized
                projects don't truncate mid-atom.
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
