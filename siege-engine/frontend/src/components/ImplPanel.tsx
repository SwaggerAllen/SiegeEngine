import { useScopeState } from '../hooks/queries/useScopeState';
import type { BodyScope } from '../api/siege';
import { BootstrapDraftPanel } from './BootstrapDraftPanel';
import { hintForStatus } from './skillHints';

interface TopLevelProps {
  kind: 'top-level';
  projectId: string;
  compId: string;
  ownerName: string;
  phase?: number | null;
}

interface SubProps {
  kind: 'sub';
  projectId: string;
  parentCompId: string;
  subId: string;
  ownerName: string;
  phase?: number | null;
}

type Props = TopLevelProps | SubProps;

/**
 * Read-only inspection panel for an implementation node.
 *
 * Two shapes share one component:
 * - Top-level (un-fanned-out): scoped by ``(comp_id, phase?)``
 * - Per-sub: scoped by ``(parent_id, sub_id, phase?)``
 *
 * Impl is phased; ``phase`` defaults to unphased (pre-phasing
 * artifacts and the v1 schema). The phased dimension is wired
 * through unchanged so the dashboard can render a specific phase
 * once the nav links pass one in.
 */
export function ImplPanel(props: Props) {
  const scope: BodyScope =
    props.kind === 'top-level'
      ? { tier: 'impl', comp_id: props.compId, phase: props.phase ?? null }
      : {
          tier: 'impl',
          parent_id: props.parentCompId,
          sub_id: props.subId,
          phase: props.phase ?? null,
        };
  const id = props.kind === 'top-level' ? props.compId : props.subId;
  const { state, draftBody, reviewBody, isLoading, error } = useScopeState(
    props.projectId,
    scope,
  );
  return (
    <BootstrapDraftPanel
      scopeName={`${props.ownerName} — Implementation`}
      tierLabel={`${props.ownerName} implementation`}
      state={state}
      draftBody={draftBody}
      reviewBody={reviewBody}
      isLoading={isLoading}
      error={error}
      skillHint={hintForStatus('impl', state?.status, id)}
    />
  );
}
