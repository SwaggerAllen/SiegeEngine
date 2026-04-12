import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { TestQueryWrapper } from '../test/queryWrapper';
import { FeatureExpansionPanel } from './FeatureExpansionPanel';
import type { ExpansionResponse } from '../api/expansion';

// Mock the API module so we can drive component state from tests.
vi.mock('../api/expansion', () => ({
  getExpansion: vi.fn(),
  postFeedback: vi.fn(),
  approveDraft: vi.fn(),
  discardDraft: vi.fn(),
}));

import * as expansionApi from '../api/expansion';

const mockedGet = expansionApi.getExpansion as unknown as ReturnType<typeof vi.fn>;
const mockedPostFeedback = expansionApi.postFeedback as unknown as ReturnType<
  typeof vi.fn
>;
const mockedApprove = expansionApi.approveDraft as unknown as ReturnType<typeof vi.fn>;
const mockedDiscard = expansionApi.discardDraft as unknown as ReturnType<typeof vi.fn>;

function renderPanel() {
  return render(
    <TestQueryWrapper>
      <FeatureExpansionPanel projectId="proj_1" />
    </TestQueryWrapper>
  );
}

function makeResponse(overrides: Partial<ExpansionResponse> = {}): ExpansionResponse {
  return {
    node: {
      id: 'expn_1',
      name: 'Feature Expansion',
      content: '',
      updated_at: '2026-04-12T00:00:00',
    },
    pending_draft: null,
    generation_status: 'idle',
    last_error: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('FeatureExpansionPanel', () => {
  it('shows a spinner while generating with no pending draft', async () => {
    mockedGet.mockResolvedValue(makeResponse({ generation_status: 'running' }));
    renderPanel();
    await waitFor(() =>
      expect(screen.getByText(/Generating feature expansion/i)).toBeInTheDocument()
    );
  });

  it('renders the pending draft with approve/discard/regenerate actions', async () => {
    mockedGet.mockResolvedValue(
      makeResponse({
        pending_draft: {
          id: 'draft_1',
          content: '# Hello\n\nSome plan.',
          created_at: '2026-04-12T00:00:00',
        },
      })
    );
    renderPanel();

    await waitFor(() => expect(screen.getByText(/Hello/)).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /Approve/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Discard/i })).toBeInTheDocument();
    // Regenerate is disabled until feedback is non-empty
    expect(screen.getByRole('button', { name: /Regenerate/i })).toBeDisabled();
  });

  it('invokes approveDraft when Approve is clicked', async () => {
    mockedGet.mockResolvedValue(
      makeResponse({
        pending_draft: {
          id: 'draft_1',
          content: 'content',
          created_at: '2026-04-12T00:00:00',
        },
      })
    );
    mockedApprove.mockResolvedValue({
      id: 'expn_1',
      name: 'Feature Expansion',
      content: 'content',
      updated_at: '2026-04-12T00:00:00',
    });

    renderPanel();
    const btn = await screen.findByRole('button', { name: /Approve/i });
    fireEvent.click(btn);

    await waitFor(() =>
      expect(mockedApprove).toHaveBeenCalledWith('proj_1', 'draft_1')
    );
  });

  it('invokes discardDraft when Discard is clicked', async () => {
    mockedGet.mockResolvedValue(
      makeResponse({
        pending_draft: {
          id: 'draft_1',
          content: 'content',
          created_at: '2026-04-12T00:00:00',
        },
      })
    );
    mockedDiscard.mockResolvedValue(undefined);

    renderPanel();
    const btn = await screen.findByRole('button', { name: /Discard/i });
    fireEvent.click(btn);

    await waitFor(() =>
      expect(mockedDiscard).toHaveBeenCalledWith('proj_1', 'draft_1')
    );
  });

  it('sends feedback to postFeedback when Regenerate is clicked', async () => {
    mockedGet.mockResolvedValue(
      makeResponse({
        pending_draft: {
          id: 'draft_1',
          content: 'content',
          created_at: '2026-04-12T00:00:00',
        },
      })
    );
    mockedPostFeedback.mockResolvedValue({ job_id: 'job_1' });

    renderPanel();
    const textarea = await screen.findByPlaceholderText(/Add reporting/i);
    fireEvent.change(textarea, { target: { value: 'Add reporting' } });
    fireEvent.click(screen.getByRole('button', { name: /Regenerate/i }));

    await waitFor(() =>
      expect(mockedPostFeedback).toHaveBeenCalledWith('proj_1', 'Add reporting')
    );
  });

  it('renders approved content as read-only with no revision button', async () => {
    // v2 spec: bootstrap nodes become read-only after their initial
    // approval. Ongoing feature-layer work happens on individual
    // feature nodes (Phase 2), not by re-editing the expansion prose.
    mockedGet.mockResolvedValue(
      makeResponse({
        node: {
          id: 'expn_1',
          name: 'Feature Expansion',
          content: '# Approved plan',
          updated_at: '2026-04-12T00:00:00',
        },
      })
    );
    renderPanel();

    await waitFor(() => expect(screen.getByText(/Approved plan/)).toBeInTheDocument());
    // Read-only marker visible.
    expect(screen.getByText(/Approved · read-only/i)).toBeInTheDocument();
    // No "Request revision" button exists anywhere in the document.
    expect(
      screen.queryByRole('button', { name: /Request revision/i })
    ).toBeNull();
    // No "Submit feedback" button either (old inline revision form
    // is also gone).
    expect(
      screen.queryByRole('button', { name: /Submit feedback/i })
    ).toBeNull();
  });

  it('shows an error banner with Retry when generation failed and no content', async () => {
    mockedGet.mockResolvedValue(
      makeResponse({
        generation_status: 'failed',
        last_error: 'timeout after 180s',
      })
    );
    mockedPostFeedback.mockResolvedValue({ job_id: 'job_retry' });
    renderPanel();

    await waitFor(() =>
      expect(screen.getByText(/Generation failed/i)).toBeInTheDocument()
    );
    expect(screen.getByText(/timeout after 180s/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Retry/i }));
    await waitFor(() =>
      expect(mockedPostFeedback).toHaveBeenCalledWith('proj_1', '')
    );
  });
});
