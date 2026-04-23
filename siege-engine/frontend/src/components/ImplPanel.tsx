import {
  BootstrapDraftPanel,
  type BootstrapPanelLabels,
} from './BootstrapDraftPanel';
import {
  useImplSub,
  useImplTopLevel,
} from '../hooks/queries/useImplQueries';
import {
  useImplSubApproveMutation,
  useImplSubCancelGenerationMutation,
  useImplSubFeedbackMutation,
  useImplSubResetMutation,
  useImplSubReviewRetryMutation,
  useImplTopLevelApproveMutation,
  useImplTopLevelCancelGenerationMutation,
  useImplTopLevelFeedbackMutation,
  useImplTopLevelResetMutation,
  useImplTopLevelReviewRetryMutation,
} from '../hooks/mutations/useImplMutations';
import { implRenderers } from './xml';

interface TopLevelProps {
  kind: 'top-level';
  projectId: string;
  compId: string;
  ownerName: string;
}

interface SubProps {
  kind: 'sub';
  projectId: string;
  parentCompId: string;
  subId: string;
  ownerName: string;
}

type Props = TopLevelProps | SubProps;

function makeLabels(ownerName: string): BootstrapPanelLabels {
  return {
    loadingMessage: `Loading ${ownerName} implementation…`,
    loadErrorTitle: `Failed to load ${ownerName} implementation`,
    generatingMessage: `Generating ${ownerName} implementation…`,
    draftHeading: `${ownerName} — Implementation Draft`,
    feedbackPlaceholder:
      'e.g. Tighten the sequencing around session rotation; note the race with logout…',
    // Impl is explicitly NOT frozen after approval (destructive
    // edit gate only). The BootstrapDraftPanel still shows this
    // text when the approved-content state renders; we override
    // the wording to make clear feedback reopens the draft cycle.
    readOnlyExplanation:
      'Implementation stays editable after approval. Send feedback at any time to reopen the draft cycle; destructive edits (delete, merge) go through the pending-change queue in Phase 11.',
  };
}

/**
 * Four-state review panel for a single implementation node.
 *
 * Two shapes share one component:
 * - Top-level (un-fanned-out): scoped by ``(projectId, compId)``
 * - Per-sub: scoped by ``(projectId, parentCompId, subId)``
 *
 * The discriminated union on ``kind`` keeps both wired to the
 * right hooks + API layer without touching BootstrapDraftPanel's
 * shape — it just receives the data/mutations and renders.
 */
export function ImplPanel(props: Props) {
  if (props.kind === 'top-level') {
    return <ImplPanelTopLevel {...props} />;
  }
  return <ImplPanelSub {...props} />;
}

function ImplPanelTopLevel({
  projectId,
  compId,
  ownerName,
}: TopLevelProps) {
  const { data, error, isLoading } = useImplTopLevel(projectId, compId);
  const feedbackMutation = useImplTopLevelFeedbackMutation(projectId, compId);
  const approveMutation = useImplTopLevelApproveMutation(projectId, compId);
  const cancelMutation = useImplTopLevelCancelGenerationMutation(projectId, compId);
  const resetMutation = useImplTopLevelResetMutation(projectId, compId);
  const reviewRetryMutation = useImplTopLevelReviewRetryMutation(projectId, compId);

  const isBusy =
    feedbackMutation.isPending ||
    approveMutation.isPending ||
    cancelMutation.isPending ||
    resetMutation.isPending ||
    reviewRetryMutation.isPending;

  return (
    <BootstrapDraftPanel
      projectId={projectId}
      data={data}
      isLoading={isLoading}
      error={error}
      labels={makeLabels(ownerName)}
      callbacks={{
        onFeedback: (f, autoRev) =>
          feedbackMutation.mutate({ feedback: f, autoRevisionsRequested: autoRev ?? 0 }),
        onApprove: (id) => approveMutation.mutate(id),
        onRetry: () => feedbackMutation.mutate(''),
        onCancel: () => cancelMutation.mutate(),
        onReset: () => resetMutation.mutate(),
        onRetryReview: () => reviewRetryMutation.mutate(),
        isBusy,
      }}
      contentRenderers={implRenderers}
    />
  );
}

function ImplPanelSub({
  projectId,
  parentCompId,
  subId,
  ownerName,
}: SubProps) {
  const { data, error, isLoading } = useImplSub(projectId, parentCompId, subId);
  const feedbackMutation = useImplSubFeedbackMutation(projectId, parentCompId, subId);
  const approveMutation = useImplSubApproveMutation(projectId, parentCompId, subId);
  const cancelMutation = useImplSubCancelGenerationMutation(
    projectId,
    parentCompId,
    subId,
  );
  const resetMutation = useImplSubResetMutation(projectId, parentCompId, subId);
  const reviewRetryMutation = useImplSubReviewRetryMutation(
    projectId,
    parentCompId,
    subId,
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
      labels={makeLabels(ownerName)}
      callbacks={{
        onFeedback: (f, autoRev) =>
          feedbackMutation.mutate({ feedback: f, autoRevisionsRequested: autoRev ?? 0 }),
        onApprove: (id) => approveMutation.mutate(id),
        onRetry: () => feedbackMutation.mutate(''),
        onCancel: () => cancelMutation.mutate(),
        onReset: () => resetMutation.mutate(),
        onRetryReview: () => reviewRetryMutation.mutate(),
        isBusy,
      }}
      contentRenderers={implRenderers}
    />
  );
}
