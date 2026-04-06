import { useParams } from 'react-router-dom';
import { useExecutions } from '../../hooks/queries/usePipelineQueries';
import { StageStatusList } from '../pipeline/StageStatus';
import { PanelErrorBoundary } from '../ErrorBoundary';
import { ArtifactTabLayout } from './ArtifactTabLayout';

function DefaultPipelineContent() {
  const { id: projectId } = useParams<{ id: string }>();
  const executions = useExecutions(projectId!);
  return (
    <div className="p-3">
      <PanelErrorBoundary fallbackLabel="Stage status error">
        <StageStatusList executions={executions} projectId={projectId!} />
      </PanelErrorBoundary>
    </div>
  );
}

export function PipelineTab() {
  return (
    <ArtifactTabLayout
      variant="pipeline"
      defaultPaneOpen
      defaultHandle={<span className="text-gray-500 text-xs flex-1">Pipeline stages</span>}
      defaultContent={<DefaultPipelineContent />}
    />
  );
}
