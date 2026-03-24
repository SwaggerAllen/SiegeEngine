import { useOutletContext } from 'react-router-dom';
import type { DashboardContext } from './types';
import InputDocsPanel from '../input-docs/InputDocsPanel';
import { PanelErrorBoundary } from '../ErrorBoundary';

export default function InputDocsTab() {
  const { projectId } = useOutletContext<DashboardContext>();
  return (
    <div className="flex-1 overflow-hidden">
      <PanelErrorBoundary fallbackLabel="Input docs error">
        <InputDocsPanel projectId={projectId} />
      </PanelErrorBoundary>
    </div>
  );
}
