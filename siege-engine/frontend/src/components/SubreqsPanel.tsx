import { useMemo } from 'react';
import {
  useApproveMutation,
  useCancelGenerationMutation,
  useFeedbackMutation,
  useResetMutation,
  useReviewRetryMutation,
} from '../hooks/mutations/useSubreqsMutations';
import { useFeatures } from '../hooks/queries/useFeatureQueries';
import { useProjectStructure } from '../hooks/queries/useProjectStructure';
import { useSubreqs } from '../hooks/queries/useSubreqsQueries';
import {
  BootstrapDraftPanel,
  type BootstrapPanelLabels,
} from './BootstrapDraftPanel';
import { SubreqsListTab } from './SubreqsListTab';
import { makeSubreqsRenderers } from './xml';

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
      'Further subresponsibility-layer edits happen on individual subresp nodes and on this component’s architecture doc once Phase 4 lands.',
  };
}

/**
 * Four-state review panel for a single component's subreqs node.
 *
 * Modeled on :component:`RequirementsPanel`: the panel hands
 * :component:`BootstrapDraftPanel` an ``extraTabs`` injection that
 * adds a "Subresponsibilities" subtab between Document and Review.
 * The sub-tab parses the draft / approved content and renders
 * subresps grouped under the parent resps assigned to this
 * component (mirroring the requirements tab's "responsibilities
 * with their feature coverage" layout, one tier deeper).
 *
 * The owning component's assigned parent resps come from the
 * project structure snapshot. The pre-tab "Responsibilities"
 * coverage summary is gone — the new tab structure carries the
 * same information without doubling the vertical scroll.
 */
export function SubreqsPanel({ projectId, componentId, componentName }: Props) {
  const { data, error, isLoading } = useSubreqs(projectId, componentId);
  const { data: structure } = useProjectStructure(projectId);
  const { data: featuresData } = useFeatures(projectId);
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

  // Parent resps for this component — top-level resp nodes that
  // route to this comp via decomposition edges. Order by
  // display_order so the rendered group headers track the
  // sysarch ordering.
  const parentResps = useMemo(() => {
    if (!structure) return [];
    const receivedIds = new Set(
      structure.edges
        .filter(
          (e) => e.edge_type === 'decomposition' && e.target_id === componentId,
        )
        .map((e) => e.source_id),
    );
    return structure.nodes
      .filter(
        (n) =>
          n.tier === 'resp' && n.parent_id === null && receivedIds.has(n.id),
      )
      .sort((a, b) => a.display_order - b.display_order)
      .map((n) => ({ id: n.id, name: n.name }));
  }, [structure, componentId]);

  const featureNames = useMemo(() => {
    const map: Record<string, string> = {};
    for (const f of featuresData?.features ?? []) {
      map[f.id] = f.name;
    }
    return map;
  }, [featuresData]);

  const renderers = useMemo(
    () => makeSubreqsRenderers(featureNames),
    [featureNames],
  );

  return (
    <BootstrapDraftPanel
      projectId={projectId}
      data={data}
      isLoading={isLoading}
      error={error}
      labels={makeLabels(componentName)}
      callbacks={{
        onFeedback: (f, autoRev) =>
          feedbackMutation.mutate({
            feedback: f,
            autoRevisionsRequested: autoRev ?? 0,
          }),
        onApprove: (id) => approveMutation.mutate(id),
        onRetry: () => feedbackMutation.mutate(''),
        onCancel: () => cancelMutation.mutate(),
        onReset: () => resetMutation.mutate(),
        onRetryReview: () => reviewRetryMutation.mutate(),
        isBusy,
      }}
      contentRenderers={renderers}
      extraTabs={({ pendingContent, approvedContent }) => [
        {
          id: 'subresps',
          label: 'Subresponsibilities',
          content: (
            <SubreqsListTab
              content={pendingContent ?? approvedContent}
              parentResps={parentResps}
              featureNames={featureNames}
            />
          ),
        },
      ]}
    />
  );
}
