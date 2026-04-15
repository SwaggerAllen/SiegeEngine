import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  useProjectSettings,
  useUpdateProjectSettings,
} from '../hooks/queries/useProjectSettings';
import { useProject } from '../hooks/queries/useProjectQueries';
import { describeApiError } from '../lib/describeApiError';
import {
  NODE_COUNT_RANGE_FIELDS,
  type NodeCountRange,
  type NodeCountRangeField,
  type ProjectSettings,
} from '../api/projectSettings';

const MIN_TIMEOUT_SECONDS = 60;
const MAX_TIMEOUT_SECONDS = 3600;

// Client-side mirror of backend/projects/settings.py NodeCountRange
// ordering invariant. Used for the per-sub-form validation message.
function validateRange(range: NodeCountRange): string | null {
  if (
    !Number.isFinite(range.floor) ||
    !Number.isFinite(range.typical_min) ||
    !Number.isFinite(range.typical_max) ||
    !Number.isFinite(range.ceiling)
  ) {
    return 'Every field must be a positive whole number.';
  }
  if (
    range.floor < 1 ||
    range.typical_min < 1 ||
    range.typical_max < 1 ||
    range.ceiling < 1
  ) {
    return 'Every field must be at least 1.';
  }
  if (
    range.floor > 1000 ||
    range.typical_min > 1000 ||
    range.typical_max > 1000 ||
    range.ceiling > 1000
  ) {
    return 'Every field must be at most 1000.';
  }
  if (
    !(
      range.floor <= range.typical_min &&
      range.typical_min <= range.typical_max &&
      range.typical_max <= range.ceiling
    )
  ) {
    return 'Values must be ordered floor ≤ typical min ≤ typical max ≤ ceiling.';
  }
  return null;
}

// State shape for one sub-form: raw string inputs so partial edits
// don't get coerced to NaN mid-typing. Parsed into a numeric
// NodeCountRange only at submit time.
interface RangeFormState {
  floor: string;
  typical_min: string;
  typical_max: string;
  ceiling: string;
}

function rangeToFormState(range: NodeCountRange): RangeFormState {
  return {
    floor: String(range.floor),
    typical_min: String(range.typical_min),
    typical_max: String(range.typical_max),
    ceiling: String(range.ceiling),
  };
}

function parseRangeFormState(state: RangeFormState): NodeCountRange {
  return {
    floor: Number.parseInt(state.floor, 10),
    typical_min: Number.parseInt(state.typical_min, 10),
    typical_max: Number.parseInt(state.typical_max, 10),
    ceiling: Number.parseInt(state.ceiling, 10),
  };
}

type RangeFormStateMap = Record<NodeCountRangeField['key'], RangeFormState>;

function initialRangeFormStateMap(settings: ProjectSettings): RangeFormStateMap {
  return {
    features_per_group: rangeToFormState(settings.features_per_group),
    top_level_responsibilities: rangeToFormState(settings.top_level_responsibilities),
    top_level_components: rangeToFormState(settings.top_level_components),
    subcomponents_per_component: rangeToFormState(settings.subcomponents_per_component),
    subresponsibilities_per_component: rangeToFormState(
      settings.subresponsibilities_per_component
    ),
  };
}

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
  // we convert on read and on submit.
  const [timeoutMinutes, setTimeoutMinutes] = useState<string>('');
  const [rangeForms, setRangeForms] = useState<RangeFormStateMap | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [rangeErrors, setRangeErrors] = useState<
    Partial<Record<NodeCountRangeField['key'], string>>
  >({});
  const [savedOnce, setSavedOnce] = useState(false);

  useEffect(() => {
    if (settings) {
      setTimeoutMinutes(String(Math.round(settings.generation_timeout_seconds / 60)));
      setRangeForms(initialRangeFormStateMap(settings));
    }
  }, [settings]);

  const updateRangeField = (
    key: NodeCountRangeField['key'],
    field: keyof RangeFormState,
    value: string
  ) => {
    setRangeForms((prev) =>
      prev
        ? {
            ...prev,
            [key]: { ...prev[key], [field]: value },
          }
        : prev
    );
  };

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setValidationError(null);
    setRangeErrors({});

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

    if (!rangeForms || !settings) {
      // No form state loaded yet — defensive early return.
      setValidationError('Settings are still loading.');
      return;
    }

    const parsedRanges: Partial<Record<NodeCountRangeField['key'], NodeCountRange>> = {};
    const nextRangeErrors: Partial<Record<NodeCountRangeField['key'], string>> = {};
    let hasRangeError = false;
    for (const field of NODE_COUNT_RANGE_FIELDS) {
      const numeric = parseRangeFormState(rangeForms[field.key]);
      const err = validateRange(numeric);
      if (err) {
        nextRangeErrors[field.key] = err;
        hasRangeError = true;
      } else {
        parsedRanges[field.key] = numeric;
      }
    }
    if (hasRangeError) {
      setRangeErrors(nextRangeErrors);
      return;
    }

    const payload: ProjectSettings = {
      generation_timeout_seconds: seconds,
      features_per_group: parsedRanges.features_per_group!,
      top_level_responsibilities: parsedRanges.top_level_responsibilities!,
      top_level_components: parsedRanges.top_level_components!,
      subcomponents_per_component: parsedRanges.subcomponents_per_component!,
      subresponsibilities_per_component: parsedRanges.subresponsibilities_per_component!,
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
                kills it. Between 1 and 60 minutes. Default: 15
                minutes.
              </p>
            </div>

            <div className="pt-4 border-t border-gray-800">
              <h3 className="text-base font-semibold mb-1">Generation counts</h3>
              <p className="text-xs text-gray-400 mb-4">
                Four-number ranges the generation prompts cite when
                deciding how coarsely or finely to decompose. The
                LLM is nudged toward the "typical" band and warned
                if it drops below the floor or crosses the ceiling.
                Ordering: floor ≤ typical min ≤ typical max ≤
                ceiling. Changes apply on the next regen of the
                affected tier; existing content is untouched.
              </p>
              <div className="space-y-4">
                {NODE_COUNT_RANGE_FIELDS.map((field) => {
                  const state = rangeForms?.[field.key];
                  const fieldError = rangeErrors[field.key];
                  if (!state) return null;
                  return (
                    <div
                      key={field.key}
                      className="bg-gray-800 border border-gray-700 rounded p-4"
                    >
                      <div className="text-sm font-medium">{field.label}</div>
                      <p className="text-xs text-gray-400 mt-1 mb-3">
                        {field.description}
                      </p>
                      <div className="flex gap-3">
                        {(
                          [
                            { key: 'floor', label: 'Floor' },
                            { key: 'typical_min', label: 'Typical min' },
                            { key: 'typical_max', label: 'Typical max' },
                            { key: 'ceiling', label: 'Ceiling' },
                          ] as const
                        ).map(({ key, label }) => (
                          <div key={key} className="flex flex-col">
                            <label
                              htmlFor={`${field.key}-${key}`}
                              className="text-xs text-gray-500 mb-1"
                            >
                              {label}
                            </label>
                            <input
                              id={`${field.key}-${key}`}
                              type="number"
                              min={1}
                              max={1000}
                              step={1}
                              value={state[key]}
                              onChange={(e) =>
                                updateRangeField(field.key, key, e.target.value)
                              }
                              className="w-20 bg-gray-900 border border-gray-700 rounded p-1.5 text-sm"
                              disabled={updateMutation.isPending}
                            />
                          </div>
                        ))}
                      </div>
                      {fieldError && (
                        <p className="text-xs text-red-400 mt-2">{fieldError}</p>
                      )}
                    </div>
                  );
                })}
              </div>
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
