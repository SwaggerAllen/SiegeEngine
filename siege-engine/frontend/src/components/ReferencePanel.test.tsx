import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReferenceDetail } from '../api/references';
import { TestQueryWrapper } from '../test/queryWrapper';
import { ReferencePanel } from './ReferencePanel';

vi.mock('../api/references', async () => {
  const actual = await vi.importActual<typeof import('../api/references')>(
    '../api/references',
  );
  return {
    ...actual,
    getReference: vi.fn(),
    updateReference: vi.fn(),
    approveReferenceDraft: vi.fn(),
    discardReferenceDraft: vi.fn(),
    deleteReference: vi.fn(),
    removeReferenceEdge: vi.fn(),
  };
});

import * as refsApi from '../api/references';

const mockedGet = refsApi.getReference as unknown as ReturnType<typeof vi.fn>;
const mockedUpdate = refsApi.updateReference as unknown as ReturnType<typeof vi.fn>;
const mockedApprove = refsApi.approveReferenceDraft as unknown as ReturnType<typeof vi.fn>;
const mockedRemoveEdge = refsApi.removeReferenceEdge as unknown as ReturnType<typeof vi.fn>;

function renderPanel(refId: string | null = 'ref_AAAAAAAA') {
  return render(
    <TestQueryWrapper>
      <ReferencePanel projectId="proj_1" refId={refId} />
    </TestQueryWrapper>,
  );
}

function detail(overrides: Partial<ReferenceDetail> = {}): ReferenceDetail {
  return {
    id: 'ref_AAAAAAAA',
    name: 'Runbook',
    content: '',
    updated_at: '2026-04-16T00:00:00',
    pending_draft: null,
    generation_status: 'idle',
    last_error: null,
    latest_telemetry: null,
    generation_started_at: null,
    outgoing_edges: [],
    incoming_edges: [],
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('ReferencePanel', () => {
  it('shows an empty placeholder when no ref is selected', () => {
    renderPanel(null);
    expect(screen.getByText(/Select a reference/i)).toBeInTheDocument();
  });

  it('shows a pending draft with approve and discard buttons', async () => {
    mockedGet.mockResolvedValue(
      detail({
        pending_draft: {
          id: 'draft_1',
          content:
            '<reference><title>Draft Title</title><body>Draft body.</body></reference>',
          created_at: '2026-04-16T00:00:00',
        },
      }),
    );
    renderPanel();
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: /Approve/i }),
      ).toBeInTheDocument(),
    );
    expect(screen.getByRole('button', { name: /Discard/i })).toBeInTheDocument();
    expect(screen.getByText(/Draft Title/)).toBeInTheDocument();
  });

  it('approves a pending draft when Approve is clicked', async () => {
    mockedGet.mockResolvedValue(
      detail({
        pending_draft: {
          id: 'draft_1',
          content: '<reference><title>T</title><body>B</body></reference>',
          created_at: '2026-04-16T00:00:00',
        },
      }),
    );
    mockedApprove.mockResolvedValue(undefined);
    renderPanel();
    const approveBtn = await screen.findByRole('button', { name: /Approve/i });
    await userEvent.click(approveBtn);
    await waitFor(() =>
      expect(mockedApprove).toHaveBeenCalledWith('proj_1', 'ref_AAAAAAAA', 'draft_1'),
    );
  });

  it('allows feedback submission even when content is already approved', async () => {
    mockedGet.mockResolvedValue(
      detail({
        content: '<reference><title>Approved</title><body>Body.</body></reference>',
      }),
    );
    mockedUpdate.mockResolvedValue({ job_id: 'job_1' });
    renderPanel();
    const updateBtn = await screen.findByRole('button', { name: /Update/i });
    await userEvent.click(updateBtn);
    await waitFor(() =>
      expect(mockedUpdate).toHaveBeenCalledWith('proj_1', 'ref_AAAAAAAA', null),
    );
  });

  it('lists outgoing reference edges and supports removing them', async () => {
    mockedGet.mockResolvedValue(
      detail({
        outgoing_edges: [
          {
            edge_id: 'edge_1',
            source_id: 'ref_AAAAAAAA',
            target_id: 'comp_BILLING1',
          },
        ],
      }),
    );
    mockedRemoveEdge.mockResolvedValue(undefined);
    renderPanel();
    await waitFor(() =>
      expect(screen.getByText(/comp_BILLING1/)).toBeInTheDocument(),
    );
    const removeBtn = screen.getByRole('button', { name: /Remove/i });
    await userEvent.click(removeBtn);
    await waitFor(() =>
      expect(mockedRemoveEdge).toHaveBeenCalledWith(
        'proj_1',
        'ref_AAAAAAAA',
        'comp_BILLING1',
      ),
    );
  });
});
