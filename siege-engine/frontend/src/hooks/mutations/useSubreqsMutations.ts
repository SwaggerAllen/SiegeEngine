import * as api from '../../api/subreqs';
import { makeBootstrapMutations } from '../useBootstrapHooks';
import { subreqsKeys } from '../queries/useSubreqsQueries';

const m = makeBootstrapMutations(
  'subreqs',
  {
    postFeedback: (pid, cid, fb) => api.postFeedback(pid, cid, fb),
    approveDraft: (pid, cid, did) => api.approveDraft(pid, cid, did),
    discardDraft: (pid, cid, did) => api.discardDraft(pid, cid, did),
    cancelGeneration: (pid, cid) => api.cancelGeneration(pid, cid),
    resetTier: (pid, cid) => api.resetSubreqs(pid, cid),
    retryReview: (pid, cid) => api.retryReview(pid, cid),
  },
  subreqsKeys
);

export const useFeedbackMutation = m.useFeedbackMutation;
export const useApproveMutation = m.useApproveMutation;
export const useDiscardMutation = m.useDiscardMutation;
export const useCancelGenerationMutation = m.useCancelGenerationMutation;
export const useResetMutation = m.useResetMutation;
export const useReviewRetryMutation = m.useReviewRetryMutation;
