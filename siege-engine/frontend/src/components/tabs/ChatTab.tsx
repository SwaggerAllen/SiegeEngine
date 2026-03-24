import { useOutletContext } from 'react-router-dom';
import type { DashboardContext } from './types';
import { ChatPanel } from '../chat/ChatPanel';
import { PanelErrorBoundary } from '../ErrorBoundary';

export default function ChatTab() {
  const { projectId } = useOutletContext<DashboardContext>();
  return (
    <div className="flex-1 overflow-hidden">
      <PanelErrorBoundary fallbackLabel="Chat error">
        <ChatPanel projectId={projectId} />
      </PanelErrorBoundary>
    </div>
  );
}
