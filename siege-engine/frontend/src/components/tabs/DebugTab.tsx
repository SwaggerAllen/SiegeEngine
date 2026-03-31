import { useParams } from 'react-router-dom';
import { DebugStatePanel } from '../pipeline/DebugStatePanel';
import { PanelErrorBoundary } from '../ErrorBoundary';

export default function DebugTab() {
  const { id: projectId } = useParams<{ id: string }>();
  return (
    <div className="flex-1 overflow-hidden">
      <PanelErrorBoundary fallbackLabel="Debug panel error">
        <DebugStatePanel projectId={projectId!} />
      </PanelErrorBoundary>
    </div>
  );
}
