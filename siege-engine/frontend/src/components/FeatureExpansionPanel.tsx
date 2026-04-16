import { useExpansion } from '../hooks/queries/useExpansionQueries';
import {
  useApproveMutation,
  useCancelGenerationMutation,
  useFeedbackMutation,
  useResetMutation,
} from '../hooks/mutations/useExpansionMutations';
import { getPromptPreview } from '../api/expansion';
import {
  BootstrapDraftPanel,
  type BootstrapPanelLabels,
} from './BootstrapDraftPanel';
import { featureRenderers } from './xml';

interface Props {
  projectId: string;
}

const LABELS: BootstrapPanelLabels = {
  loadingMessage: 'Loading feature expansion…',
  loadErrorTitle: 'Failed to load feature expansion',
  generatingMessage: 'Generating feature expansion…',
  draftHeading: 'Feature Expansion — Draft',
  feedbackPlaceholder: 'e.g. Add reporting, tighten scope on auth…',
  readOnlyExplanation:
    'Further feature-layer edits happen on individual feature nodes once Phase 2 lands.',
};

export function FeatureExpansionPanel({ projectId }: Props) {
  const { data, error, isLoading } = useExpansion(projectId);
  const feedbackMutation = useFeedbackMutation(projectId);
  const approveMutation = useApproveMutation(projectId);
  const cancelMutation = useCancelGenerationMutation(projectId);
  const resetMutation = useResetMutation(projectId);

  const isBusy =
    feedbackMutation.isPending ||
    approveMutation.isPending ||
    cancelMutation.isPending ||
    resetMutation.isPending;

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
        isBusy,
      }}
      contentRenderers={featureRenderers}
      getPromptPreview={(fb) => getPromptPreview(projectId, fb)}
    />
  );
}
