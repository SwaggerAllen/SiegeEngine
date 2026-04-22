import * as api from '../../api/subcomparch';
import { makeBootstrapMutations } from '../useBootstrapHooks';
import { subcomparchKeys } from '../queries/useSubcomparchQueries';

const m = makeBootstrapMutations(
  'subcomparch',
  {
    postFeedback: (...args: Array<string | number>) => api.postFeedback(...(args as Parameters<typeof api.postFeedback>)),
    approveDraft: (pid, pcid, sid, did) => api.approveDraft(pid, pcid, sid, did),
    discardDraft: (pid, pcid, sid, did) => api.discardDraft(pid, pcid, sid, did),
    cancelGeneration: (pid, pcid, sid) => api.cancelGeneration(pid, pcid, sid),
    resetTier: (pid, pcid, sid) => api.resetSubcomparch(pid, pcid, sid),
    retryReview: (pid, pcid, sid) => api.retryReview(pid, pcid, sid),
  },
  subcomparchKeys
);

export const useSubcomparchFeedbackMutation = m.useFeedbackMutation;
export const useSubcomparchApproveMutation = m.useApproveMutation;
export const useSubcomparchCancelGenerationMutation = m.useCancelGenerationMutation;
export const useSubcomparchResetMutation = m.useResetMutation;
export const useSubcomparchReviewRetryMutation = m.useReviewRetryMutation;
