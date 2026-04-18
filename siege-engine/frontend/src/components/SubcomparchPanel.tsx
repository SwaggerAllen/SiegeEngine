import { useSubcomparch } from '../hooks/queries/useSubcomparchQueries';
import {
  useSubcomparchApproveMutation,
  useSubcomparchCancelGenerationMutation,
  useSubcomparchFeedbackMutation,
  useSubcomparchResetMutation,
  useSubcomparchReviewRetryMutation,
} from '../hooks/mutations/useSubcomparchMutations';
import {
  BootstrapDraftPanel,
  type BootstrapPanelLabels,
} from './BootstrapDraftPanel';
import { subcomparchRenderers } from './xml';

interface Props {
  projectId: string;
  parentCompId: string;
  subId: string;
  subName: string;
}

function makeLabels(subName: string): BootstrapPanelLabels {
  return {
    loadingMessage: `Loading ${subName} architecture doc…`,
    loadErrorTitle: `Failed to load ${subName} architecture doc`,
    generatingMessage: `Generating ${subName} architecture doc…`,
    draftHeading: `${subName} — Subcomponent Architecture Doc Draft`,
    feedbackPlaceholder:
      'e.g. Narrow the public surface; move the rotation cadence to a private helper…',
    readOnlyExplanation:
      'The subcomponent architecture is the anchor for its impl node and dependency edges downstream. Further edits happen via the structural-edit UIs coming in Phase 11.',
  };
}

/**
 * Four-state review panel for a single subcomponent's
 * architecture doc. Thin wrapper around BootstrapDraftPanel —
 * supplies labels, data source, mutations, and the subcomparch
 * schema renderer map. Scoped by the
 * ``(projectId, parentCompId, subId)`` triple because
 * subcomparch routes nest one level deeper than comparch.
 */
export function SubcomparchPanel({
  projectId,
  parentCompId,
  subId,
  subName,
}: Props) {
  const { data, error, isLoading } = useSubcomparch(projectId, parentCompId, subId);
  const feedbackMutation = useSubcomparchFeedbackMutation(
    projectId,
    parentCompId,
    subId
  );
  const approveMutation = useSubcomparchApproveMutation(
    projectId,
    parentCompId,
    subId
  );
  const cancelMutation = useSubcomparchCancelGenerationMutation(
    projectId,
    parentCompId,
    subId
  );
  const resetMutation = useSubcomparchResetMutation(
    projectId,
    parentCompId,
    subId
  );
  const reviewRetryMutation = useSubcomparchReviewRetryMutation(
    projectId,
    parentCompId,
    subId
  );

  const isBusy =
    feedbackMutation.isPending ||
    approveMutation.isPending ||
    cancelMutation.isPending ||
    resetMutation.isPending ||
    reviewRetryMutation.isPending;

  return (
    <BootstrapDraftPanel
      data={data}
      isLoading={isLoading}
      error={error}
      labels={makeLabels(subName)}
      callbacks={{
        onFeedback: (f) => feedbackMutation.mutate(f),
        onApprove: (id) => approveMutation.mutate(id),
        onRetry: () => feedbackMutation.mutate(''),
        onCancel: () => cancelMutation.mutate(),
        onReset: () => resetMutation.mutate(),
        onRetryReview: () => reviewRetryMutation.mutate(),
        isBusy,
      }}
      contentRenderers={subcomparchRenderers}
    />
  );
}
