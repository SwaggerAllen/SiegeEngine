import { applyWSEvent, patchExecutions, emptySnapshot } from './pipelineReducer';
import type { StageExecution, WSEvent } from '../types/pipeline';

const makeExec = (overrides: Partial<StageExecution> = {}): StageExecution => ({
  id: 'exec-1',
  stage_key: 'design',
  component_key: null,
  status: 'pending',
  artifact_id: null,
  started_at: null,
  completed_at: null,
  error_message: null,
  run_id: 'run-1',
  ...overrides,
});

describe('patchExecutions', () => {
  it('patches status to running on stage_started', () => {
    const execs = [makeExec()];
    const event: WSEvent = { type: 'stage_started', stage_key: 'design' };

    const result = patchExecutions(execs, event);

    expect(result).not.toBe(execs); // new array
    expect(result[0].status).toBe('running');
    expect(result[0].id).toBe('exec-1'); // unchanged fields preserved
  });

  it('patches status and artifact_id on stage_awaiting_review', () => {
    const execs = [makeExec({ status: 'running' })];
    const event: WSEvent = { type: 'stage_awaiting_review', stage_key: 'design', artifact_id: 'art-1' };

    const result = patchExecutions(execs, event);

    expect(result[0].status).toBe('awaiting_review');
    expect(result[0].artifact_id).toBe('art-1');
  });

  it('patches status on stage_completed', () => {
    const execs = [makeExec({ status: 'awaiting_review' })];
    const event: WSEvent = { type: 'stage_completed', stage_key: 'design', status: 'approved' };

    const result = patchExecutions(execs, event);

    expect(result[0].status).toBe('approved');
  });

  it('defaults to approved when stage_completed has no status', () => {
    const execs = [makeExec({ status: 'awaiting_review' })];
    const event: WSEvent = { type: 'stage_completed', stage_key: 'design' };

    const result = patchExecutions(execs, event);

    expect(result[0].status).toBe('approved');
  });

  it('patches status and error_message on stage_failed', () => {
    const execs = [makeExec({ status: 'running' })];
    const event: WSEvent = { type: 'stage_failed', stage_key: 'design', error: 'timeout' };

    const result = patchExecutions(execs, event);

    expect(result[0].status).toBe('failed');
    expect(result[0].error_message).toBe('timeout');
  });

  it('matches by component_key', () => {
    const execs = [
      makeExec({ id: 'exec-1', component_key: 'auth' }),
      makeExec({ id: 'exec-2', component_key: 'billing' }),
    ];
    const event: WSEvent = { type: 'stage_started', stage_key: 'design', component_key: 'billing' };

    const result = patchExecutions(execs, event);

    expect(result[0].status).toBe('pending'); // auth unchanged
    expect(result[1].status).toBe('running'); // billing patched
  });

  it('prefers active execution when multiple match', () => {
    const execs = [
      makeExec({ id: 'exec-old', status: 'approved' }),
      makeExec({ id: 'exec-active', status: 'running' }),
    ];
    const event: WSEvent = { type: 'stage_failed', stage_key: 'design', error: 'crash' };

    const result = patchExecutions(execs, event);

    // Should patch the active one, not the approved one
    expect(result.find((e) => e.id === 'exec-active')!.status).toBe('failed');
    expect(result.find((e) => e.id === 'exec-old')!.status).toBe('approved');
  });

  it('returns same reference for unmatched events', () => {
    const execs = [makeExec({ stage_key: 'implement' })];
    const event: WSEvent = { type: 'stage_started', stage_key: 'design' };

    const result = patchExecutions(execs, event);

    expect(result).toBe(execs); // referential equality — no copy
  });

  it('returns same reference for non-stage events', () => {
    const execs = [makeExec()];
    const event: WSEvent = { type: 'pipeline_completed', run_id: 'run-1' };

    const result = patchExecutions(execs, event);

    expect(result).toBe(execs);
  });
});

describe('applyWSEvent', () => {
  it('sets stage to running on stage_started', () => {
    const snap = applyWSEvent(emptySnapshot(), { type: 'stage_started', stage_key: 'design' });

    expect(snap.stage_statuses['design']).toBe('running');
    expect(snap.is_running).toBe(true);
  });

  it('handles composite stage key with component', () => {
    const snap = applyWSEvent(emptySnapshot(), {
      type: 'stage_started',
      stage_key: 'design',
      component_key: 'auth',
    });

    expect(snap.stage_statuses['design/auth']).toBe('running');
  });

  it('clears is_running on pipeline_completed', () => {
    const running = { ...emptySnapshot(), is_running: true };
    const snap = applyWSEvent(running, { type: 'pipeline_completed', run_id: 'r1' });

    expect(snap.is_running).toBe(false);
    expect(snap.run_status['r1']).toBe('completed');
  });

  it('propagates staleness to multiple artifacts', () => {
    const snap = applyWSEvent(emptySnapshot(), {
      type: 'staleness_propagated',
      stale_artifact_ids: ['a1', 'a2'],
    });

    expect(snap.artifact_statuses['a1']).toBe('stale');
    expect(snap.artifact_statuses['a2']).toBe('stale');
  });
});
