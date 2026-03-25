import { useState, useEffect } from 'react';
import { NavLink } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { useProject } from '../../hooks/queries/useProjectQueries';
import { useAuthStore } from '../../store/authStore';
import { useDAGStore } from '../../store/dagStore';
import { usePipelineUIStore } from '../../store/pipelineUIStore';
import { pipelineKeys } from '../../hooks/queries/usePipelineQueries';
import { RunSelector } from '../pipeline/RunSelector';
import { PipelineControls } from '../pipeline/PipelineControls';
import { InvitePanel } from '../auth/InvitePanel';
import { PRDialog } from '../../pages/ProjectDashboardLayout';
import { reconcilePipeline } from '../../api/pipeline';

type Tab = 'documents' | 'pipeline' | 'prompts' | 'input-docs' | 'chat' | 'settings' | 'history' | 'logs' | 'debug';

const TAB_LABELS: Record<Tab, string> = {
  documents: 'Documents',
  pipeline: 'Pipeline',
  prompts: 'Prompts',
  'input-docs': 'Input Docs',
  chat: 'Chat',
  settings: 'Settings',
  history: 'Event History',
  logs: 'Logs',
  debug: 'Debug',
};

interface HeaderDrawerProps {
  projectId: string;
  visibleTabs: Tab[];
  onClose: () => void;
}

export function HeaderDrawer({ projectId, visibleTabs, onClose }: HeaderDrawerProps) {
  const user = useAuthStore((s) => s.user);
  const isAdmin = user?.role === 'admin';
  const isViewer = user?.role === 'viewer';
  const isViewingHistory = usePipelineUIStore((s) => s.isViewingHistory);
  const { data: currentProject } = useProject(projectId);
  const hasRemote = !!currentProject?.remote_url;
  const hasGitHub = !!currentProject?.github_repo_slug;
  const clearSelection = useDAGStore((s) => s.clearSelection);
  const queryClient = useQueryClient();

  const [showInvites, setShowInvites] = useState(false);
  const [showPRDialog, setShowPRDialog] = useState(false);
  const [repairing, setRepairing] = useState(false);
  const [repairResult, setRepairResult] = useState<string | null>(null);

  useEffect(() => {
    if (!repairResult) return;
    const t = setTimeout(() => setRepairResult(null), 4000);
    return () => clearTimeout(t);
  }, [repairResult]);

  const handleRepair = async () => {
    if (repairing) return;
    setRepairing(true);
    setRepairResult(null);
    try {
      const result = await reconcilePipeline(projectId);
      const fixes = result.corrections.length + result.orphans_removed.length;
      setRepairResult(fixes > 0 ? `Fixed ${fixes} issue${fixes > 1 ? 's' : ''}` : 'No issues found');
      if (fixes > 0) {
        queryClient.invalidateQueries({ queryKey: pipelineKeys.status(projectId) });
        queryClient.invalidateQueries({ queryKey: pipelineKeys.runs(projectId) });
      }
    } catch {
      setRepairResult('Repair failed');
    } finally {
      setRepairing(false);
    }
  };

  const handleNavClick = () => {
    clearSelection();
    onClose();
  };

  // All tabs shown in drawer, always including debug
  const drawerTabs = visibleTabs.includes('debug' as Tab)
    ? visibleTabs
    : [...visibleTabs, 'debug' as Tab];

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 z-40 bg-black/60" onClick={onClose} />

      {/* Drawer panel — slides down from top */}
      <div className="fixed inset-x-0 top-0 z-50 bg-gray-900 shadow-2xl flex flex-col overflow-y-auto max-h-[90vh]">
        {/* Drawer header row */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700 shrink-0">
          <span className="text-sm font-semibold text-white">Menu</span>
          <button
            onClick={onClose}
            className="p-1 text-gray-400 hover:text-white"
            aria-label="Close menu"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Run controls */}
        {!isViewingHistory && (
          <div className="px-4 py-3 border-b border-gray-700 space-y-3">
            <RunSelector projectId={projectId} />
            {!isViewer && (
              <PipelineControls projectId={projectId} hasGitHub={hasGitHub} />
            )}
          </div>
        )}

        {/* Admin / project controls */}
        <div className="px-4 py-3 border-b border-gray-700 flex flex-wrap gap-2 items-center">
          {!isViewer && hasRemote && !isViewingHistory && (
            <button
              onClick={() => setShowPRDialog(true)}
              className="px-3 py-2 bg-purple-600 hover:bg-purple-700 text-white text-sm rounded"
            >
              Open PR
            </button>
          )}
          {isAdmin && (
            <button
              onClick={() => setShowInvites(true)}
              className="px-3 py-2 bg-gray-700 hover:bg-gray-600 text-white text-sm rounded"
            >
              Invites
            </button>
          )}
          <button
            onClick={handleRepair}
            disabled={repairing}
            className="px-3 py-2 bg-gray-700 hover:bg-gray-600 text-gray-300 text-sm rounded disabled:opacity-50 flex items-center gap-1.5"
          >
            <svg
              className={`w-4 h-4 ${repairing ? 'animate-spin' : ''}`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              {repairing ? (
                <>
                  <circle className="opacity-25" cx="12" cy="12" r="10" strokeWidth="4" />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    stroke="none"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                  />
                </>
              ) : (
                <>
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"
                  />
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
                  />
                </>
              )}
            </svg>
            {repairing ? 'Repairing...' : 'Sync / Repair'}
          </button>
          {repairResult && (
            <span
              className={`text-sm ${
                repairResult.startsWith('Fixed')
                  ? 'text-green-400'
                  : repairResult === 'No issues found'
                  ? 'text-gray-400'
                  : 'text-red-400'
              }`}
            >
              {repairResult}
            </span>
          )}
        </div>

        {/* Navigation */}
        <nav>
          {drawerTabs.map((tab) => (
            <NavLink
              key={tab}
              to={tab}
              onClick={handleNavClick}
              className={({ isActive }) =>
                `block px-4 py-4 text-sm border-b border-gray-800 ${
                  isActive
                    ? 'bg-gray-700 text-white font-medium'
                    : 'text-gray-300 hover:bg-gray-800 hover:text-white'
                }`
              }
            >
              {TAB_LABELS[tab]}
            </NavLink>
          ))}
        </nav>
      </div>

      {showInvites && <InvitePanel onClose={() => setShowInvites(false)} />}
      {showPRDialog && <PRDialog projectId={projectId} onClose={() => setShowPRDialog(false)} />}
    </>
  );
}
