import { useScopeState } from '../hooks/queries/useScopeState';
import type { BodyScope } from '../api/siege';
import { BootstrapDraftPanel } from './BootstrapDraftPanel';
import { hintForStatus } from './skillHints';

interface Props {
  projectId: string;
  parentCompId: string;
  subId: string;
  subName: string;
}

export function SubcomparchPanel({ projectId, parentCompId, subId, subName }: Props) {
  const scope: BodyScope = {
    tier: 'subcomparch',
    parent_id: parentCompId,
    sub_id: subId,
  };
  const { state, draftBody, reviewBody, isLoading, error } = useScopeState(projectId, scope);
  return (
    <BootstrapDraftPanel
      scopeName={`${subName} — Subcomponent Architecture`}
      tierLabel={`${subName} subcomponent architecture`}
      state={state}
      draftBody={draftBody}
      reviewBody={reviewBody}
      isLoading={isLoading}
      error={error}
      skillHint={hintForStatus('subcomparch', state?.status, subId)}
    />
  );
}
