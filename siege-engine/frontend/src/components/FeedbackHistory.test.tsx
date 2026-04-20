import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { FeedbackHistoryResponse } from '../api/feedbackHistory';
import { TestQueryWrapper } from '../test/queryWrapper';
import { FeedbackHistory } from './FeedbackHistory';

vi.mock('../api/feedbackHistory', async () => {
  const actual =
    await vi.importActual<typeof import('../api/feedbackHistory')>(
      '../api/feedbackHistory',
    );
  return { ...actual, getFeedbackHistory: vi.fn() };
});

import * as api from '../api/feedbackHistory';

const mocked = api.getFeedbackHistory as unknown as ReturnType<typeof vi.fn>;

function response(entries: FeedbackHistoryResponse['entries']): FeedbackHistoryResponse {
  return { entries };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('FeedbackHistory', () => {
  it('renders nothing when nodeId is missing', () => {
    const { container } = render(
      <TestQueryWrapper>
        <FeedbackHistory projectId="p1" nodeId={null} />
      </TestQueryWrapper>,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing once an empty history resolves', async () => {
    mocked.mockResolvedValue(response([]));
    render(
      <TestQueryWrapper>
        <FeedbackHistory projectId="p1" nodeId="expansion_A" />
      </TestQueryWrapper>,
    );
    // Empty response collapses the whole section — the <summary>
    // never appears.
    await waitFor(() =>
      expect(screen.queryByText(/Feedback history/)).not.toBeInTheDocument(),
    );
  });

  it('shows entries with source labels + a Copy all button', async () => {
    mocked.mockResolvedValue(
      response([
        {
          created_at: '2026-04-20T12:00:00',
          source: 'user',
          text: 'Please sharpen onboarding.',
        },
        {
          created_at: '2026-04-20T12:05:00',
          source: 'ai_review',
          text: 'Intent reads generic.',
        },
      ]),
    );
    render(
      <TestQueryWrapper>
        <FeedbackHistory projectId="p1" nodeId="expansion_A" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByText('Please sharpen onboarding.')).toBeInTheDocument(),
    );
    expect(screen.getByText('Intent reads generic.')).toBeInTheDocument();
    expect(screen.getByText(/User feedback/)).toBeInTheDocument();
    expect(screen.getByText(/AI review/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Copy all/ })).toBeInTheDocument();
  });

  it('writes the combined history to the clipboard on Copy all', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    mocked.mockResolvedValue(
      response([
        {
          created_at: '2026-04-20T12:00:00',
          source: 'user',
          text: 'User note.',
        },
        {
          created_at: '2026-04-20T12:01:00',
          source: 'ai_review',
          text: 'AI note.',
        },
      ]),
    );
    render(
      <TestQueryWrapper>
        <FeedbackHistory projectId="p1" nodeId="expansion_A" />
      </TestQueryWrapper>,
    );
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Copy all/ })).toBeInTheDocument(),
    );
    await userEvent.click(screen.getByRole('button', { name: /Copy all/ }));

    expect(writeText).toHaveBeenCalledTimes(1);
    const copied = writeText.mock.calls[0][0] as string;
    expect(copied).toContain('User feedback');
    expect(copied).toContain('User note.');
    expect(copied).toContain('AI review');
    expect(copied).toContain('AI note.');
  });
});
