import { useState, useEffect } from 'react';
import { usePipelineConfig } from '../../hooks/queries/usePipelineQueries';
import { updatePipelineConfig } from '../../api/pipeline';
import { useQueryClient } from '@tanstack/react-query';
import { pipelineKeys } from '../../hooks/queries/usePipelineQueries';

/** Default values shown as placeholders when no override is set. */
const DEFAULTS = {
  cli_timeout_document: 2100,
  cli_timeout_code: 1800,
  cli_timeout_summary: 900,
  cli_max_budget_code: 5.0,
};

function secondsToMinutes(s: number): string {
  return (s / 60).toFixed(0);
}

function minutesToSeconds(m: string): number | null {
  const n = parseFloat(m);
  if (isNaN(n) || n < 0) return null;
  return Math.round(n * 60);
}

interface PipelineConfigPanelProps {
  projectId: string;
}

export function PipelineConfigPanel({ projectId }: PipelineConfigPanelProps) {
  const { data: config } = usePipelineConfig(projectId);
  const queryClient = useQueryClient();

  // Local form state (minutes for timeouts, dollars for budget)
  const [docTimeout, setDocTimeout] = useState('');
  const [codeTimeout, setCodeTimeout] = useState('');
  const [summaryTimeout, setSummaryTimeout] = useState('');
  const [maxBudget, setMaxBudget] = useState('');
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');

  // Sync from server data
  useEffect(() => {
    if (!config) return;
    setDocTimeout(
      config.cli_timeout_document != null
        ? secondsToMinutes(config.cli_timeout_document)
        : '',
    );
    setCodeTimeout(
      config.cli_timeout_code != null
        ? secondsToMinutes(config.cli_timeout_code)
        : '',
    );
    setSummaryTimeout(
      config.cli_timeout_summary != null
        ? secondsToMinutes(config.cli_timeout_summary)
        : '',
    );
    setMaxBudget(
      config.cli_max_budget_code != null
        ? String(config.cli_max_budget_code)
        : '',
    );
  }, [config]);

  const handleSave = async () => {
    setSaving(true);
    setMessage('');
    try {
      const updates: Record<string, number | null> = {};

      // Convert minutes → seconds, empty string → null (clear override)
      const docSec = docTimeout.trim() ? minutesToSeconds(docTimeout) : null;
      const codeSec = codeTimeout.trim() ? minutesToSeconds(codeTimeout) : null;
      const sumSec = summaryTimeout.trim() ? minutesToSeconds(summaryTimeout) : null;
      const budget = maxBudget.trim() ? parseFloat(maxBudget) : null;

      updates.cli_timeout_document = docSec;
      updates.cli_timeout_code = codeSec;
      updates.cli_timeout_summary = sumSec;
      updates.cli_max_budget_code = budget != null && !isNaN(budget) ? budget : null;

      await updatePipelineConfig(projectId, updates);
      await queryClient.invalidateQueries({ queryKey: pipelineKeys.config(projectId) });
      setMessage('Saved');
      setTimeout(() => setMessage(''), 2000);
    } catch {
      setMessage('Failed to save');
    } finally {
      setSaving(false);
    }
  };

  if (!config) return null;

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-medium text-gray-300">Generation Timeouts</h3>
      <p className="text-xs text-gray-500">
        Override global timeout defaults for this project. Leave blank to use the system default.
      </p>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs text-gray-400 mb-1">
            Document timeout (min)
          </label>
          <input
            type="number"
            min={1}
            step={1}
            value={docTimeout}
            onChange={(e) => setDocTimeout(e.target.value)}
            placeholder={secondsToMinutes(DEFAULTS.cli_timeout_document)}
            className="w-full px-3 py-2 bg-gray-700 text-white rounded border border-gray-600 focus:border-blue-500 focus:outline-none text-sm"
          />
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1">
            Code timeout (min)
          </label>
          <input
            type="number"
            min={1}
            step={1}
            value={codeTimeout}
            onChange={(e) => setCodeTimeout(e.target.value)}
            placeholder={secondsToMinutes(DEFAULTS.cli_timeout_code)}
            className="w-full px-3 py-2 bg-gray-700 text-white rounded border border-gray-600 focus:border-blue-500 focus:outline-none text-sm"
          />
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1">
            Summary timeout (min)
          </label>
          <input
            type="number"
            min={1}
            step={1}
            value={summaryTimeout}
            onChange={(e) => setSummaryTimeout(e.target.value)}
            placeholder={secondsToMinutes(DEFAULTS.cli_timeout_summary)}
            className="w-full px-3 py-2 bg-gray-700 text-white rounded border border-gray-600 focus:border-blue-500 focus:outline-none text-sm"
          />
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1">
            Code budget (USD)
          </label>
          <input
            type="number"
            min={0.1}
            step={0.5}
            value={maxBudget}
            onChange={(e) => setMaxBudget(e.target.value)}
            placeholder={String(DEFAULTS.cli_max_budget_code)}
            className="w-full px-3 py-2 bg-gray-700 text-white rounded border border-gray-600 focus:border-blue-500 focus:outline-none text-sm"
          />
        </div>
      </div>

      <div className="flex items-center gap-3">
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded disabled:opacity-50"
        >
          {saving ? 'Saving...' : 'Save Timeouts'}
        </button>
        {message && (
          <span className={`text-sm ${message === 'Saved' ? 'text-green-400' : 'text-red-400'}`}>
            {message}
          </span>
        )}
      </div>
    </div>
  );
}
