import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { getSamplerConfig, putSamplerConfig, type SamplerConfig } from '../api/cohorts';

interface Props {
  projectId: string;
  tier: string;
}

interface AxisDraft {
  key: string;
  label: string;
  weight: number;
  type: string;
  buckets?: { label?: string; min?: number; max?: number }[];
}

/**
 * Per-tier sampler config editor.
 *
 * Lets the user tune axis weights without a deploy interrupting
 * in-flight generations. The config drives the cohort
 * auto-suggest endpoint's stratified sampler — higher-weight
 * axes prioritise their bucket coverage in the greedy pick.
 *
 * Bucket editing for numeric axes is intentionally minimal here
 * (the seeded defaults cover the common shapes); the JSON view
 * underneath is the escape hatch for arbitrary edits.
 */
export function SamplerConfigEditor({ projectId, tier }: Props) {
  const [open, setOpen] = useState(false);
  const queryClient = useQueryClient();
  const { data, isLoading, isError } = useQuery({
    queryKey: ['samplerConfig', projectId, tier],
    queryFn: () => getSamplerConfig(projectId, tier),
    enabled: open,
  });

  return (
    <div className="rounded border border-gray-800 bg-gray-950/40 p-3 text-xs space-y-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 text-gray-200 font-medium hover:text-gray-50"
        data-testid="sampler-config-toggle"
        aria-expanded={open}
      >
        <span>{open ? '▼' : '▶'}</span>
        <span>Sampler config ({tier})</span>
      </button>
      {open && (
        <>
          {isLoading && <div className="text-gray-500 italic">Loading config…</div>}
          {isError && <div className="text-red-400">Failed to load sampler config</div>}
          {data && (
            <SamplerConfigForm
              projectId={projectId}
              tier={tier}
              config={data}
              onSaved={() => {
                queryClient.invalidateQueries({ queryKey: ['samplerConfig', projectId, tier] });
              }}
            />
          )}
        </>
      )}
    </div>
  );
}

function SamplerConfigForm({
  projectId,
  tier,
  config,
  onSaved,
}: {
  projectId: string;
  tier: string;
  config: SamplerConfig;
  onSaved: () => void;
}) {
  const initialAxes = useMemo(
    () => (config.axes.axes ?? []) as unknown as AxisDraft[],
    [config],
  );
  const [axes, setAxes] = useState<AxisDraft[]>(() => initialAxes.map((a) => ({ ...a })));
  const [statusMsg, setStatusMsg] = useState<string | null>(null);
  const [jsonMode, setJsonMode] = useState(false);
  const [jsonText, setJsonText] = useState(() => JSON.stringify(config.axes, null, 2));
  const [jsonError, setJsonError] = useState<string | null>(null);

  // Resync when the upstream config changes (after a save).
  useEffect(() => {
    setAxes(initialAxes.map((a) => ({ ...a })));
    setJsonText(JSON.stringify(config.axes, null, 2));
  }, [config, initialAxes]);

  const saveMutation = useMutation({
    mutationFn: (nextAxes: SamplerConfig['axes']) =>
      putSamplerConfig(projectId, tier, nextAxes),
    onSuccess: () => {
      setStatusMsg('Saved.');
      onSaved();
    },
    onError: (err: unknown) => {
      setStatusMsg(`Save failed: ${err instanceof Error ? err.message : String(err)}`);
    },
  });

  function handleSave() {
    if (jsonMode) {
      try {
        const parsed = JSON.parse(jsonText);
        if (!parsed || typeof parsed !== 'object' || !Array.isArray(parsed.axes)) {
          setJsonError('JSON must be an object with an "axes" array.');
          return;
        }
        setJsonError(null);
        saveMutation.mutate(parsed as SamplerConfig['axes']);
      } catch (err) {
        setJsonError(err instanceof Error ? err.message : String(err));
      }
      return;
    }
    saveMutation.mutate({ axes: axes as unknown as Record<string, unknown>[] } as SamplerConfig['axes']);
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-[11px]">
        <button
          type="button"
          onClick={() => setJsonMode(false)}
          className={`px-2 py-0.5 rounded ${
            jsonMode ? 'text-gray-400' : 'bg-gray-800 text-gray-100'
          }`}
        >
          Form
        </button>
        <button
          type="button"
          onClick={() => setJsonMode(true)}
          className={`px-2 py-0.5 rounded ${
            jsonMode ? 'bg-gray-800 text-gray-100' : 'text-gray-400'
          }`}
        >
          JSON
        </button>
      </div>
      {!jsonMode && (
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-gray-500 text-left">
              <th className="px-1 py-0.5">Key</th>
              <th className="px-1 py-0.5">Label</th>
              <th className="px-1 py-0.5">Type</th>
              <th className="px-1 py-0.5">Weight</th>
            </tr>
          </thead>
          <tbody>
            {axes.map((axis, idx) => (
              <tr key={axis.key} className="border-t border-gray-900">
                <td className="px-1 py-0.5 font-mono text-gray-200">{axis.key}</td>
                <td className="px-1 py-0.5 text-gray-300">{axis.label}</td>
                <td className="px-1 py-0.5 text-gray-400">{axis.type}</td>
                <td className="px-1 py-0.5">
                  <input
                    type="number"
                    min={0}
                    max={5}
                    step={0.1}
                    value={axis.weight}
                    onChange={(e) => {
                      const next = [...axes];
                      next[idx] = { ...next[idx], weight: Number(e.target.value) || 0 };
                      setAxes(next);
                    }}
                    className="w-16 bg-gray-900 border border-gray-700 rounded px-1 py-0.5 text-gray-200"
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {jsonMode && (
        <>
          <textarea
            value={jsonText}
            onChange={(e) => setJsonText(e.target.value)}
            rows={Math.min(20, jsonText.split('\n').length + 1)}
            className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 font-mono text-[11px] text-gray-200"
            spellCheck={false}
          />
          {jsonError && <div className="text-red-400">{jsonError}</div>}
        </>
      )}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={handleSave}
          disabled={saveMutation.isPending}
          className="px-2 py-1 rounded bg-emerald-700 hover:bg-emerald-600 text-white disabled:opacity-40"
        >
          {saveMutation.isPending ? 'Saving…' : 'Save sampler config'}
        </button>
        {statusMsg && <span className="text-gray-300">{statusMsg}</span>}
      </div>
    </div>
  );
}
