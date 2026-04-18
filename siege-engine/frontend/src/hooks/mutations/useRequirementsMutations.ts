import * as api from '../../api/requirements';
import { makeBootstrapMutations } from '../useBootstrapHooks';
import { requirementsKeys } from '../queries/useRequirementsQueries';

const m = makeBootstrapMutations(
  'requirements',
  {
    postFeedback: (pid, fb) => api.postFeedback(pid, fb),
    approveDraft: (pid, did) => api.approveDraft(pid, did),
    discardDraft: (pid, did) => api.discardDraft(pid, did),
    cancelGeneration: (pid) => api.cancelGeneration(pid),
    resetTier: (pid) => api.resetRequirements(pid),
    retryReview: (pid) => api.retryReview(pid),
  },
  requirementsKeys
);

export const useFeedbackMutation = m.useFeedbackMutation;
export const useApproveMutation = m.useApproveMutation;
export const useDiscardMutation = m.useDiscardMutation;
export const useCancelGenerationMutation = m.useCancelGenerationMutation;
export const useResetMutation = m.useResetMutation;
export const useReviewRetryMutation = m.useReviewRetryMutation;
