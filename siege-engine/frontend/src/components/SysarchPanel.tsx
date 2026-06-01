import { useScopeState } from '../hooks/queries/useScopeState';
import type { BodyScope } from '../api/siege';
import { BootstrapDraftPanel } from './BootstrapDraftPanel';
import { hintForStatus } from './skillHints';

interface Props {
  projectId: string;
}

const SCOPE: BodyScope = { tier: 'sysarch', comp_id: 'proj' };

export function SysarchPanel({ projectId }: Props) {
  const { state, draftBody, reviewBody, isLoading, error } = useScopeState(projectId, SCOPE);
  return (
    <BootstrapDraftPanel
      scopeName="System Architecture"
      tierLabel="system architecture"
      state={state}
      draftBody={draftBody}
      reviewBody={reviewBody}
      isLoading={isLoading}
      error={error}
      skillHint={hintForStatus('sysarch', state?.status, 'proj')}
    />
  );
}
