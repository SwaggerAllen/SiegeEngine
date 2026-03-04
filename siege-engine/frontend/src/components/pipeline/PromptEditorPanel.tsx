import { useEffect, useState } from 'react';
import api from '../../api/client';

interface PromptConfig {
  id: string | null;
  stage_definition_id: string;
  system_message: string;
  output_format_instructions: string;
  context_template: string;
  revision_instructions: string;
  model: string | null;
  temperature: number | null;
  max_tokens: number;
}

interface StagePrompt {
  stage_key: string;
  display_name: string;
  has_custom_config: boolean;
  config: PromptConfig;
}

const MODEL_OPTIONS = [
  'claude-opus-4-20250514',
  'claude-sonnet-4-20250514',
  'claude-haiku-4-5-20251001',
];

export function PromptEditorPanel({ projectId }: { projectId: string }) {
  const [stages, setStages] = useState<StagePrompt[]>([]);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [form, setForm] = useState<PromptConfig | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const fetchPrompts = async () => {
    const { data } = await api.get(`/pipeline/${projectId}/prompts`);
    setStages(data);
    if (!selectedKey && data.length > 0) {
      setSelectedKey(data[0].stage_key);
      setForm({ ...data[0].config });
    }
  };

  useEffect(() => {
    fetchPrompts();
  }, [projectId]);

  useEffect(() => {
    const stage = stages.find((s) => s.stage_key === selectedKey);
    if (stage) {
      setForm({ ...stage.config });
      setSaved(false);
    }
  }, [selectedKey]);

  const handleSave = async () => {
    if (!selectedKey || !form) return;
    setSaving(true);
    try {
      await api.put(`/pipeline/${projectId}/prompts/${selectedKey}`, {
        system_message: form.system_message,
        output_format_instructions: form.output_format_instructions,
        context_template: form.context_template,
        revision_instructions: form.revision_instructions,
        model: form.model,
        temperature: form.temperature,
        max_tokens: form.max_tokens,
      });
      setSaved(true);
      await fetchPrompts();
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    if (!selectedKey) return;
    try {
      await api.post(`/pipeline/${projectId}/prompts/${selectedKey}/reset`);
      await fetchPrompts();
    } catch {
      setSaved(false);
    }
  };

  const updateField = <K extends keyof PromptConfig>(key: K, value: PromptConfig[K]) => {
    if (!form) return;
    setForm({ ...form, [key]: value });
    setSaved(false);
  };

  return (
    <div className="flex h-full">
      {/* Sidebar: stage list */}
      <div className="w-56 border-r border-gray-700 overflow-auto shrink-0">
        <div className="p-3 text-xs text-gray-400 uppercase tracking-wider">Stages</div>
        {stages.map((s) => (
          <button
            key={s.stage_key}
            onClick={() => setSelectedKey(s.stage_key)}
            className={`w-full text-left px-3 py-2 text-sm ${
              selectedKey === s.stage_key
                ? 'bg-gray-700 text-white'
                : 'text-gray-400 hover:bg-gray-800 hover:text-white'
            }`}
          >
            {s.display_name}
            {s.has_custom_config && (
              <span className="ml-1 text-xs text-blue-400">*</span>
            )}
          </button>
        ))}
      </div>

      {/* Editor form */}
      <div className="flex-1 overflow-auto p-4">
        {form ? (
          <div className="max-w-3xl space-y-4">
            <div>
              <label className="block text-sm text-gray-300 mb-1">System Message</label>
              <textarea
                value={form.system_message}
                onChange={(e) => updateField('system_message', e.target.value)}
                rows={8}
                className="w-full px-3 py-2 bg-gray-700 text-white rounded border border-gray-600 focus:border-blue-500 focus:outline-none font-mono text-sm"
              />
            </div>

            <div>
              <label className="block text-sm text-gray-300 mb-1">
                Output Format Instructions
              </label>
              <textarea
                value={form.output_format_instructions}
                onChange={(e) => updateField('output_format_instructions', e.target.value)}
                rows={3}
                className="w-full px-3 py-2 bg-gray-700 text-white rounded border border-gray-600 focus:border-blue-500 focus:outline-none font-mono text-sm"
              />
            </div>

            <div>
              <label className="block text-sm text-gray-300 mb-1">
                Context Template
                <span className="text-gray-500 ml-2 font-normal">
                  (placeholders: {'{input_artifacts}'}, {'{component_key}'})
                </span>
              </label>
              <textarea
                value={form.context_template}
                onChange={(e) => updateField('context_template', e.target.value)}
                rows={4}
                className="w-full px-3 py-2 bg-gray-700 text-white rounded border border-gray-600 focus:border-blue-500 focus:outline-none font-mono text-sm"
              />
            </div>

            <div>
              <label className="block text-sm text-gray-300 mb-1">
                Revision Instructions
              </label>
              <textarea
                value={form.revision_instructions}
                onChange={(e) => updateField('revision_instructions', e.target.value)}
                rows={3}
                className="w-full px-3 py-2 bg-gray-700 text-white rounded border border-gray-600 focus:border-blue-500 focus:outline-none font-mono text-sm"
              />
            </div>

            <div className="grid grid-cols-3 gap-4">
              <div>
                <label className="block text-sm text-gray-300 mb-1">Model</label>
                <select
                  value={form.model || ''}
                  onChange={(e) => updateField('model', e.target.value || null)}
                  className="w-full px-3 py-2 bg-gray-700 text-white rounded border border-gray-600 focus:border-blue-500 focus:outline-none text-sm"
                >
                  <option value="">Default</option>
                  {MODEL_OPTIONS.map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-sm text-gray-300 mb-1">Temperature</label>
                <input
                  type="number"
                  value={form.temperature ?? ''}
                  onChange={(e) =>
                    updateField('temperature', e.target.value ? parseFloat(e.target.value) : null)
                  }
                  min={0}
                  max={1}
                  step={0.1}
                  placeholder="Default"
                  className="w-full px-3 py-2 bg-gray-700 text-white rounded border border-gray-600 focus:border-blue-500 focus:outline-none text-sm"
                />
              </div>

              <div>
                <label className="block text-sm text-gray-300 mb-1">Max Tokens</label>
                <input
                  type="number"
                  value={form.max_tokens}
                  onChange={(e) => updateField('max_tokens', parseInt(e.target.value) || 8192)}
                  min={256}
                  max={32768}
                  step={256}
                  className="w-full px-3 py-2 bg-gray-700 text-white rounded border border-gray-600 focus:border-blue-500 focus:outline-none text-sm"
                />
              </div>
            </div>

            <div className="flex items-center gap-3 pt-2">
              <button
                onClick={handleSave}
                disabled={saving}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded disabled:opacity-50"
              >
                {saving ? 'Saving...' : 'Save'}
              </button>
              <button
                onClick={handleReset}
                className="px-4 py-2 bg-gray-600 hover:bg-gray-500 text-white text-sm rounded"
              >
                Reset to Default
              </button>
              {saved && <span className="text-green-400 text-sm">Saved!</span>}
            </div>
          </div>
        ) : (
          <p className="text-gray-500 text-sm">Select a stage to edit its prompt configuration.</p>
        )}
      </div>
    </div>
  );
}
