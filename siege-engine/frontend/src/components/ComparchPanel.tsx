import { useMemo } from 'react';
import { useComparch } from '../hooks/queries/useComparchQueries';
import { useFeatures } from '../hooks/queries/useFeatureQueries';
import { useResponsibilities } from '../hooks/queries/useRequirementsQueries';
import {
  useApproveMutation,
  useCancelGenerationMutation,
  useFeedbackMutation,
  useResetMutation,
  useReviewRetryMutation,
} from '../hooks/mutations/useComparchMutations';
import {
  BootstrapDraftPanel,
  type BootstrapPanelLabels,
} from './BootstrapDraftPanel';
import { makeComparchRenderers } from './xml';

interface Props {
  projectId: string;
  componentId: string;
  componentName: string;
}

function makeLabels(componentName: string): BootstrapPanelLabels {
  return {
    loadingMessage: `Loading ${componentName} architecture doc…`,
    loadErrorTitle: `Failed to load ${componentName} architecture doc`,
    generatingMessage: `Generating ${componentName} architecture doc…`,
    draftHeading: `${componentName} — Architecture Doc Draft`,
    feedbackPlaceholder:
      'e.g. Split TokenStore into separate storage + rotation subcomponents…',
    readOnlyExplanation:
      'The component architecture is the anchor for subcomponents, component-local policies, and external dependency edges downstream. Further edits land on individual nodes via the structural-edit UIs coming in Phase 11.',
  };
}

/**
 * Four-state review panel for a single top-level component's
 * architecture doc. Thin wrapper around BootstrapDraftPanel —
 * supplies labels, data source, mutations, and the comparch
 * schema renderer map.
 */
export function ComparchPanel({ projectId, componentId, componentName }: Props) {
  const { data, error, isLoading } = useComparch(projectId, componentId);
  const { data: respsData } = useResponsibilities(projectId);
  const { data: featsData } = useFeatures(projectId);
  const feedbackMutation = useFeedbackMutation(projectId, componentId);
  const approveMutation = useApproveMutation(projectId, componentId);
  const cancelMutation = useCancelGenerationMutation(projectId, componentId);
  const resetMutation = useResetMutation(projectId, componentId);
  const reviewRetryMutation = useReviewRetryMutation(projectId, componentId);

  const isBusy =
    feedbackMutation.isPending ||
    approveMutation.isPending ||
    cancelMutation.isPending ||
    resetMutation.isPending ||
    reviewRetryMutation.isPending;

  // Per-subcomponent <owns> rendering needs project-level resp +
  // feat name lookups so each claim shows ``Name (resp_id)`` and
  // each feat-slice chip shows ``FeatName (feat_id)`` instead of
  // bare IDs.
  const renderers = useMemo(() => {
    const respNames: Record<string, string> = {};
    for (const r of respsData?.responsibilities ?? []) {
      respNames[r.id] = r.name;
    }
    const featureNames: Record<string, string> = {};
    for (const f of featsData?.features ?? []) {
      featureNames[f.id] = f.name;
    }
    return makeComparchRenderers(respNames, featureNames);
  }, [respsData, featsData]);

  return (
    <BootstrapDraftPanel
      projectId={projectId}
      data={data}
      isLoading={isLoading}
      error={error}
      labels={makeLabels(componentName)}
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
      contentRenderers={renderers}
    />
  );
}
