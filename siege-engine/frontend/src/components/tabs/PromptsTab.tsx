import { useState } from 'react';
import { useLocation, useOutletContext } from 'react-router-dom';
import type { DashboardContext } from './types';
import { PromptEditorPanel } from '../pipeline/PromptEditorPanel';
import { PanelErrorBoundary } from '../ErrorBoundary';

export default function PromptsTab() {
  const { projectId } = useOutletContext<DashboardContext>();
  const location = useLocation();
  const [initialStageKey, setInitialStageKey] = useState<string | null>(
    (location.state as { initialStageKey?: string } | null)?.initialStageKey ?? null,
  );

  return (
    <div className="flex-1 overflow-hidden">
      <PanelErrorBoundary fallbackLabel="Prompt editor error">
        <PromptEditorPanel
          projectId={projectId}
          initialStageKey={initialStageKey}
          onStageKeyConsumed={() => setInitialStageKey(null)}
        />
      </PanelErrorBoundary>
    </div>
  );
}
