import { useSubreqs } from '../hooks/queries/useSubreqsQueries';
import {
  useApproveMutation,
  useCancelGenerationMutation,
  useDiscardMutation,
  useFeedbackMutation,
} from '../hooks/mutations/useSubreqsMutations';
import {
  BootstrapDraftPanel,
  type BootstrapPanelLabels,
} from './BootstrapDraftPanel';
import { subreqsRenderers } from './xml';

interface Props {
  projectId: string;
  componentId: string;
  componentName: string;
}

function makeLabels(componentName: string): BootstrapPanelLabels {
  return {
    loadingMessage: `Loading ${componentName} subrequirements…`,
    loadErrorTitle: `Failed to load ${componentName} subrequirements`,
    generatingMessage: `Generating ${componentName} subrequirements…`,
    draftHeading: `${componentName} — Subrequirements Draft`,
    feedbackPlaceholder: 'e.g. Add explicit retry backoff, tighten scope…',
    readOnlyExplanation:
      'Further subresponsibility-layer edits happen on individual subresp nodes and on this component\u2019s architecture doc once Phase 4 lands.',
  };
}

/**
 * Four-state review panel for a single component's subreqs node.
 *
 * Thin wrapper around :component:`BootstrapDraftPanel`. Labels are
 * parameterized by the component name so users immediately see
 * which component's subreqs they're reviewing.
 */
export function SubreqsPanel({ projectId, componentId, componentName }: Props) {
  const { data, error, isLoading } = useSubreqs(projectId, componentId);
  const feedbackMutation = useFeedbackMutation(projectId, componentId);
  const approveMutation = useApproveMutation(projectId, componentId);
  const discardMutation = useDiscardMutation(projectId, componentId);
  const cancelMutation = useCancelGenerationMutation(projectId, componentId);

  const isBusy =
    feedbackMutation.isPending ||
    approveMutation.isPending ||
    discardMutation.isPending ||
    cancelMutation.isPending;

  return (
    <BootstrapDraftPanel
      data={data}
      isLoading={isLoading}
      error={error}
      labels={makeLabels(componentName)}
      callbacks={{
        onFeedback: (f) => feedbackMutation.mutate(f),
        onApprove: (id) => approveMutation.mutate(id),
        onDiscard: (id) => discardMutation.mutate(id),
        onRetry: () => feedbackMutation.mutate(''),
        onCancel: () => cancelMutation.mutate(),
        isBusy,
      }}
      contentRenderers={subreqsRenderers}
    />
  );
}
