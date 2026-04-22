import * as api from '../../api/sysarch';
import { makeBootstrapMutations } from '../useBootstrapHooks';
import { sysarchKeys } from '../queries/useSysarchQueries';

const m = makeBootstrapMutations(
  'sysarch',
  {
    postFeedback: (...args: Array<string | number>) => api.postFeedback(...(args as Parameters<typeof api.postFeedback>)),
    approveDraft: (pid, did) => api.approveDraft(pid, did),
    discardDraft: (pid, did) => api.discardDraft(pid, did),
    cancelGeneration: (pid) => api.cancelGeneration(pid),
    resetTier: (pid) => api.resetSysarch(pid),
    retryReview: (pid) => api.retryReview(pid),
  },
  sysarchKeys
);

export const useFeedbackMutation = m.useFeedbackMutation;
export const useApproveMutation = m.useApproveMutation;
export const useDiscardMutation = m.useDiscardMutation;
export const useCancelGenerationMutation = m.useCancelGenerationMutation;
export const useResetMutation = m.useResetMutation;
export const useReviewRetryMutation = m.useReviewRetryMutation;
