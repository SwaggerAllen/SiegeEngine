import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReferenceDetail } from '../api/references';
import { TestQueryWrapper } from '../test/queryWrapper';
import { ReferencePanel } from './ReferencePanel';

const apiStub: {
  list: ReturnType<typeof vi.fn>;
  getDetail: ReturnType<typeof vi.fn>;
  create: ReturnType<typeof vi.fn>;
  delete: ReturnType<typeof vi.fn>;
  addEdge: ReturnType<typeof vi.fn>;
  removeEdge: ReturnType<typeof vi.fn>;
  getState: ReturnType<typeof vi.fn>;
  postFeedback: ReturnType<typeof vi.fn>;
  approveDraft: ReturnType<typeof vi.fn>;
  discardDraft: ReturnType<typeof vi.fn>;
  cancelGeneration: ReturnType<typeof vi.fn>;
  resetTier: ReturnType<typeof vi.fn>;
  getPromptPreview: ReturnType<typeof vi.fn>;
} = {
  list: vi.fn(),
  getDetail: vi.fn(),
  create: vi.fn(),
  delete: vi.fn(),
  addEdge: vi.fn(),
  removeEdge: vi.fn(),
  getState: vi.fn(),
  postFeedback: vi.fn(),
  approveDraft: vi.fn(),
  discardDraft: vi.fn(),
  cancelGeneration: vi.fn(),
  resetTier: vi.fn(),
  getPromptPreview: vi.fn(),
};

vi.mock('../api/references', async () => {
  const actual = await vi.importActual<typeof import('../api/references')>(
    '../api/references',
  );
  return {
    ...actual,
    makeReferencesApi: vi.fn(() => apiStub),
  };
});

function renderPanel(refId: string | null = 'ref_AAAAAAAA') {
  return render(
    <TestQueryWrapper>
      <ReferencePanel projectId="proj_1" refId={refId} />
    </TestQueryWrapper>,
  );
}

function detail(overrides: Partial<ReferenceDetail> = {}): ReferenceDetail {
  return {
    node: {
      id: 'ref_AAAAAAAA',
      name: 'Runbook',
      content: '',
      updated_at: '2026-04-16T00:00:00',
    },
    pending_draft: null,
    generation_status: 'idle',
    last_error: null,
    latest_telemetry: null,
    generation_started_at: null,
    current_attempt: null,
    max_attempts: null,
    failed_raw_output: null,
    review_text: '',
    review_status: 'idle',
    review_last_error: null,
    review_started_at: null,
    review_current_attempt: null,
    review_max_attempts: null,
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
    apiStub.getDetail.mockResolvedValue(
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
    apiStub.getDetail.mockResolvedValue(
      detail({
        pending_draft: {
          id: 'draft_1',
          content: '<reference><title>T</title><body>B</body></reference>',
          created_at: '2026-04-16T00:00:00',
        },
      }),
    );
    apiStub.approveDraft.mockResolvedValue(undefined);
    renderPanel();
    const approveBtn = await screen.findByRole('button', { name: /Approve/i });
    await userEvent.click(approveBtn);
    await waitFor(() =>
      expect(apiStub.approveDraft).toHaveBeenCalledWith('ref_AAAAAAAA', 'draft_1'),
    );
  });

  it('allows feedback submission even when content is already approved', async () => {
    apiStub.getDetail.mockResolvedValue(
      detail({
        node: {
          id: 'ref_AAAAAAAA',
          name: 'Runbook',
          content:
            '<reference><title>Approved</title><body>Body.</body></reference>',
          updated_at: '2026-04-16T00:00:00',
        },
      }),
    );
    apiStub.postFeedback.mockResolvedValue({ job_id: 'job_1' });
    renderPanel();
    const updateBtn = await screen.findByRole('button', { name: /Update/i });
    await userEvent.click(updateBtn);
    await waitFor(() =>
      expect(apiStub.postFeedback).toHaveBeenCalledWith('ref_AAAAAAAA', ''),
    );
  });

  it('lists outgoing reference edges and supports removing them', async () => {
    apiStub.getDetail.mockResolvedValue(
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
    apiStub.removeEdge.mockResolvedValue(undefined);
    renderPanel();
    await waitFor(() =>
      expect(screen.getByText(/comp_BILLING1/)).toBeInTheDocument(),
    );
    const removeBtn = screen.getByRole('button', { name: /Remove/i });
    await userEvent.click(removeBtn);
    await waitFor(() =>
      expect(apiStub.removeEdge).toHaveBeenCalledWith(
        'ref_AAAAAAAA',
        'comp_BILLING1',
      ),
    );
  });
});
