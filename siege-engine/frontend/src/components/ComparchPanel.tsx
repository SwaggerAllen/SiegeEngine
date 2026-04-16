import { useComparch } from '../hooks/queries/useComparchQueries';
import {
  useApproveMutation,
<<<<<<< HEAD
  useCancelGenerationMutation,
  useDiscardMutation,
=======
>>>>>>> bc67e15 (v2: destructive sysarch reset + merge regen buttons)
  useFeedbackMutation,
} from '../hooks/mutations/useComparchMutations';
import {
  BootstrapDraftPanel,
  type BootstrapPanelLabels,
} from './BootstrapDraftPanel';
import { comparchRenderers } from './xml';

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
  const feedbackMutation = useFeedbackMutation(projectId, componentId);
  const approveMutation = useApproveMutation(projectId, componentId);
<<<<<<< HEAD
  const discardMutation = useDiscardMutation(projectId, componentId);
  const cancelMutation = useCancelGenerationMutation(projectId, componentId);

  const isBusy =
    feedbackMutation.isPending ||
    approveMutation.isPending ||
    discardMutation.isPending ||
    cancelMutation.isPending;
=======

  const isBusy = feedbackMutation.isPending || approveMutation.isPending;
>>>>>>> bc67e15 (v2: destructive sysarch reset + merge regen buttons)

  return (
    <BootstrapDraftPanel
      data={data}
      isLoading={isLoading}
      error={error}
      labels={makeLabels(componentName)}
      callbacks={{
        onFeedback: (f) => feedbackMutation.mutate(f),
        onApprove: (id) => approveMutation.mutate(id),
        onRetry: () => feedbackMutation.mutate(''),
        onCancel: () => cancelMutation.mutate(),
        isBusy,
      }}
      contentRenderers={comparchRenderers}
    />
  );
}
