import type { StageExecution } from '../schemas/pipeline';
import type { Artifact } from '../types/project';

/**
 * Find the most relevant StageExecution for a selected artifact.
 *
 * Fallback priority:
 * 1. Exact artifact match + awaiting_review (show Approve/Reject)
 * 2. Exact artifact match, any status
 * 3. Component key match, no artifact_id yet (generation died before artifact was created)
 * 4. Component key match, both awaiting_review (regeneration edge case with stale artifact_id)
 *
 * Input docs (project_doc) skip component_key fallbacks — they have no StageExecution.
 */
export function findSelectedExecution(
  executions: StageExecution[],
  artifact: Artifact,
): StageExecution | undefined {
  const isInputDoc = artifact.artifact_type === 'project_doc';
  return (
    // 1. Awaiting review for this artifact (needs user action)
    executions.find((e) => e.artifact_id === artifact.id && e.status === 'awaiting_review') ??
    // 2. Active generation for this component (running/pending — show live timer)
    (!isInputDoc
      ? executions.find(
          (e) =>
            !e.artifact_id &&
            e.component_key === (artifact.component_key ?? null) &&
            ['running', 'ai_review', 'pending'].includes(e.status) &&
            ['generating', 'ai_reviewing', 'pending'].includes(artifact.status),
        )
      : undefined) ??
    // 3. Historical execution that produced this artifact
    executions.find((e) => e.artifact_id === artifact.id) ??
    // 4. Failed execution for this component
    (!isInputDoc
      ? executions.find(
          (e) =>
            !e.artifact_id &&
            e.component_key === (artifact.component_key ?? null) &&
            ['failed', 'awaiting_review'].includes(e.status) &&
            ['generating', 'ai_reviewing', 'pending', 'awaiting_review'].includes(artifact.status),
        )
      : undefined) ??
    // 5. Awaiting review by component key
    (!isInputDoc
      ? executions.find(
          (e) =>
            e.component_key === (artifact.component_key ?? null) &&
            e.status === 'awaiting_review' &&
            artifact.status === 'awaiting_review',
        )
      : undefined)
  );
}
