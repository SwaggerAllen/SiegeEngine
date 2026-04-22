import * as implApi from '../../api/impl';
import { makeBootstrapMutations } from '../useBootstrapHooks';
import { implKeys } from '../queries/useImplQueries';

// Phase 8: two mutation factories, one per URL shape. Each
// binds the matching api function. Both share `implKeys` so
// the cache invalidations fire on the same key namespace.

const topLevel = makeBootstrapMutations(
  'impl',
  {
    postFeedback: (...args: Array<string | number>) => implApi.postImplTopLevelFeedback(...(args as [string, string, string])),
    approveDraft: (pid, cid, did) => implApi.approveImplTopLevelDraft(pid, cid, did),
    discardDraft: (pid, cid, did) => implApi.discardImplTopLevelDraft(pid, cid, did),
    cancelGeneration: (pid, cid) => implApi.cancelImplTopLevelGeneration(pid, cid),
    resetTier: (pid, cid) => implApi.resetImplTopLevel(pid, cid),
    retryReview: (pid, cid) => implApi.retryImplTopLevelReview(pid, cid),
  },
  implKeys,
);

const sub = makeBootstrapMutations(
  'impl',
  {
    postFeedback: (...args: Array<string | number>) => implApi.postImplSubFeedback(...(args as [string, string, string, string])),
    approveDraft: (pid, pcid, sid, did) => implApi.approveImplSubDraft(pid, pcid, sid, did),
    discardDraft: (pid, pcid, sid, did) => implApi.discardImplSubDraft(pid, pcid, sid, did),
    cancelGeneration: (pid, pcid, sid) => implApi.cancelImplSubGeneration(pid, pcid, sid),
    resetTier: (pid, pcid, sid) => implApi.resetImplSub(pid, pcid, sid),
    retryReview: (pid, pcid, sid) => implApi.retryImplSubReview(pid, pcid, sid),
  },
  implKeys,
);

// Top-level impl mutation hooks — `(projectId, compId, ...)` signatures.
export const useImplTopLevelFeedbackMutation = topLevel.useFeedbackMutation;
export const useImplTopLevelApproveMutation = topLevel.useApproveMutation;
export const useImplTopLevelDiscardMutation = topLevel.useDiscardMutation;
export const useImplTopLevelCancelGenerationMutation =
  topLevel.useCancelGenerationMutation;
export const useImplTopLevelResetMutation = topLevel.useResetMutation;
export const useImplTopLevelReviewRetryMutation = topLevel.useReviewRetryMutation;

// Per-sub impl mutation hooks — `(projectId, parentCompId, subId, ...)`.
export const useImplSubFeedbackMutation = sub.useFeedbackMutation;
export const useImplSubApproveMutation = sub.useApproveMutation;
export const useImplSubDiscardMutation = sub.useDiscardMutation;
export const useImplSubCancelGenerationMutation = sub.useCancelGenerationMutation;
export const useImplSubResetMutation = sub.useResetMutation;
export const useImplSubReviewRetryMutation = sub.useReviewRetryMutation;
