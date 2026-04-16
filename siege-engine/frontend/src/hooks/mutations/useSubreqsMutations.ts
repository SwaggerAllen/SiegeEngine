import * as api from '../../api/subreqs';
import { makeBootstrapMutations } from '../useBootstrapHooks';
import { decompositionGraphKeys } from '../queries/useDecompositionGraph';
import { componentsKeys } from '../queries/useSysarchQueries';
import { subreqsKeys } from '../queries/useSubreqsQueries';

const m = makeBootstrapMutations(
  'subreqs',
  {
    postFeedback: (pid, cid, fb) => api.postFeedback(pid, cid, fb),
    approveDraft: (pid, cid, did) => api.approveDraft(pid, cid, did),
    discardDraft: (pid, cid, did) => api.discardDraft(pid, cid, did),
    cancelGeneration: (pid, cid) => api.cancelGeneration(pid, cid),
  },
  subreqsKeys,
  (queryClient, projectId) => {
    queryClient.invalidateQueries({ queryKey: componentsKeys.list(projectId) });
    queryClient.invalidateQueries({
      queryKey: decompositionGraphKeys.detail(projectId),
    });
  }
);

export const useFeedbackMutation = m.useFeedbackMutation;
export const useApproveMutation = m.useApproveMutation;
export const useDiscardMutation = m.useDiscardMutation;
export const useCancelGenerationMutation = m.useCancelGenerationMutation;
