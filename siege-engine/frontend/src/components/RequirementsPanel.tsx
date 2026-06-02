import { useScopeState } from '../hooks/queries/useScopeState';
import type { BodyScope } from '../api/siege';
import { BootstrapDraftPanel } from './BootstrapDraftPanel';
import { hintForStatus } from './skillHints';

interface Props {
  projectId: string;
}

const SCOPE: BodyScope = { tier: 'requirements', comp_id: 'proj' };

export function RequirementsPanel({ projectId }: Props) {
  const { state, draftBody, reviewBody, isLoading, error } = useScopeState(projectId, SCOPE);
  return (
    <BootstrapDraftPanel
      scopeName="Requirements"
      tierLabel="requirements"
      state={state}
      draftBody={draftBody}
      reviewBody={reviewBody}
      isLoading={isLoading}
      error={error}
      skillHint={hintForStatus('requirements', state?.status, 'proj')}
    />
  );
}
