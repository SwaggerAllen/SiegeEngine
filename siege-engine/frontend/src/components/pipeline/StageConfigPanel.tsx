import { useEffect, useState } from 'react';
import { updateStageConfig, resetStageConfig, reconcilePipeline } from '../../api/pipeline';
import { usePipelineStore } from '../../store/pipelineStore';
import { useDAGStore } from '../../store/dagStore';

const MODEL_OPTIONS = [
  { value: '', label: 'Pipeline Default' },
  { value: 'claude-opus-4-20250514', label: 'Claude Opus 4' },
  { value: 'claude-sonnet-4-20250514', label: 'Claude Sonnet 4' },
  { value: 'claude-haiku-4-5-20251001', label: 'Claude Haiku 4.5' },
];

interface StageConfigPanelProps {
  projectId: string;
  stageKey: string;
}

export function StageConfigPanel({ projectId, stageKey }: StageConfigPanelProps) {
  const config = usePipelineStore((s) => s.config);
  const fetchConfig = usePipelineStore((s) => s.fetchConfig);
  const fetchDAG = useDAGStore((s) => s.fetchDAG);
  const setEditPromptStageKey = useDAGStore((s) => s.setEditPromptStageKey);

  const stageDef = config?.stages.find((s) => s.stage_key === stageKey);

  const [form, setForm] = useState<{
    display_name: string;
    model_override: string | null;
    temperature_override: number | null;
    ai_review_enabled: boolean;
    human_review_enabled: boolean;
  } | null>(null);

  const triggerStage = usePipelineStore((s) => s.triggerStage);

  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [saved, setSaved] = useState(false);
  const [triggering, setTriggering] = useState(false);
  const [repairing, setRepairing] = useState(false);
  const [repairResult, setRepairResult] = useState<string | null>(null);
  const fetchDocumentsDAG = useDAGStore((s) => s.fetchDocumentsDAG);
  const fetchStatus = usePipelineStore((s) => s.fetchStatus);
  const fetchRuns = usePipelineStore((s) => s.fetchRuns);

  useEffect(() => {
    if (stageDef) {
      setForm({
        display_name: stageDef.display_name,
        model_override: stageDef.model_override,
        temperature_override: stageDef.temperature_override,
        ai_review_enabled: stageDef.ai_review_enabled,
        human_review_enabled: stageDef.human_review_enabled,
      });
      setSaved(false);
    }
  }, [stageKey, stageDef]);

  const handleSave = async () => {
    if (!form) return;
    setSaving(true);
    try {
      await updateStageConfig(projectId, stageKey, {
        display_name: form.display_name,
        model_override: form.model_override,
        temperature_override: form.temperature_override,
        ai_review_enabled: form.ai_review_enabled,
        human_review_enabled: form.human_review_enabled,
      });
      setSaved(true);
      await Promise.all([fetchConfig(projectId), fetchDAG(projectId)]);
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    setResetting(true);
    try {
      const updated = await resetStageConfig(projectId, stageKey);
      setForm({
        display_name: updated.display_name,
        model_override: updated.model_override,
        temperature_override: updated.temperature_override,
        ai_review_enabled: updated.ai_review_enabled,
        human_review_enabled: updated.human_review_enabled,
      });
      setSaved(false);
      await Promise.all([fetchConfig(projectId), fetchDAG(projectId)]);
    } finally {
      setResetting(false);
    }
  };

  const handleEditPrompt = () => {
    setEditPromptStageKey(stageKey);
  };

  const handleTrigger = async () => {
    setTriggering(true);
    try {
      await triggerStage(projectId, stageKey);
    } catch (err) {
      console.error('[StageConfig] Trigger failed:', err);
    } finally {
      setTriggering(false);
    }
  };

  const handleRepair = async () => {
    setRepairing(true);
    setRepairResult(null);
    try {
      const result = await reconcilePipeline(projectId);
      const fixes = result.corrections.length + result.orphans_removed.length;
      setRepairResult(fixes > 0 ? `Fixed ${fixes} issue${fixes > 1 ? 's' : ''}` : 'No issues found');
      if (fixes > 0) {
        await Promise.all([
          fetchDAG(projectId),
          fetchDocumentsDAG(projectId),
          fetchStatus(projectId),
          fetchRuns(projectId),
        ]);
      }
    } catch {
      setRepairResult('Repair failed');
    } finally {
      setRepairing(false);
    }
  };

  // Auto-dismiss repair result
  useEffect(() => {
    if (!repairResult) return;
    const timer = setTimeout(() => setRepairResult(null), 4000);
    return () => clearTimeout(timer);
  }, [repairResult]);

  if (!stageDef || !form) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500 text-sm">
        Stage not found
      </div>
    );
  }

  return (
    <div className="p-4 overflow-auto h-full">
      <h3 className="text-lg font-semibold text-white mb-1">{stageDef.display_name}</h3>
      <div className="text-xs text-gray-500 mb-4 flex gap-3">
        <span>Output: {stageDef.output_artifact_type}</span>
        <span>Fan out: {stageDef.fan_out_strategy}</span>
      </div>

      <div className="space-y-4">
        <div>
          <label className="block text-sm text-gray-300 mb-1">Display Name</label>
          <input
            type="text"
            value={form.display_name}
            onChange={(e) => {
              setForm({ ...form, display_name: e.target.value });
              setSaved(false);
            }}
            className="w-full px-3 py-2 bg-gray-700 text-white rounded border border-gray-600 focus:border-blue-500 focus:outline-none text-sm"
          />
        </div>

        <div>
          <label className="block text-sm text-gray-300 mb-1">Model Override</label>
          <select
            value={form.model_override || ''}
            onChange={(e) => {
              setForm({ ...form, model_override: e.target.value || null });
              setSaved(false);
            }}
            className="w-full px-3 py-2 bg-gray-700 text-white rounded border border-gray-600 focus:border-blue-500 focus:outline-none text-sm"
          >
            {MODEL_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
          {config && (
            <p className="text-xs text-gray-500 mt-1">
              Pipeline default: {config.default_model}
            </p>
          )}
        </div>

        <div>
          <label className="block text-sm text-gray-300 mb-1">Temperature Override</label>
          <input
            type="number"
            value={form.temperature_override ?? ''}
            onChange={(e) => {
              setForm({
                ...form,
                temperature_override: e.target.value ? parseFloat(e.target.value) : null,
              });
              setSaved(false);
            }}
            min={0}
            max={1}
            step={0.1}
            placeholder={config ? `Default: ${config.default_temperature}` : 'Default'}
            className="w-full px-3 py-2 bg-gray-700 text-white rounded border border-gray-600 focus:border-blue-500 focus:outline-none text-sm"
          />
        </div>

        <div className="space-y-2">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={form.ai_review_enabled}
              onChange={(e) => {
                setForm({ ...form, ai_review_enabled: e.target.checked });
                setSaved(false);
              }}
              className="w-4 h-4 rounded border-gray-600 bg-gray-700 text-blue-500 focus:ring-blue-500 focus:ring-offset-gray-900"
            />
            <span className="text-sm text-gray-300">AI Review Enabled</span>
          </label>
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={form.human_review_enabled}
              onChange={(e) => {
                setForm({ ...form, human_review_enabled: e.target.checked });
                setSaved(false);
              }}
              className="w-4 h-4 rounded border-gray-600 bg-gray-700 text-blue-500 focus:ring-blue-500 focus:ring-offset-gray-900"
            />
            <span className="text-sm text-gray-300">Human Review Enabled</span>
          </label>
        </div>

        <div className="flex flex-wrap items-center gap-3 pt-2 border-t border-gray-700">
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded disabled:opacity-50"
          >
            {saving ? 'Saving...' : 'Save'}
          </button>
          <button
            onClick={handleReset}
            disabled={resetting}
            className="px-4 py-2 bg-gray-600 hover:bg-gray-500 text-white text-sm rounded disabled:opacity-50"
          >
            {resetting ? 'Resetting...' : 'Use Defaults'}
          </button>
          <button
            onClick={handleEditPrompt}
            className="px-4 py-2 bg-gray-600 hover:bg-gray-500 text-white text-sm rounded"
          >
            Edit Prompt
          </button>
          <button
            onClick={handleTrigger}
            disabled={triggering}
            className="px-4 py-2 bg-amber-600 hover:bg-amber-700 text-white text-sm rounded disabled:opacity-50"
            title="Manually kick off this stage (useful for recovering from stuck states)"
          >
            {triggering ? 'Running...' : 'Run Stage'}
          </button>
          <button
            onClick={handleRepair}
            disabled={repairing}
            className="px-4 py-2 bg-gray-600 hover:bg-gray-500 text-white text-sm rounded disabled:opacity-50 flex items-center gap-1.5"
            title="Repair: fix orphaned nodes and status mismatches"
          >
            <svg className={`w-4 h-4 ${repairing ? 'animate-spin' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              {repairing ? (
                <>
                  <circle className="opacity-25" cx="12" cy="12" r="10" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" stroke="none" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </>
              ) : (
                <>
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                </>
              )}
            </svg>
            <span>Repair</span>
          </button>
          {saved && <span className="text-green-400 text-sm">Saved!</span>}
          {repairResult && (
            <span className={`text-sm ${repairResult.startsWith('Fixed') ? 'text-green-400' : repairResult === 'No issues found' ? 'text-gray-400' : 'text-red-400'}`}>
              {repairResult}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
