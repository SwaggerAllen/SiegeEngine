import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { TestQueryWrapper } from '../test/queryWrapper';
import { RequirementsPanel } from './RequirementsPanel';
import type { ReqsResponse } from '../api/requirements';

// Mock the API module so we can drive component state from tests.
vi.mock('../api/requirements', () => ({
  getRequirements: vi.fn(),
  postFeedback: vi.fn(),
  approveDraft: vi.fn(),
  cancelGeneration: vi.fn(),
  getResponsibilities: vi.fn(),
}));

import * as reqsApi from '../api/requirements';

const mockedGet = reqsApi.getRequirements as unknown as ReturnType<typeof vi.fn>;

function renderPanel() {
  return render(
    <TestQueryWrapper>
      <RequirementsPanel projectId="proj_1" />
    </TestQueryWrapper>
  );
}

function makeResponse(overrides: Partial<ReqsResponse> = {}): ReqsResponse {
  return {
    node: {
      id: 'reqs_1',
      name: 'Requirements',
      content: '',
      updated_at: '2026-04-13T00:00:00',
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

describe('RequirementsPanel', () => {
  it('shows a spinner while generating with no pending draft', async () => {
    mockedGet.mockResolvedValue(makeResponse({ generation_status: 'running' }));
    renderPanel();
    await waitFor(() =>
      expect(screen.getByText(/Generating requirements/i)).toBeInTheDocument()
    );
  });

  // TODO Phase 3 reinstate test once dashboard is read-only:
  //   - renders pending draft with approve/discard/regenerate actions
  //   - invokes approveDraft when Approve is clicked
  //   - invokes feedback (empty) when Reject & Regenerate is clicked without feedback
  //   - sends feedback to postFeedback when Reject & Regenerate is clicked with feedback
  it('renders the pending draft body with the Open-in-CC fallback', async () => {
    mockedGet.mockResolvedValue(
      makeResponse({
        pending_draft: {
          id: 'draft_1',
          content:
            '<requirements><responsibility><name>identify users</name><feats/></responsibility></requirements>',
          created_at: '2026-04-13T00:00:00',
        },
      })
    );
    renderPanel();
    await waitFor(() => expect(screen.getByText('identify users')).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /Approve/i })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Reject & Regenerate' })).toBeNull();
    expect(
      screen.getAllByRole('button', { name: /Open in Claude Code/i }).length,
    ).toBeGreaterThan(0);
  });

  it('renders approved content as read-only', async () => {
    mockedGet.mockResolvedValue(
      makeResponse({
        node: {
          id: 'reqs_1',
          name: 'Requirements',
          content:
            '<requirements><responsibility><name>final scope</name><feats/></responsibility></requirements>',
          updated_at: '2026-04-13T00:00:00',
        },
      })
    );
    renderPanel();

    await waitFor(() => expect(screen.getByText('final scope')).toBeInTheDocument());
    expect(screen.getByText(/Approved · read-only/i)).toBeInTheDocument();
  });

  it('shows an error banner with Open-in-CC when generation failed and no content', async () => {
    mockedGet.mockResolvedValue(
      makeResponse({
        generation_status: 'failed',
        last_error: 'timeout after 900s',
      })
    );
    renderPanel();

    await waitFor(() =>
      expect(screen.getByText(/Generation failed/i)).toBeInTheDocument()
    );
    expect(screen.getByText(/timeout after 900s/)).toBeInTheDocument();
    // TODO Phase 3 reinstate test once dashboard is read-only:
    // Retry is gone, the fallback is the Open-in-Claude-Code button.
    expect(screen.queryByRole('button', { name: /^Retry$/i })).toBeNull();
    expect(
      screen.getAllByRole('button', { name: /Open in Claude Code/i }).length,
    ).toBeGreaterThan(0);
  });
});
