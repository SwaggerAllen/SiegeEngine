import { useScopeState } from '../hooks/queries/useScopeState';
import type { BodyScope } from '../api/siege';
import { BootstrapDraftPanel } from './BootstrapDraftPanel';
import { hintForStatus } from './skillHints';

interface Props {
  projectId: string;
  compId: string;
  ownerName: string;
  phase?: number | null;
}

/**
 * Read-only inspection panel for a fan-in synthesis node.
 *
 * Fan-in carries a draft + review lifecycle in v3 like the other
 * tiers (the legacy "writes content directly" path is gone); the
 * panel reads through the same composite state hook as every other
 * tier and renders the bodies verbatim.
 */
export function FanInPanel({ projectId, compId, ownerName, phase }: Props) {
  const scope: BodyScope = { tier: 'fanin', comp_id: compId, phase: phase ?? null };
  const { state, draftBody, reviewBody, isLoading, error } = useScopeState(projectId, scope);
  return (
    <BootstrapDraftPanel
      scopeName={`${ownerName} — Fan-in`}
      tierLabel={`${ownerName} fan-in`}
      state={state}
      draftBody={draftBody}
      reviewBody={reviewBody}
      isLoading={isLoading}
      error={error}
      skillHint={hintForStatus('fanin', state?.status, compId)}
    />
  );
}
