import { useOutletContext } from 'react-router-dom';
import type { DashboardContext } from './types';
import { ProjectSettingsPanel } from '../project/ProjectSettingsPanel';
import { PanelErrorBoundary } from '../ErrorBoundary';

export default function SettingsTab() {
  const { projectId } = useOutletContext<DashboardContext>();
  return (
    <div className="flex-1 overflow-auto">
      <PanelErrorBoundary fallbackLabel="Settings error">
        <ProjectSettingsPanel projectId={projectId} />
      </PanelErrorBoundary>
    </div>
  );
}
