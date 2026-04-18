import { useMemo } from 'react';
import { useResponsibilities } from '../hooks/queries/useRequirementsQueries';
import { useComponents, useSysarch } from '../hooks/queries/useSysarchQueries';
import {
  useApproveMutation,
  useCancelGenerationMutation,
  useFeedbackMutation,
  useResetMutation,
  useReviewRetryMutation,
} from '../hooks/mutations/useSysarchMutations';
import {
  BootstrapDraftPanel,
  type BootstrapPanelLabels,
} from './BootstrapDraftPanel';
import { makeSysarchRenderers } from './xml';

interface Props {
  projectId: string;
}

const LABELS: BootstrapPanelLabels = {
  loadingMessage: 'Loading system architecture…',
  loadErrorTitle: 'Failed to load system architecture',
  generatingMessage: 'Generating system architecture…',
  draftHeading: 'System Architecture — Draft',
  feedbackPlaceholder: 'e.g. Split Billing into Subscription + Invoicing…',
  readOnlyExplanation:
    'Further component-layer edits happen on individual component arch docs once Phase 4 lands.',
};

/**
 * Four-state review panel for the project's sysarch node.
 * Thin wrapper around :component:`BootstrapDraftPanel` — supplies
 * labels, data source, mutations, and the sysarch schema
 * renderer map.
 *
 * The renderer map is built via ``makeSysarchRenderers`` with two
 * live maps:
 *
 * 1. A ``resp_*`` → name map from ``useResponsibilities`` so
 *    component cards' "Responsibilities" lists and policy
 *    "requires" lines render ``name (resp_xxxxxxxx)`` instead of
 *    bare IDs.
 * 2. A component-name → pending-draft-kind map from
 *    ``useComponents`` so each component card can show a
 *    "Waiting — subreqs / comparch / subcomparch" badge while
 *    downstream drafts are awaiting user approval. The sysarch
 *    document only contains aliases + names, so the lookup is
 *    name-keyed — the components list query resolves name →
 *    comp_id internally.
 *
 * Both queries run with no ``mintPending`` gate — sysarch
 * generation is downstream of reqs_mint, so by the time the
 * panel renders, the upstream lists are already populated and a
 * single fetch on mount is enough. React Query's default
 * refetch-on-mount picks up new pending drafts when the user
 * navigates back to the tab.
 */
export function SysarchPanel({ projectId }: Props) {
  const { data, error, isLoading } = useSysarch(projectId);
  const { data: respsData } = useResponsibilities(projectId);
  const { data: componentsData } = useComponents(projectId);
  const feedbackMutation = useFeedbackMutation(projectId);
  const approveMutation = useApproveMutation(projectId);
  const cancelMutation = useCancelGenerationMutation(projectId);
  const resetMutation = useResetMutation(projectId);
  const reviewRetryMutation = useReviewRetryMutation(projectId);

  const isBusy =
    feedbackMutation.isPending ||
    approveMutation.isPending ||
    cancelMutation.isPending ||
    resetMutation.isPending ||
    reviewRetryMutation.isPending;

  const renderers = useMemo(() => {
    const respNames: Record<string, string> = {};
    for (const r of respsData?.responsibilities ?? []) {
      respNames[r.id] = r.name;
    }
    const pendingByName: Record<string, string> = {};
    for (const c of componentsData?.components ?? []) {
      if (c.pending_draft_kind) {
        pendingByName[c.name] = c.pending_draft_kind;
      }
    }
    return makeSysarchRenderers(respNames, pendingByName);
  }, [respsData, componentsData]);

  return (
    <BootstrapDraftPanel
      data={data}
      isLoading={isLoading}
      error={error}
      labels={LABELS}
      callbacks={{
        onFeedback: (f) => feedbackMutation.mutate(f),
        onApprove: (id) => approveMutation.mutate(id),
        onRetry: () => feedbackMutation.mutate(''),
        onCancel: () => cancelMutation.mutate(),
        onReset: () => resetMutation.mutate(),
        onRetryReview: () => reviewRetryMutation.mutate(),
        isBusy,
      }}
      contentRenderers={renderers}
    />
  );
}
