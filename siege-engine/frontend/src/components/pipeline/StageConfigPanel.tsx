import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { updateStageConfig, resetStageConfig, reconcilePipeline } from '../../api/pipeline';
import { usePipelineConfigData, useIsRunning, usePipelineRuns, pipelineKeys } from '../../hooks/queries/usePipelineQueries';
import { useTriggerStage, useStartPipeline, useResumeRun } from '../../hooks/mutations/usePipelineMutations';
import { dagKeys } from '../../hooks/queries/useDAGQueries';
import { useDAGStore } from '../../store/dagStore';
import type { PipelineStartOptions } from '../../types/pipeline';

const STOP_POINT_OPTIONS = [
  { value: 'end_of_phase', label: 'End of phase' },
  { value: 'before_code', label: 'Before code generation' },
  { value: 'every_artifact', label: 'After every artifact' },
];

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
  const queryClient = useQueryClient();
  const config = usePipelineConfigData(projectId);
  const setEditPromptStageKey = useDAGStore((s) => s.setEditPromptStageKey);

  const stageDef = config?.stages.find((s) => s.stage_key === stageKey);

  const [form, setForm] = useState<{
    display_name: string;
    model_override: string | null;
    temperature_override: number | null;
    ai_review_enabled: boolean;
    human_review_enabled: boolean;
  } | null>(null);

  const triggerStageMutation = useTriggerStage(projectId);
  const startPipelineMutation = useStartPipeline(projectId);
  const resumeRunMutation = useResumeRun(projectId);
  const isRunning = useIsRunning(projectId);
  const { data: runs = [] } = usePipelineRuns(projectId);

  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [saved, setSaved] = useState(false);
  const [triggering, setTriggering] = useState(false);
  const [repairing, setRepairing] = useState(false);
  const [repairResult, setRepairResult] = useState<string | null>(null);
  const [showRunConfig, setShowRunConfig] = useState(false);
  const [runMode, setRunMode] = useState<'start' | 'resume'>('start');
  const [aiLoops, setAiLoops] = useState(1);
  const [stopPoint, setStopPoint] = useState('end_of_phase');
  const [startingRun, setStartingRun] = useState(false);
  // Removed: imperative refetch replaced by queryClient.invalidateQueries

  const hasCompletedRun = runs.some(
    (r) => r.status === 'completed' || r.status === 'paused' || r.status === 'cancelled' || r.status === 'failed'
  );

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
      queryClient.invalidateQueries({ queryKey: pipelineKeys.config(projectId) });
      queryClient.invalidateQueries({ queryKey: dagKeys.workflow(projectId) });
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
      queryClient.invalidateQueries({ queryKey: pipelineKeys.config(projectId) });
      queryClient.invalidateQueries({ queryKey: dagKeys.workflow(projectId) });
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
      await triggerStageMutation.mutateAsync({ stageKey });
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
        queryClient.invalidateQueries({ queryKey: dagKeys.workflow(projectId) });
        queryClient.invalidateQueries({ queryKey: dagKeys.documents(projectId) });
        queryClient.invalidateQueries({ queryKey: pipelineKeys.status(projectId) });
        queryClient.invalidateQueries({ queryKey: pipelineKeys.runs(projectId) });
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
          <div className="flex items-center gap-2 opacity-50">
            <input
              type="checkbox"
              checked={true}
              disabled
              className="w-4 h-4 rounded border-gray-600 bg-gray-700 text-blue-500"
            />
            <span className="text-sm text-gray-400">Human Review (always on)</span>
          </div>
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

        {/* Start Run from this stage */}
        {!isRunning && (
          <div className="pt-4 border-t border-gray-700">
            {!showRunConfig ? (
              <button
                type="button"
                onClick={() => setShowRunConfig(true)}
                className="px-4 py-2 bg-green-600 hover:bg-green-700 text-white text-sm rounded flex items-center gap-1.5"
              >
                <span>Start Run from Here</span>
                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </button>
            ) : (
              <div className="space-y-3 bg-gray-800/50 rounded-lg p-3">
                <h4 className="text-sm font-semibold text-gray-300">Run Configuration</h4>
                <p className="text-xs text-gray-400">
                  Starting from <span className="text-white font-medium">{stageDef.display_name}</span>
                </p>

                <div>
                  <label className="block text-xs text-gray-400 mb-1">Run type</label>
                  <select
                    value={runMode}
                    onChange={(e) => setRunMode(e.target.value as 'start' | 'resume')}
                    className="w-full px-2 py-1.5 bg-gray-700 text-white text-sm rounded border border-gray-600 focus:border-blue-500 focus:outline-none"
                  >
                    <option value="start">Fresh Start</option>
                    {hasCompletedRun && <option value="resume">Resume</option>}
                  </select>
                </div>

                <div>
                  <label className="block text-xs text-gray-400 mb-1">AI self-improvement loops</label>
                  <input
                    type="number"
                    min={0}
                    max={10}
                    value={aiLoops}
                    onChange={(e) => setAiLoops(Math.max(0, Math.min(10, parseInt(e.target.value) || 0)))}
                    className="w-20 px-2 py-1 bg-gray-700 text-white text-sm rounded border border-gray-600 focus:border-blue-500 focus:outline-none"
                  />
                </div>

                <div>
                  <label className="block text-xs text-gray-400 mb-1">Stop at</label>
                  <select
                    value={stopPoint}
                    onChange={(e) => setStopPoint(e.target.value)}
                    className="w-full px-2 py-1.5 bg-gray-700 text-white text-sm rounded border border-gray-600 focus:border-blue-500 focus:outline-none"
                  >
                    {STOP_POINT_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>{opt.label}</option>
                    ))}
                  </select>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={async () => {
                      setStartingRun(true);
                      try {
                        const options: PipelineStartOptions = {
                          ai_loops: aiLoops,
                          stop_point: stopPoint,
                          start_stage_key: stageKey,
                        };
                        if (runMode === 'resume') {
                          await resumeRunMutation.mutateAsync(options);
                        } else {
                          await startPipelineMutation.mutateAsync(options);
                        }
                        setShowRunConfig(false);
                      } catch (err) {
                        console.error('Run start failed:', err);
                      } finally {
                        setStartingRun(false);
                      }
                    }}
                    disabled={startingRun}
                    className={`px-4 py-2 text-white text-sm rounded disabled:opacity-50 ${
                      runMode === 'resume' ? 'bg-blue-600 hover:bg-blue-700' : 'bg-green-600 hover:bg-green-700'
                    }`}
                  >
                    {startingRun ? 'Starting...' : runMode === 'resume' ? 'Resume' : 'Start'}
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowRunConfig(false)}
                    className="px-4 py-2 bg-gray-600 hover:bg-gray-500 text-white text-sm rounded"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
