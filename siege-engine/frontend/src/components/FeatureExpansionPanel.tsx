import { useScopeState } from '../hooks/queries/useScopeState';
import type { BodyScope } from '../api/siege';
import { BootstrapDraftPanel } from './BootstrapDraftPanel';
import { hintForStatus } from './skillHints';

interface Props {
  projectId: string;
}

const SCOPE: BodyScope = { tier: 'feature_expansion', comp_id: 'proj' };

export function FeatureExpansionPanel({ projectId }: Props) {
  const { state, draftBody, reviewBody, isLoading, error } = useScopeState(projectId, SCOPE);
  return (
    <BootstrapDraftPanel
      scopeName="Feature Expansion"
      tierLabel="feature expansion"
      state={state}
      draftBody={draftBody}
      reviewBody={reviewBody}
      isLoading={isLoading}
      error={error}
      skillHint={hintForStatus('feature-expansion', state?.status, 'proj')}
    />
  );
}
