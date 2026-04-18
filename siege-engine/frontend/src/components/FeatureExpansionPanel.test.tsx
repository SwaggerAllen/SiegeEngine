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
  cancelGeneration: vi.fn(),
  retryReview: vi.fn(),
}));

import * as expansionApi from '../api/expansion';

const mockedGet = expansionApi.getExpansion as unknown as ReturnType<typeof vi.fn>;
const mockedPostFeedback = expansionApi.postFeedback as unknown as ReturnType<
  typeof vi.fn
>;
const mockedApprove = expansionApi.approveDraft as unknown as ReturnType<typeof vi.fn>;
const mockedRetryReview = expansionApi.retryReview as unknown as ReturnType<
  typeof vi.fn
>;

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
    latest_telemetry: null,
    generation_started_at: null,
    current_attempt: null,
    max_attempts: null,
    failed_raw_output: null,
    review_text: '',
    review_status: 'idle',
    review_last_error: null,
    review_current_attempt: null,
    review_max_attempts: null,
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

  it('renders the pending draft with approve and reject-regenerate actions', async () => {
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
    expect(
      screen.getByRole('button', { name: 'Reject & Regenerate' })
    ).toBeInTheDocument();
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

  it('invokes feedback (empty) when Reject & Regenerate is clicked without feedback', async () => {
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
    const btn = await screen.findByRole('button', {
      name: 'Reject & Regenerate',
    });
    fireEvent.click(btn);

    await waitFor(() =>
      expect(mockedPostFeedback).toHaveBeenCalledWith('proj_1', '')
    );
  });

  it('sends typed feedback when Reject & Regenerate is clicked with feedback text', async () => {
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
    fireEvent.click(screen.getByRole('button', { name: 'Reject & Regenerate' }));

    await waitFor(() =>
      expect(mockedPostFeedback).toHaveBeenCalledWith('proj_1', 'Add reporting')
    );
  });

  it('renders the telemetry line when latest_telemetry is present', async () => {
    mockedGet.mockResolvedValue(
      makeResponse({
        node: {
          id: 'expn_1',
          name: 'Feature Expansion',
          content: '# Approved plan',
          updated_at: '2026-04-12T00:00:00',
        },
        latest_telemetry: {
          prompt_tokens: 1234,
          completion_tokens: 567,
          model: 'claude-sonnet-4-6',
          created_at: '2026-04-12T00:00:00',
        },
      })
    );
    renderPanel();

    const line = await screen.findByTestId('telemetry-line');
    expect(line).toHaveTextContent(/Last gen:/);
    expect(line).toHaveTextContent(/1,234/);
    expect(line).toHaveTextContent(/567 tokens/);
    expect(line).toHaveTextContent(/claude-sonnet-4-6/);
  });

  it('does not render the telemetry line when latest_telemetry is null', async () => {
    mockedGet.mockResolvedValue(
      makeResponse({
        node: {
          id: 'expn_1',
          name: 'Feature Expansion',
          content: '# Approved plan',
          updated_at: '2026-04-12T00:00:00',
        },
        latest_telemetry: null,
      })
    );
    renderPanel();

    await waitFor(() => expect(screen.getByText(/Approved plan/)).toBeInTheDocument());
    expect(screen.queryByTestId('telemetry-line')).toBeNull();
  });

  it('renders approved content as read-only with no revision button', async () => {
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
    expect(screen.getByText(/Approved · read-only/i)).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /Request revision/i })
    ).toBeNull();
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

  // Phase 8 — AI self-review block render states.
  describe('AI review block', () => {
    it('renders the review markdown when present on a pending draft', async () => {
      mockedGet.mockResolvedValue(
        makeResponse({
          pending_draft: {
            id: 'draft_1',
            content: 'content',
            created_at: '2026-04-12T00:00:00',
          },
          review_text:
            '## Handles & structure\nHandles read cleanly.\n\n## Architectural decisions\nNo tech decisions at this tier.',
        })
      );
      renderPanel();

      const reviewBlock = await screen.findByTestId('review-text');
      expect(reviewBlock).toBeInTheDocument();
      expect(reviewBlock).toHaveTextContent(/AI Review/i);
    });

    it('renders the in-flight spinner + attempt counter when review_status=running', async () => {
      mockedGet.mockResolvedValue(
        makeResponse({
          pending_draft: {
            id: 'draft_1',
            content: 'content',
            created_at: '2026-04-12T00:00:00',
          },
          review_status: 'running',
          review_current_attempt: 2,
          review_max_attempts: 3,
        })
      );
      renderPanel();

      const running = await screen.findByTestId('review-running');
      expect(running).toHaveTextContent(/Reviewing/);
      expect(running).toHaveTextContent(/attempt 2 \/ 3/);
    });

    it('renders the failed banner + retry button when review_status=failed', async () => {
      mockedGet.mockResolvedValue(
        makeResponse({
          pending_draft: {
            id: 'draft_1',
            content: 'content',
            created_at: '2026-04-12T00:00:00',
          },
          review_status: 'failed',
          review_last_error: 'review CLI timed out',
        })
      );
      mockedRetryReview.mockResolvedValue({ job_id: 'job_review_retry' });
      renderPanel();

      const failed = await screen.findByTestId('review-failed');
      expect(failed).toHaveTextContent(/AI review failed/);
      expect(failed).toHaveTextContent(/review CLI timed out/);

      fireEvent.click(screen.getByTestId('review-retry-button'));
      await waitFor(() =>
        expect(mockedRetryReview).toHaveBeenCalledWith('proj_1')
      );
    });

    it('renders the Generate review button on reviewable content with no review yet', async () => {
      mockedGet.mockResolvedValue(
        makeResponse({
          pending_draft: {
            id: 'draft_1',
            content: 'content',
            created_at: '2026-04-12T00:00:00',
          },
        })
      );
      mockedRetryReview.mockResolvedValue({ job_id: 'job_review_new' });
      renderPanel();

      await waitFor(() =>
        expect(screen.getByRole('button', { name: /Approve/i })).toBeInTheDocument()
      );
      expect(screen.queryByTestId('review-text')).toBeNull();
      expect(screen.queryByTestId('review-running')).toBeNull();
      expect(screen.queryByTestId('review-failed')).toBeNull();

      const generate = screen.getByTestId('review-generate-button');
      fireEvent.click(generate);
      await waitFor(() =>
        expect(mockedRetryReview).toHaveBeenCalledWith('proj_1')
      );
    });

    it('offers Generate review on grandfathered approved content', async () => {
      mockedGet.mockResolvedValue(
        makeResponse({
          node: {
            id: 'expn_1',
            name: 'Feature Expansion',
            content: '# Approved plan from before Phase 8',
            updated_at: '2025-12-01T00:00:00',
          },
        })
      );
      mockedRetryReview.mockResolvedValue({ job_id: 'job_review_grand' });
      renderPanel();

      await waitFor(() =>
        expect(screen.getByText(/Approved plan from before Phase 8/)).toBeInTheDocument()
      );
      const generate = screen.getByTestId('review-generate-button');
      fireEvent.click(generate);
      await waitFor(() =>
        expect(mockedRetryReview).toHaveBeenCalledWith('proj_1')
      );
    });

    it('renders the review markdown alongside approved content', async () => {
      mockedGet.mockResolvedValue(
        makeResponse({
          node: {
            id: 'expn_1',
            name: 'Feature Expansion',
            content: '# Approved plan',
            updated_at: '2026-04-12T00:00:00',
          },
          review_text:
            '## Handles & structure\nReview landed after approval — still visible.',
        })
      );
      renderPanel();

      await waitFor(() =>
        expect(screen.getByText(/Approved plan/)).toBeInTheDocument()
      );
      const reviewBlock = screen.getByTestId('review-text');
      expect(reviewBlock).toHaveTextContent(/AI Review/);
    });
  });
});
