import * as api from '../../api/subcomparch';
import { makeBootstrapMutations } from '../useBootstrapHooks';
import { decompositionGraphKeys } from '../queries/useDecompositionGraph';
import { componentsKeys } from '../queries/useSysarchQueries';
import { subcomparchKeys } from '../queries/useSubcomparchQueries';

const m = makeBootstrapMutations(
  'subcomparch',
  {
    postFeedback: (pid, pcid, sid, fb) => api.postFeedback(pid, pcid, sid, fb),
    approveDraft: (pid, pcid, sid, did) => api.approveDraft(pid, pcid, sid, did),
    discardDraft: (pid, pcid, sid, did) => api.discardDraft(pid, pcid, sid, did),
    cancelGeneration: (pid, pcid, sid) => api.cancelGeneration(pid, pcid, sid),
  },
  subcomparchKeys,
  (queryClient, projectId) => {
    queryClient.invalidateQueries({ queryKey: componentsKeys.list(projectId) });
    queryClient.invalidateQueries({
      queryKey: decompositionGraphKeys.detail(projectId),
    });
  }
);

export const useSubcomparchFeedbackMutation = m.useFeedbackMutation;
export const useSubcomparchApproveMutation = m.useApproveMutation;
export const useSubcomparchCancelGenerationMutation = m.useCancelGenerationMutation;
