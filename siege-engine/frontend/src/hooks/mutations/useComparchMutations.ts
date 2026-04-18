import * as api from '../../api/comparch';
import { makeBootstrapMutations } from '../useBootstrapHooks';
import { comparchKeys } from '../queries/useComparchQueries';

const m = makeBootstrapMutations(
  'comparch',
  {
    postFeedback: (pid, cid, fb) => api.postFeedback(pid, cid, fb),
    approveDraft: (pid, cid, did) => api.approveDraft(pid, cid, did),
    discardDraft: (pid, cid, did) => api.discardDraft(pid, cid, did),
    cancelGeneration: (pid, cid) => api.cancelGeneration(pid, cid),
    resetTier: (pid, cid) => api.resetComparch(pid, cid),
    retryReview: (pid, cid) => api.retryReview(pid, cid),
  },
  comparchKeys
);

export const useFeedbackMutation = m.useFeedbackMutation;
export const useApproveMutation = m.useApproveMutation;
export const useDiscardMutation = m.useDiscardMutation;
export const useCancelGenerationMutation = m.useCancelGenerationMutation;
export const useResetMutation = m.useResetMutation;
export const useReviewRetryMutation = m.useReviewRetryMutation;
