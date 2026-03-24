import { useParams } from 'react-router-dom';
import InputDocsPanel from '../input-docs/InputDocsPanel';
import { PanelErrorBoundary } from '../ErrorBoundary';

export default function InputDocsTab() {
  const { id: projectId } = useParams<{ id: string }>();
  return (
    <div className="flex-1 overflow-hidden">
      <PanelErrorBoundary fallbackLabel="Input docs error">
        <InputDocsPanel projectId={projectId!} />
      </PanelErrorBoundary>
    </div>
  );
}
