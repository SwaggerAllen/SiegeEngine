import { useParams } from 'react-router-dom';
import { EventHistoryPanel } from '../pipeline/EventHistoryPanel';
import { PanelErrorBoundary } from '../ErrorBoundary';

export default function HistoryTab() {
  const { id: projectId } = useParams<{ id: string }>();
  return (
    <div className="flex-1 overflow-hidden">
      <PanelErrorBoundary fallbackLabel="Event history error">
        <EventHistoryPanel projectId={projectId} />
      </PanelErrorBoundary>
    </div>
  );
}
