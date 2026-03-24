import { useParams } from 'react-router-dom';
import { ProjectSettingsPanel } from '../project/ProjectSettingsPanel';
import { PanelErrorBoundary } from '../ErrorBoundary';

export default function SettingsTab() {
  const { id: projectId } = useParams<{ id: string }>();
  return (
    <div className="flex-1 overflow-auto">
      <PanelErrorBoundary fallbackLabel="Settings error">
        <ProjectSettingsPanel projectId={projectId!} />
      </PanelErrorBoundary>
    </div>
  );
}
