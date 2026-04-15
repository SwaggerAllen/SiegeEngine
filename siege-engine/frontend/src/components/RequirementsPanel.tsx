import { useMemo } from 'react';
import { useFeatures } from '../hooks/queries/useFeatureQueries';
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
import { makeRequirementsRenderers } from './xml';

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
 *
 * The renderer map is built via ``makeRequirementsRenderers`` with
 * a live feature-name map so each ``<responsibility>`` card's
 * "Covers" footer renders ``name (feat_xxxxxxxx)`` for every
 * upstream feature instead of bare IDs. Features are fetched with
 * ``mintPending=true`` so the query runs as soon as the expansion
 * has been approved and downstream features exist — without that
 * gate the query would be disabled and we'd fall back to bare IDs.
 */
export function RequirementsPanel({ projectId }: Props) {
  const { data, error, isLoading } = useRequirements(projectId);
  const { data: featuresData } = useFeatures(projectId, true);
  const feedbackMutation = useFeedbackMutation(projectId);
  const approveMutation = useApproveMutation(projectId);
  const discardMutation = useDiscardMutation(projectId);

  const isBusy =
    feedbackMutation.isPending || approveMutation.isPending || discardMutation.isPending;

  const renderers = useMemo(() => {
    const featureNames: Record<string, string> = {};
    for (const f of featuresData?.features ?? []) {
      featureNames[f.id] = f.name;
    }
    return makeRequirementsRenderers(featureNames);
  }, [featuresData]);

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
