import { describe, it, expect } from 'vitest';
import { findSelectedExecution } from './ProjectDashboardLayout';
import type { StageExecution } from '../schemas/pipeline';
import type { Artifact } from '../schemas/project';

// Minimal fixture helpers
function makeExec(overrides: Partial<StageExecution>): StageExecution {
  return {
    id: 'exec-1',
    stage_key: 'stage_a',
    component_key: null,
    status: 'pending',
    artifact_id: null,
    started_at: null,
    completed_at: null,
    error_message: null,
    run_id: 'run-1',
    ...overrides,
  };
}

function makeArtifact(overrides: Partial<Artifact>): Artifact {
  return {
    id: 'artifact-1',
    project_id: 'proj-1',
    artifact_type: 'component_spec',
    name: 'My Artifact',
    component_key: 'comp_a',
    content: null,
    summary_generating: false,
    status: 'awaiting_review',
    is_stale: false,
    version: 1,
    ai_review_feedback: null,
    human_review_notes: null,
    file_path: null,
    git_commit_sha: null,
    language: null,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    ...overrides,
  };
}

describe('findSelectedExecution', () => {
  it('priority 1: returns exact artifact match with awaiting_review', () => {
    const artifact = makeArtifact({ id: 'a1', status: 'awaiting_review' });
    const executions = [
      makeExec({ id: 'e1', artifact_id: 'a1', status: 'awaiting_review' }),
      makeExec({ id: 'e2', artifact_id: 'a1', status: 'approved' }),
    ];
    expect(findSelectedExecution(executions, artifact)?.id).toBe('e1');
  });

  it('priority 2: returns exact artifact match when no awaiting_review exists', () => {
    const artifact = makeArtifact({ id: 'a1', status: 'approved' });
    const executions = [
      makeExec({ id: 'e1', artifact_id: 'a1', status: 'approved' }),
    ];
    expect(findSelectedExecution(executions, artifact)?.id).toBe('e1');
  });

  it('priority 1 beats priority 2 when both artifact matches exist', () => {
    const artifact = makeArtifact({ id: 'a1', status: 'awaiting_review' });
    const executions = [
      makeExec({ id: 'e1', artifact_id: 'a1', status: 'approved' }),
      makeExec({ id: 'e2', artifact_id: 'a1', status: 'awaiting_review' }),
    ];
    expect(findSelectedExecution(executions, artifact)?.id).toBe('e2');
  });

  it('priority 3: returns component_key match when no artifact_id and generation in progress', () => {
    const artifact = makeArtifact({ id: 'a1', component_key: 'comp_a', status: 'generating', artifact_type: 'component_spec' });
    const executions = [
      makeExec({ id: 'e1', artifact_id: null, component_key: 'comp_a', status: 'running' }),
    ];
    expect(findSelectedExecution(executions, artifact)?.id).toBe('e1');
  });

  it('priority 4: returns component_key match when both are awaiting_review (regeneration edge case)', () => {
    const artifact = makeArtifact({ id: 'a1', component_key: 'comp_a', status: 'awaiting_review', artifact_type: 'component_spec' });
    const executions = [
      makeExec({ id: 'e1', artifact_id: null, component_key: 'comp_a', status: 'awaiting_review' }),
    ];
    expect(findSelectedExecution(executions, artifact)?.id).toBe('e1');
  });

  it('project_doc artifact type skips component_key fallbacks (returns undefined)', () => {
    const artifact = makeArtifact({ id: 'a1', component_key: 'comp_a', status: 'generating', artifact_type: 'project_doc' });
    const executions = [
      makeExec({ id: 'e1', artifact_id: null, component_key: 'comp_a', status: 'running' }),
      makeExec({ id: 'e2', artifact_id: null, component_key: 'comp_a', status: 'awaiting_review' }),
    ];
    expect(findSelectedExecution(executions, artifact)).toBeUndefined();
  });

  it('returns undefined when no execution matches', () => {
    const artifact = makeArtifact({ id: 'a1', component_key: 'comp_a', status: 'approved', artifact_type: 'component_spec' });
    const executions = [
      makeExec({ id: 'e1', artifact_id: 'other-artifact', status: 'approved', component_key: 'other_comp' }),
    ];
    expect(findSelectedExecution(executions, artifact)).toBeUndefined();
  });
});
