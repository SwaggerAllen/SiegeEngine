import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TestQueryWrapper } from '../test/queryWrapper';
import { TierReviewSummaryPanel } from './TierReviewSummaryPanel';
import type { TierReviewSummary } from '../api/tierOps';

vi.mock('../api/tierOps', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/tierOps')>();
  return {
    ...actual,
    getTierReviewSummary: vi.fn(),
  };
});

import * as tierOpsApi from '../api/tierOps';

const mockedFetch = tierOpsApi.getTierReviewSummary as unknown as ReturnType<typeof vi.fn>;

function makeSummary(overrides: Partial<TierReviewSummary> = {}): TierReviewSummary {
  return {
    tier: 'comparch',
    tier_name: 'Comparch',
    draft_count: 3,
    reviewed_count: 3,
    missing_count: 0,
    score_stats: { min: 45, max: 92, mean: 69.67, median: 72 },
    score_buckets: { band_0_30: 0, band_31_60: 1, band_61_85: 1, band_86_100: 1 },
    handles_count_mean: 2.0,
    arch_count_mean: 1.0,
    reviews: [
      {
        scope_id: 'comp_a',
        scope_label: 'Auth',
        score: 45,
        intro: 'Auth is uneven.',
        handles_count: 4,
        arch_count: 2,
        approved_at: '2026-04-01T12:00:00',
      },
      {
        scope_id: 'comp_b',
        scope_label: 'Billing',
        score: 72,
        intro: 'Billing is OK.',
        handles_count: 2,
        arch_count: 1,
        approved_at: '2026-04-01T12:00:01',
      },
      {
        scope_id: 'comp_f',
        scope_label: 'Foundation',
        score: 92,
        intro: 'Foundation looks great.',
        handles_count: 0,
        arch_count: 0,
        approved_at: '2026-04-01T12:00:02',
      },
    ],
    missing: [],
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('TierReviewSummaryPanel', () => {
  it('renders header counts + histogram + stats', async () => {
    mockedFetch.mockResolvedValue(makeSummary());
    render(
      <TestQueryWrapper>
        <TierReviewSummaryPanel projectId="proj_1" tier="comparch" />
      </TestQueryWrapper>,
    );
    expect(await screen.findByText('Comparch')).toBeInTheDocument();
    expect(screen.getByText(/3 reviewed/)).toBeInTheDocument();
    expect(screen.getByTestId('tier-review-summary-histogram')).toBeInTheDocument();
    expect(screen.getByTestId('tier-review-summary-stats')).toHaveTextContent(/min 45/);
    expect(screen.getByTestId('tier-review-summary-stats')).toHaveTextContent(/max 92/);
  });

  it('default copy block holds the worst-N reviews score-ordered', async () => {
    mockedFetch.mockResolvedValue(makeSummary());
    render(
      <TestQueryWrapper>
        <TierReviewSummaryPanel projectId="proj_1" tier="comparch" />
      </TestQueryWrapper>,
    );
    const block = await screen.findByTestId('tier-review-summary-copy-block-comparch');
    // Worst-first ordering: Auth (45) first, Foundation (92) last.
    const text = block.textContent ?? '';
    const authIdx = text.indexOf('Auth — score 45');
    const billIdx = text.indexOf('Billing — score 72');
    const foundIdx = text.indexOf('Foundation — score 92');
    expect(authIdx).toBeGreaterThan(-1);
    expect(billIdx).toBeGreaterThan(authIdx);
    expect(foundIdx).toBeGreaterThan(billIdx);
    // Each section has the intro paragraph + findings counts.
    expect(text).toMatch(/Auth is uneven\./);
    expect(text).toMatch(/findings: 4 handles · 2 arch/);
  });

  it('threshold filter trims the copy block to score < threshold', async () => {
    mockedFetch.mockResolvedValue(makeSummary());
    render(
      <TestQueryWrapper>
        <TierReviewSummaryPanel projectId="proj_1" tier="comparch" />
      </TestQueryWrapper>,
    );
    const threshold = await screen.findByTestId('tier-review-summary-threshold');
    fireEvent.change(threshold, { target: { value: '70' } });
    await waitFor(() => {
      const block = screen.getByTestId('tier-review-summary-copy-block-comparch');
      const text = block.textContent ?? '';
      expect(text).toMatch(/Auth — score 45/);
      // Billing (72) and Foundation (92) are filtered out.
      expect(text).not.toMatch(/Billing — score 72/);
      expect(text).not.toMatch(/Foundation — score 92/);
    });
  });

  it('worst-N slider trims the copy block to the top-N worst', async () => {
    mockedFetch.mockResolvedValue(makeSummary());
    render(
      <TestQueryWrapper>
        <TierReviewSummaryPanel projectId="proj_1" tier="comparch" />
      </TestQueryWrapper>,
    );
    const slider = await screen.findByTestId('tier-review-summary-worst-n');
    fireEvent.change(slider, { target: { value: '1' } });
    await waitFor(() => {
      const block = screen.getByTestId('tier-review-summary-copy-block-comparch');
      const text = block.textContent ?? '';
      expect(text).toMatch(/Auth — score 45/);
      expect(text).not.toMatch(/Billing — score 72/);
    });
  });

  it('Copy button writes the formatted block to the clipboard', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    mockedFetch.mockResolvedValue(makeSummary());
    render(
      <TestQueryWrapper>
        <TierReviewSummaryPanel projectId="proj_1" tier="comparch" />
      </TestQueryWrapper>,
    );
    const button = await screen.findByTestId('tier-review-summary-copy-comparch');
    fireEvent.click(button);
    await waitFor(() => expect(writeText).toHaveBeenCalled());
    const written: string = writeText.mock.calls[0][0];
    expect(written).toMatch(/^# Comparch — 3 reviews/);
    expect(written).toMatch(/Auth — score 45/);
  });

  it('renders the missing list when scopes failed to summarise', async () => {
    mockedFetch.mockResolvedValue(
      makeSummary({
        missing: [
          { scope_id: 'comp_x', scope_label: 'Bad', reason: 'parse failed: bad xml' },
          { scope_id: 'comp_y', scope_label: 'Empty', reason: 'empty review' },
        ],
        missing_count: 2,
        draft_count: 5,
      }),
    );
    render(
      <TestQueryWrapper>
        <TierReviewSummaryPanel projectId="proj_1" tier="comparch" />
      </TestQueryWrapper>,
    );
    const list = await screen.findByTestId('tier-review-summary-missing-comparch');
    expect(list).toHaveTextContent('Bad');
    expect(list).toHaveTextContent('parse failed: bad xml');
    expect(list).toHaveTextContent('Empty');
    expect(list).toHaveTextContent('empty review');
  });

  it('shows the empty-state message when no drafts exist', async () => {
    mockedFetch.mockResolvedValue(
      makeSummary({
        draft_count: 0,
        reviewed_count: 0,
        missing_count: 0,
        score_stats: null,
        score_buckets: { band_0_30: 0, band_31_60: 0, band_61_85: 0, band_86_100: 0 },
        handles_count_mean: null,
        arch_count_mean: null,
        reviews: [],
        missing: [],
      }),
    );
    render(
      <TestQueryWrapper>
        <TierReviewSummaryPanel projectId="proj_1" tier="comparch" />
      </TestQueryWrapper>,
    );
    expect(
      await screen.findByText(/No drafts in this tier yet/),
    ).toBeInTheDocument();
  });
});
