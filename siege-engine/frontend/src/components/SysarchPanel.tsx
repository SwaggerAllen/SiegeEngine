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
import { sysarchRenderers } from './xml';

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
 */
export function SysarchPanel({ projectId }: Props) {
  const { data, error, isLoading } = useSysarch(projectId);
  const feedbackMutation = useFeedbackMutation(projectId);
  const approveMutation = useApproveMutation(projectId);
  const discardMutation = useDiscardMutation(projectId);

  const isBusy =
    feedbackMutation.isPending || approveMutation.isPending || discardMutation.isPending;

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
      contentRenderers={sysarchRenderers}
    />
  );
}
