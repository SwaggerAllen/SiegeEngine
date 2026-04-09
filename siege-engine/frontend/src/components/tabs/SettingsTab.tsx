import { useParams } from 'react-router-dom';
import { ProjectSettingsPanel } from '../project/ProjectSettingsPanel';
import { PipelineConfigPanel } from '../pipeline/PipelineConfigPanel';
import { PanelErrorBoundary } from '../ErrorBoundary';

export default function SettingsTab() {
  const { id: projectId } = useParams<{ id: string }>();
  return (
    <div className="flex-1 overflow-auto">
      <PanelErrorBoundary fallbackLabel="Settings error">
        <ProjectSettingsPanel projectId={projectId!} />
      </PanelErrorBoundary>
      <div className="px-4 pb-4 max-w-xl">
        <div className="border-t border-gray-700 pt-4">
          <PanelErrorBoundary fallbackLabel="Pipeline config error">
            <PipelineConfigPanel projectId={projectId!} />
          </PanelErrorBoundary>
        </div>
      </div>
    </div>
  );
}
