import * as api from '../../api/expansion';
import { makeBootstrapMutations } from '../useBootstrapHooks';
import { expansionKeys } from '../queries/useExpansionQueries';

const m = makeBootstrapMutations(
  'expansion',
  {
    postFeedback: (pid, fb) => api.postFeedback(pid, fb),
    approveDraft: (pid, did) => api.approveDraft(pid, did),
    discardDraft: (pid, did) => api.discardDraft(pid, did),
    cancelGeneration: (pid) => api.cancelGeneration(pid),
    resetTier: (pid) => api.resetExpansion(pid),
    retryReview: (pid) => api.retryReview(pid),
  },
  expansionKeys
);

export const useFeedbackMutation = m.useFeedbackMutation;
export const useApproveMutation = m.useApproveMutation;
export const useDiscardMutation = m.useDiscardMutation;
export const useCancelGenerationMutation = m.useCancelGenerationMutation;
export const useResetMutation = m.useResetMutation;
export const useReviewRetryMutation = m.useReviewRetryMutation;
