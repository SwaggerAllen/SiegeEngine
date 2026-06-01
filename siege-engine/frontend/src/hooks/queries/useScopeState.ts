import { useQuery } from '@tanstack/react-query';
import { useSelectedRef } from '../../components/BranchSelector';
import {
  getBody,
  getScopeState,
  type BodyResponse,
  type BodyScope,
  type ScopeStateResponse,
} from '../../api/siege';

/**
 * Composite read hook for the read-only per-tier panels.
 *
 * Stitches together three siege calls:
 *   1. ``/get-state`` — the scope's state JSON (status, draft sha,
 *      review sha, approval block, edges, meta).
 *   2. ``/get-body?which=draft`` — the draft body file, only when the
 *      scope has a draft (status ≠ ``"absent"``).
 *   3. ``/get-body?which=review`` — the review body file, only when
 *      the scope has been reviewed (status ∈ {``"reviewed"``,
 *      ``"approved"``}).
 *
 * The body fetches are conditional on the state fetch resolving with
 * the right status, so an absent / drafted-only scope doesn't fan out
 * a useless 200-with-empty-body for the review side.
 *
 * The deployed dashboard panels are read-only — write actions live in
 * Claude Code skills. This hook is the read-half of that contract.
 */
export interface UseScopeStateResult {
  state: ScopeStateResponse | undefined;
  draftBody: BodyResponse | undefined;
  reviewBody: BodyResponse | undefined;
  isLoading: boolean;
  error: unknown;
}

export function useScopeState(projectId: string, scope: BodyScope): UseScopeStateResult {
  const ref = useSelectedRef();
  const stateQuery = useQuery<ScopeStateResponse>({
    queryKey: ['siege-state', projectId, ref, scope],
    queryFn: () => getScopeState(projectId, scope, ref),
  });

  const status = stateQuery.data?.status;
  // Draft body whenever the scope has any draft (drafted / reviewed /
  // approved). Absent skips the fetch entirely — there's no body to
  // read.
  const draftEnabled = stateQuery.data?.found === true && status !== 'absent';
  const draftQuery = useQuery<BodyResponse>({
    queryKey: ['siege-body', projectId, ref, scope, 'draft'],
    queryFn: () => getBody(projectId, scope, ref, 'draft'),
    enabled: draftEnabled,
  });

  const reviewEnabled =
    stateQuery.data?.found === true &&
    (status === 'reviewed' || status === 'approved');
  const reviewQuery = useQuery<BodyResponse>({
    queryKey: ['siege-body', projectId, ref, scope, 'review'],
    queryFn: () => getBody(projectId, scope, ref, 'review'),
    enabled: reviewEnabled,
  });

  return {
    state: stateQuery.data,
    draftBody: draftQuery.data,
    reviewBody: reviewQuery.data,
    isLoading:
      stateQuery.isLoading ||
      (draftEnabled && draftQuery.isLoading) ||
      (reviewEnabled && reviewQuery.isLoading),
    error: stateQuery.error ?? draftQuery.error ?? reviewQuery.error,
  };
}
