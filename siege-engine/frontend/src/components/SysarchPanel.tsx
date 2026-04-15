import { useMemo } from 'react';
import { useResponsibilities } from '../hooks/queries/useRequirementsQueries';
import { useSysarch } from '../hooks/queries/useSysarchQueries';
import {
  useApproveMutation,
  useDiscardMutation,
  useFeedbackMutation,
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
 * The renderer map is built via ``makeSysarchRenderers`` with a
 * live ``resp_*`` → name map from ``useResponsibilities`` so
 * component cards' "Responsibilities" lists and policy "requires"
 * lines render ``name (resp_xxxxxxxx)`` instead of bare IDs. The
 * responsibilities query is fetched with ``mintPending=true`` so
 * it activates as soon as the reqs node has been approved and
 * top-level ``resp_*`` nodes exist — sysarch generation blocks on
 * that step anyway, so by the time the user looks at the sysarch
 * draft, the name map is populated.
 */
export function SysarchPanel({ projectId }: Props) {
  const { data, error, isLoading } = useSysarch(projectId);
  const { data: respsData } = useResponsibilities(projectId, true);
  const feedbackMutation = useFeedbackMutation(projectId);
  const approveMutation = useApproveMutation(projectId);
  const discardMutation = useDiscardMutation(projectId);

  const isBusy =
    feedbackMutation.isPending || approveMutation.isPending || discardMutation.isPending;

  const renderers = useMemo(() => {
    const respNames: Record<string, string> = {};
    for (const r of respsData?.responsibilities ?? []) {
      respNames[r.id] = r.name;
    }
    return makeSysarchRenderers(respNames);
  }, [respsData]);

  return (
    <BootstrapDraftPanel
      data={data}
      isLoading={isLoading}
      error={error}
      labels={LABELS}
      callbacks={{
        onFeedback: (f) => feedbackMutation.mutate(f),
        onApprove: (id) => approveMutation.mutate(id),
        onDiscard: (id) => discardMutation.mutate(id),
        onRetry: () => feedbackMutation.mutate(''),
        isBusy,
      }}
      contentRenderers={renderers}
    />
  );
}
