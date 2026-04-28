import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api/jobs', async (orig) => {
  const actual = await orig<typeof import('../api/jobs')>();
  return {
    ...actual,
    listJobs: vi.fn(),
    cancelJob: vi.fn(),
    deleteJob: vi.fn(),
    reprioritizeJob: vi.fn(),
  };
});

const mockedStructure = vi.fn();
vi.mock('../hooks/queries/useProjectStructure', () => ({
  useProjectStructure: () => mockedStructure(),
}));

import * as jobsApi from '../api/jobs';
import { GenerationQueuePanel } from './GenerationQueuePanel';

const mockedListJobs = jobsApi.listJobs as unknown as ReturnType<typeof vi.fn>;

function renderPanel() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <GenerationQueuePanel projectId="proj_1" />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockedListJobs.mockReset();
  mockedStructure.mockReset();
});

describe('GenerationQueuePanel scope rendering', () => {
  it('shows display names for payload IDs that resolve to structure nodes', async () => {
    mockedStructure.mockReturnValue({
      data: {
        offset: 1,
        nodes: [
          { id: 'comp_TOP00001', name: 'Billing' },
          { id: 'comp_SUB00007', name: 'TokenStore' },
        ],
        edges: [],
      },
    });
    mockedListJobs.mockResolvedValue({
      jobs: [
        {
          id: 'job_1',
          job_type: 'v2.generate_subcomparch',
          status: 'queued',
          priority: 50,
          retry_count: 0,
          max_retries: 3,
          error_message: null,
          payload: { component_id: 'comp_TOP00001', sub_id: 'comp_SUB00007' },
          created_at: '2026-04-26T12:00:00',
        },
      ],
      status_counts: { queued: 1 },
      total_returned: 1,
    });
    renderPanel();
    await waitFor(() =>
      expect(screen.getByText(/component_id=Billing/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/sub_id=TokenStore/)).toBeInTheDocument();
    // Raw IDs no longer surfaced when names resolve.
    expect(screen.queryByText(/comp_TOP00001/)).toBeNull();
    expect(screen.queryByText(/comp_SUB00007/)).toBeNull();
  });

  it('falls back to the raw ID when no structure node matches', async () => {
    mockedStructure.mockReturnValue({
      data: { offset: 1, nodes: [], edges: [] },
    });
    mockedListJobs.mockResolvedValue({
      jobs: [
        {
          id: 'job_2',
          job_type: 'v2.generate_reference',
          status: 'queued',
          priority: 50,
          retry_count: 0,
          max_retries: 3,
          error_message: null,
          // ref_id has no structure-node home; should render as-is.
          payload: { ref_id: 'ref_xxxx' },
          created_at: '2026-04-26T12:00:00',
        },
      ],
      status_counts: { queued: 1 },
      total_returned: 1,
    });
    renderPanel();
    await waitFor(() =>
      expect(screen.getByText(/ref_id=ref_xxxx/)).toBeInTheDocument(),
    );
  });
});
