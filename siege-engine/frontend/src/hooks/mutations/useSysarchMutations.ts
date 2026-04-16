import * as api from '../../api/sysarch';
import { makeBootstrapMutations } from '../useBootstrapHooks';
import { componentsKeys, policiesKeys, sysarchKeys } from '../queries/useSysarchQueries';

const m = makeBootstrapMutations(
  'sysarch',
  {
    postFeedback: (pid, fb) => api.postFeedback(pid, fb),
    approveDraft: (pid, did) => api.approveDraft(pid, did),
    discardDraft: (pid, did) => api.discardDraft(pid, did),
    cancelGeneration: (pid) => api.cancelGeneration(pid),
    resetTier: (pid) => api.resetSysarch(pid),
  },
  sysarchKeys,
  (queryClient, projectId) => {
    queryClient.invalidateQueries({ queryKey: componentsKeys.list(projectId) });
    queryClient.invalidateQueries({ queryKey: policiesKeys.list(projectId) });
  }
);

export const useFeedbackMutation = m.useFeedbackMutation;
export const useApproveMutation = m.useApproveMutation;
export const useDiscardMutation = m.useDiscardMutation;
export const useCancelGenerationMutation = m.useCancelGenerationMutation;
export const useResetMutation = m.useResetMutation;
