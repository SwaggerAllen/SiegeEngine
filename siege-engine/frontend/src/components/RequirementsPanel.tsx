import { useRequirements } from '../hooks/queries/useRequirementsQueries';
import {
  useApproveMutation,
  useDiscardMutation,
  useFeedbackMutation,
} from '../hooks/mutations/useRequirementsMutations';
import {
  BootstrapDraftPanel,
  type BootstrapPanelLabels,
} from './BootstrapDraftPanel';
import { requirementsRenderers } from './xml';

interface Props {
  projectId: string;
}

const LABELS: BootstrapPanelLabels = {
  loadingMessage: 'Loading requirements…',
  loadErrorTitle: 'Failed to load requirements',
  generatingMessage: 'Generating requirements…',
  draftHeading: 'Requirements — Draft',
  feedbackPlaceholder: 'e.g. Add rate limiting, split Auth into two…',
  readOnlyExplanation:
    'Further responsibility-layer edits happen on individual responsibility nodes once Phase 10 lands.',
};

/**
 * Four-state review panel for the project's reqs node. Thin
 * wrapper around :component:`BootstrapDraftPanel` — supplies the
 * requirements-specific labels, data source, mutations, and
 * content renderer map, and defers the entire state machine to
 * the shared shell.
 */
export function RequirementsPanel({ projectId }: Props) {
  const { data, error, isLoading } = useRequirements(projectId);
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
      contentRenderers={requirementsRenderers}
    />
  );
}
