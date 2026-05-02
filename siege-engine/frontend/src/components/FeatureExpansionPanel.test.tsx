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
    previous_draft_content: null,
    auto_revision_intermediates: [],
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
    last_generation_job: null,
    last_content_updated_at: null,
    is_stale: false,
    staleness_reasons: [],
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
    // Review content lives behind the "Review" subtab — click it
    // before asserting on review-state testids.
    async function openReviewTab() {
      const reviewTab = await screen.findByTestId('review-tab');
      fireEvent.click(reviewTab);
    }

    const STRUCTURED_REVIEW = (
      '<review>' +
      '<intro>Shape is roughly right but a couple of names collide.</intro>' +
      '<score>65</score>' +
      '<handles-structure>' +
      '<finding id="h1">Feature names overlap between "Dashboard" and "Reports".</finding>' +
      '<finding id="h2">Intent for X is a restated name.</finding>' +
      '</handles-structure>' +
      '<architectural-decisions>' +
      '<finding id="a1">Decomposition axis split across two concerns.</finding>' +
      '</architectural-decisions>' +
      '</review>'
    );

    it('Regenerate review button on the success-state calls the retry endpoint', async () => {
      mockedGet.mockResolvedValue(
        makeResponse({
          pending_draft: {
            id: 'draft_1',
            content: 'content',
            created_at: '2026-04-12T00:00:00',
          },
          review_text: STRUCTURED_REVIEW,
        })
      );
      mockedRetryReview.mockResolvedValue({ job_id: 'job_regen_review' });
      renderPanel();

      await openReviewTab();
      await screen.findByTestId('review-finding-h1');
      // The regenerate-review button is visible on the success
      // state (reviewText present + onRetryReview wired) so the
      // user doesn't have to wait for a failure to rerun it.
      const regen = screen.getByTestId('review-regenerate-button');
      fireEvent.click(regen);
      await waitFor(() =>
        expect(mockedRetryReview).toHaveBeenCalledWith('proj_1')
      );
    });

    it('renders structured findings with checkboxes for a parseable review', async () => {
      mockedGet.mockResolvedValue(
        makeResponse({
          pending_draft: {
            id: 'draft_1',
            content: 'content',
            created_at: '2026-04-12T00:00:00',
          },
          review_text: STRUCTURED_REVIEW,
        })
      );
      renderPanel();

      await openReviewTab();

      // All three findings render as checkboxes, checked by default.
      const h1 = await screen.findByTestId('review-finding-h1');
      const h2 = screen.getByTestId('review-finding-h2');
      const a1 = screen.getByTestId('review-finding-a1');
      expect(h1).toBeChecked();
      expect(h2).toBeChecked();
      expect(a1).toBeChecked();

      // Finding text rendered inline.
      expect(screen.getByText(/Feature names overlap/)).toBeInTheDocument();
    });

    it('falls back to markdown render for unparseable review text', async () => {
      mockedGet.mockResolvedValue(
        makeResponse({
          pending_draft: {
            id: 'draft_1',
            content: 'content',
            created_at: '2026-04-12T00:00:00',
          },
          // Pre-Phase-8 markdown review — no <review> wrapper.
          review_text: '## Handles & structure\nsome finding.',
        })
      );
      renderPanel();

      await openReviewTab();
      const legacy = await screen.findByTestId('review-text-legacy');
      expect(legacy).toHaveTextContent(/AI Review/);
    });

    it('Reject & Regenerate folds only checked findings into the feedback payload', async () => {
      mockedGet.mockResolvedValue(
        makeResponse({
          pending_draft: {
            id: 'draft_1',
            content: 'content',
            created_at: '2026-04-12T00:00:00',
          },
          review_text: STRUCTURED_REVIEW,
        })
      );
      mockedPostFeedback.mockResolvedValue({ job_id: 'job_apply' });
      renderPanel();

      await openReviewTab();

      // Uncheck h2 — we expect only h1 + a1 to feed forward.
      const h2 = await screen.findByTestId('review-finding-h2');
      fireEvent.click(h2);
      expect(h2).not.toBeChecked();

      fireEvent.click(
        screen.getByRole('button', { name: 'Reject & Regenerate' })
      );
      await waitFor(() => expect(mockedPostFeedback).toHaveBeenCalled());
      const [, feedback] = mockedPostFeedback.mock.calls[0];
      expect(feedback).toContain('Feature names overlap');
      expect(feedback).toContain('Decomposition axis split');
      expect(feedback).not.toContain('restated name');
    });

    it('Reject & Regenerate still runs when nothing is checked (empty AI part)', async () => {
      mockedGet.mockResolvedValue(
        makeResponse({
          pending_draft: {
            id: 'draft_1',
            content: 'content',
            created_at: '2026-04-12T00:00:00',
          },
          review_text: STRUCTURED_REVIEW,
        })
      );
      mockedPostFeedback.mockResolvedValue({ job_id: 'job_empty' });
      renderPanel();

      await openReviewTab();

      // Uncheck every finding via the toggle-all button.
      fireEvent.click(screen.getByTestId('review-toggle-all-button'));
      // All three finding checkboxes should now be unchecked.
      expect(screen.getByTestId('review-finding-h1')).not.toBeChecked();
      expect(screen.getByTestId('review-finding-h2')).not.toBeChecked();
      expect(screen.getByTestId('review-finding-a1')).not.toBeChecked();

      // The bottom-bar button is still enabled — "no findings
      // selected" is a valid regen state (equivalent to the
      // pre-Phase-11 empty Reject & Regenerate).
      const regen = screen.getByRole('button', { name: 'Reject & Regenerate' });
      expect(regen).not.toBeDisabled();

      fireEvent.click(regen);
      await waitFor(() => expect(mockedPostFeedback).toHaveBeenCalled());
      const [, feedback] = mockedPostFeedback.mock.calls[0];
      // With no findings + no textarea, the payload is empty.
      expect(feedback).toBe('');
    });

    it('toggle-all flips every checkbox in one click', async () => {
      mockedGet.mockResolvedValue(
        makeResponse({
          pending_draft: {
            id: 'draft_1',
            content: 'content',
            created_at: '2026-04-12T00:00:00',
          },
          review_text: STRUCTURED_REVIEW,
        })
      );
      renderPanel();

      await openReviewTab();

      // Start: all three selected → toggle-all deselects.
      expect(await screen.findByTestId('review-finding-h1')).toBeChecked();
      fireEvent.click(screen.getByTestId('review-toggle-all-button'));
      expect(screen.getByTestId('review-finding-h1')).not.toBeChecked();
      expect(screen.getByTestId('review-finding-a1')).not.toBeChecked();

      // Toggle-all again → reselect.
      fireEvent.click(screen.getByTestId('review-toggle-all-button'));
      expect(screen.getByTestId('review-finding-h1')).toBeChecked();
      expect(screen.getByTestId('review-finding-a1')).toBeChecked();
    });

    it('combines textarea feedback with checked findings under a "Selected AI-review findings:" divider', async () => {
      mockedGet.mockResolvedValue(
        makeResponse({
          pending_draft: {
            id: 'draft_1',
            content: 'content',
            created_at: '2026-04-12T00:00:00',
          },
          review_text: STRUCTURED_REVIEW,
        })
      );
      mockedPostFeedback.mockResolvedValue({ job_id: 'job_combined' });
      renderPanel();

      // Visit the Review tab so the default-all-checked selection
      // state pushes up to the panel, then return to the bottom.
      await openReviewTab();
      await screen.findByTestId('review-finding-h1');

      // Type some user feedback.
      const textarea = screen.getAllByRole('textbox')[0] as HTMLTextAreaElement;
      fireEvent.change(textarea, { target: { value: 'Also tighten auth' } });

      fireEvent.click(
        screen.getByRole('button', { name: 'Reject & Regenerate' })
      );
      await waitFor(() => expect(mockedPostFeedback).toHaveBeenCalled());
      const [, feedback] = mockedPostFeedback.mock.calls[0];
      expect(feedback).toContain('Also tighten auth');
      expect(feedback).toContain('Selected AI-review findings:');
      expect(feedback).toContain('Feature names overlap');
    });

    it('flags running review via a spinner on the tab and inside the panel', async () => {
      mockedGet.mockResolvedValue(
        makeResponse({
          pending_draft: {
            id: 'draft_1',
            content: 'content',
            created_at: '2026-04-12T00:00:00',
          },
          review_status: 'running',
          review_started_at: '2026-04-12T00:00:00',
          review_current_attempt: 2,
          review_max_attempts: 3,
        })
      );
      renderPanel();

      // Tab indicator visible without clicking Review.
      expect(await screen.findByTestId('review-tab-running')).toBeInTheDocument();

      await openReviewTab();
      const running = await screen.findByTestId('review-running');
      expect(running).toHaveTextContent(/Reviewing/);
      expect(running).toHaveTextContent(/attempt 2 \/ 3/);
    });

    it('flags failed review on the tab and renders retry button in the panel', async () => {
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

      expect(await screen.findByTestId('review-tab-failed')).toBeInTheDocument();

      await openReviewTab();
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
      // No running / failed indicator on the Review tab.
      expect(screen.queryByTestId('review-tab-running')).toBeNull();
      expect(screen.queryByTestId('review-tab-failed')).toBeNull();

      await openReviewTab();
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

      await openReviewTab();
      const generate = screen.getByTestId('review-generate-button');
      fireEvent.click(generate);
      await waitFor(() =>
        expect(mockedRetryReview).toHaveBeenCalledWith('proj_1')
      );
    });

    it('renders structured findings alongside approved content, but no Apply button', async () => {
      mockedGet.mockResolvedValue(
        makeResponse({
          node: {
            id: 'expn_1',
            name: 'Feature Expansion',
            content: '# Approved plan',
            updated_at: '2026-04-12T00:00:00',
          },
          review_text: STRUCTURED_REVIEW,
        })
      );
      renderPanel();

      await waitFor(() =>
        expect(screen.getByText(/Approved plan/)).toBeInTheDocument()
      );

      await openReviewTab();
      // Findings render. The "rides along with Reject & Regenerate"
      // hint is hidden on approved content because that branch has
      // no feedback regeneration path (no onSelectionChanged wiring).
      expect(await screen.findByTestId('review-finding-h1')).toBeInTheDocument();
      expect(
        screen.queryByText(/ride along when you Reject/i)
      ).toBeNull();
    });
  });
});
