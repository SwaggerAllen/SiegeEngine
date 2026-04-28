import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TestQueryWrapper } from '../test/queryWrapper';
import { DebugPanel } from './DebugPanel';

function makeNodes(count: number, baseLength = 200) {
  return Array.from({ length: count }, (_, i) => ({
    id: `node_${i.toString().padStart(4, '0')}`,
    tier: 'feat',
    kind: 'domain',
    name: `Filler node ${i}`.padEnd(baseLength, '.'),
    parent_id: null,
    content_length: baseLength,
  }));
}

vi.mock('../api/debug', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/debug')>();
  return {
    ...actual,
    getDebugSnapshot: vi.fn(),
  };
});

import * as debugApi from '../api/debug';

const mockedGet = debugApi.getDebugSnapshot as unknown as ReturnType<typeof vi.fn>;

function makeSnapshot(): debugApi.DebugSnapshot {
  return {
    project: {
      id: 'proj_1',
      name: 'Dev',
      git_repo_path: '/tmp/dev',
      created_at: '2026-04-01T00:00:00',
    },
    summary: {
      node_count: 2,
      edge_count: 1,
      fragment_count: 0,
      draft_count: 1,
      staleness_rows: 0,
      jobs_returned: 1,
      events_returned: 2,
    },
    nodes: [
      {
        id: 'feat_aaa',
        tier: 'feat',
        kind: 'domain',
        name: 'Alpha',
        parent_id: null,
        content_length: 12,
      },
    ],
    edges: [
      {
        id: 'edge_1',
        edge_type: 'decomposition',
        source_id: 'feat_aaa',
        target_id: 'resp_bbb',
      },
    ],
    fragments: [],
    drafts: [
      {
        id: 'draft_1',
        target_id: 'comp_1',
        status: 'pending',
        content_length: 200,
      },
    ],
    staleness: [],
    recent_jobs: [
      {
        id: 'job_1',
        job_type: 'v2.generate_comparch',
        status: 'queued',
        retry_count: 0,
        is_deferred: false,
        error_message: null,
        payload: { project_id: 'proj_1', component_id: 'comp_1' },
        created_at: '2026-04-26T12:00:00',
      },
    ],
    recent_events: [
      {
        id: 'ev_1',
        offset: 1,
        event_type: 'NodeCreated',
        payload: { node_id: 'feat_aaa' },
        created_at: '2026-04-25T00:00:00',
      },
    ],
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('DebugPanel', () => {
  it('shows summary stats and section counts', async () => {
    mockedGet.mockResolvedValue(makeSnapshot());
    render(
      <TestQueryWrapper>
        <DebugPanel projectId="proj_1" />
      </TestQueryWrapper>,
    );
    await waitFor(() => expect(screen.getByText('Debug Snapshot')).toBeInTheDocument());
    expect(screen.getByText('Nodes (1)')).toBeInTheDocument();
    expect(screen.getByText('Recent jobs (1)')).toBeInTheDocument();
    expect(screen.getByText('Recent events (1)')).toBeInTheDocument();
    // Job error_message renders as the dash for null.
    expect(screen.getByText('v2.generate_comparch')).toBeInTheDocument();
  });

  it('Copy snapshot writes the JSON blob to the clipboard', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    mockedGet.mockResolvedValue(makeSnapshot());
    render(
      <TestQueryWrapper>
        <DebugPanel projectId="proj_1" />
      </TestQueryWrapper>,
    );
    const copyButton = await screen.findByTestId('debug-copy-button');
    fireEvent.click(copyButton);
    await waitFor(() => expect(writeText).toHaveBeenCalled());
    const blob = writeText.mock.calls[0][0] as string;
    const parsed = JSON.parse(blob);
    expect(parsed.project.id).toBe('proj_1');
    expect(parsed.recent_events[0].event_type).toBe('NodeCreated');
  });

  it('shows total character count for the snapshot', async () => {
    mockedGet.mockResolvedValue(makeSnapshot());
    render(
      <TestQueryWrapper>
        <DebugPanel projectId="proj_1" />
      </TestQueryWrapper>,
    );
    const totalChars = await screen.findByTestId('debug-total-chars');
    expect(Number(totalChars.textContent?.replace(/,/g, ''))).toBeGreaterThan(0);
  });

  it('Copy section button copies just that section as JSON', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    mockedGet.mockResolvedValue(makeSnapshot());
    render(
      <TestQueryWrapper>
        <DebugPanel projectId="proj_1" />
      </TestQueryWrapper>,
    );
    const sectionCopy = await screen.findByTestId('debug-copy-recent_jobs');
    fireEvent.click(sectionCopy);
    await waitFor(() => expect(writeText).toHaveBeenCalled());
    const payload = writeText.mock.calls[0][0] as string;
    const parsed = JSON.parse(payload);
    expect(Object.keys(parsed)).toEqual(['recent_jobs']);
    expect(parsed.recent_jobs[0].job_type).toBe('v2.generate_comparch');
    expect(parsed.project).toBeUndefined();
  });

  it('exposes per-chunk copy buttons when a section exceeds the chunk size', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    const snap = makeSnapshot();
    snap.nodes = makeNodes(40, 400);
    mockedGet.mockResolvedValue(snap);
    render(
      <TestQueryWrapper>
        <DebugPanel projectId="proj_1" />
      </TestQueryWrapper>,
    );
    // Shrink chunk size so we definitely split into multiple parts.
    const chunkInput = (await screen.findByTestId(
      'debug-chunk-size-input',
    )) as HTMLInputElement;
    fireEvent.change(chunkInput, { target: { value: '5000' } });

    const firstChunk = await screen.findByTestId('debug-copy-nodes-chunk-1');
    const secondChunk = await screen.findByTestId('debug-copy-nodes-chunk-2');
    fireEvent.click(firstChunk);
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    const firstPayload = JSON.parse(writeText.mock.calls[0][0] as string);
    expect(firstPayload._chunk.index).toBe(1);
    expect(firstPayload._chunk.total).toBeGreaterThan(1);
    expect(firstPayload.nodes.length).toBe(firstPayload._chunk.rows_in_chunk);
    expect((writeText.mock.calls[0][0] as string).length).toBeLessThanOrEqual(6000);

    fireEvent.click(secondChunk);
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(2));
    const secondPayload = JSON.parse(writeText.mock.calls[1][0] as string);
    expect(secondPayload._chunk.index).toBe(2);
  });

  it('does not show chunk buttons for a section that fits in one chunk', async () => {
    mockedGet.mockResolvedValue(makeSnapshot());
    render(
      <TestQueryWrapper>
        <DebugPanel projectId="proj_1" />
      </TestQueryWrapper>,
    );
    await screen.findByTestId('debug-copy-recent_jobs');
    expect(screen.queryByTestId('debug-copy-recent_jobs-chunk-1')).toBeNull();
  });

  it('renders an error state when the request fails', async () => {
    mockedGet.mockRejectedValue(new Error('boom'));
    render(
      <TestQueryWrapper>
        <DebugPanel projectId="proj_1" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByText(/Failed to load snapshot/)).toBeInTheDocument(),
    );
  });
});
