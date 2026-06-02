import { useScopeState } from '../hooks/queries/useScopeState';
import type { BodyScope } from '../api/siege';
import { BootstrapDraftPanel } from './BootstrapDraftPanel';
import { hintForStatus } from './skillHints';

interface Props {
  projectId: string;
  componentId: string;
  componentName: string;
}

export function ComparchPanel({ projectId, componentId, componentName }: Props) {
  const scope: BodyScope = { tier: 'comparch', comp_id: componentId };
  const { state, draftBody, reviewBody, isLoading, error } = useScopeState(projectId, scope);
  return (
    <BootstrapDraftPanel
      scopeName={`${componentName} — Architecture Doc`}
      tierLabel={`${componentName} architecture`}
      state={state}
      draftBody={draftBody}
      reviewBody={reviewBody}
      isLoading={isLoading}
      error={error}
      skillHint={hintForStatus('comparch', state?.status, componentId)}
    />
  );
}
