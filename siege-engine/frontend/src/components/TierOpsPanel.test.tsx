import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TestQueryWrapper } from '../test/queryWrapper';
import { TierOpsPanel } from './TierOpsPanel';

vi.mock('../api/tierOps', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/tierOps')>();
  return {
    ...actual,
    getTierInfo: vi.fn(),
    resetTier: vi.fn(),
    reviewSweepTier: vi.fn(),
    getTierReviewSummary: vi.fn(),
  };
});

import * as tierOpsApi from '../api/tierOps';

const mockedGetInfo = tierOpsApi.getTierInfo as unknown as ReturnType<typeof vi.fn>;
const mockedReset = tierOpsApi.resetTier as unknown as ReturnType<typeof vi.fn>;
const mockedReview = tierOpsApi.reviewSweepTier as unknown as ReturnType<typeof vi.fn>;

function makeInfo(overrides: Partial<tierOpsApi.TierInfo> = {}): tierOpsApi.TierInfo {
  // Default ``reviewable_count`` mirrors ``nodes_with_content`` so
  // the legacy tests that only set ``nodes_with_content`` still get
  // sensible gate behaviour. Tests that exercise the pending-draft
  // case override ``reviewable_count`` explicitly.
  const nodes_with_content = overrides.nodes_with_content ?? 2;
  return {
    tier: 'comparch',
    tier_name: 'Comparch',
    node_count: 2,
    nodes_with_content,
    reviewable_count: nodes_with_content,
    supports_reset: true,
    supports_review: true,
    avg_generation_seconds: null,
    generation_sample_size: 0,
    ...overrides,
  };
}

function renderPanel() {
  return render(
    <TestQueryWrapper>
      <TierOpsPanel projectId="proj_1" />
    </TestQueryWrapper>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  // Default: every tier returns 0 nodes so the panel renders rows
  // but most buttons are disabled. Individual tests override by
  // queueing per-call responses.
  mockedGetInfo.mockResolvedValue(
    makeInfo({ tier: 'comparch', node_count: 0, nodes_with_content: 0 }),
  );
});

describe('TierOpsPanel', () => {
  it('renders one row per tier', async () => {
    renderPanel();
    await waitFor(() =>
      expect(screen.getByTestId('tier-row-expansion')).toBeInTheDocument(),
    );
    for (const tier of [
      'expansion',
      'requirements',
      'sysarch',
      'comparch',
      'subcomparch',
      'impl',
    ]) {
      expect(screen.getByTestId(`tier-row-${tier}`)).toBeInTheDocument();
    }
  });

  it('shows node count from the tier info endpoint', async () => {
    mockedGetInfo.mockImplementation(async (_pid: string, tier: string) =>
      makeInfo({ tier, node_count: tier === 'comparch' ? 3 : 0, nodes_with_content: 1 }),
    );
    renderPanel();
    const comparchRow = await screen.findByTestId('tier-row-comparch');
    await waitFor(() => expect(comparchRow).toHaveTextContent(/3 nodes · 1 with content/));
  });

  it('shows the avg generation time when sample size is non-zero', async () => {
    mockedGetInfo.mockImplementation(async (_pid: string, tier: string) =>
      makeInfo({
        tier,
        node_count: 2,
        nodes_with_content: 2,
        avg_generation_seconds: 95,
        generation_sample_size: 8,
      }),
    );
    renderPanel();
    const comparchRow = await screen.findByTestId('tier-row-comparch');
    // 95s formats to "1m 35s".
    await waitFor(() =>
      expect(comparchRow).toHaveTextContent(/avg gen 1m 35s.*n=8/),
    );
  });

  it('hides the avg generation cell when no completed jobs exist yet', async () => {
    mockedGetInfo.mockImplementation(async (_pid: string, tier: string) =>
      makeInfo({
        tier,
        node_count: 2,
        nodes_with_content: 2,
        avg_generation_seconds: null,
        generation_sample_size: 0,
      }),
    );
    renderPanel();
    const comparchRow = await screen.findByTestId('tier-row-comparch');
    await waitFor(() =>
      expect(comparchRow).toHaveTextContent(/2 nodes · 2 with content/),
    );
    expect(comparchRow).not.toHaveTextContent(/avg gen/);
  });

  it('Reset All requires a confirm tap before firing', async () => {
    mockedGetInfo.mockImplementation(async (_pid: string, tier: string) =>
      makeInfo({ tier, node_count: 2, nodes_with_content: 2 }),
    );
    mockedReset.mockResolvedValue({
      ok: true,
      tier: 'comparch',
      scopes_total: 2,
      scopes_succeeded: 2,
      scopes_skipped: [],
      jobs_cancelled: 4,
      jobs_enqueued: 2,
      drafts_discarded: 0,
      nodes_deleted: 0,
    });
    renderPanel();
    const button = await screen.findByTestId('tier-row-comparch-reset-button');
    fireEvent.click(button);
    // The reset endpoint must NOT have fired yet — confirm step.
    expect(mockedReset).not.toHaveBeenCalled();
    const confirmButton = await screen.findByTestId(
      'tier-row-comparch-confirm-reset-button',
    );
    fireEvent.click(confirmButton);
    await waitFor(() => expect(mockedReset).toHaveBeenCalledWith('proj_1', 'comparch'));
    // Success message reflects scopes_succeeded.
    await waitFor(() =>
      expect(screen.getByTestId('tier-row-comparch-message')).toHaveTextContent(
        /Reset 2 scopes · 2 generations queued/,
      ),
    );
  });

  it('Regen From Reviews fires immediately and reports skipped scopes', async () => {
    mockedGetInfo.mockImplementation(async (_pid: string, tier: string) =>
      makeInfo({ tier, node_count: 2, nodes_with_content: 1 }),
    );
    mockedReview.mockResolvedValue({
      ok: true,
      tier: 'comparch',
      scopes_total: 2,
      jobs_enqueued: 1,
      scopes_skipped: [
        { scope_ids: ['comp_2'], status: 409, detail: 'already approved' },
      ],
    });
    renderPanel();
    const button = await screen.findByTestId('tier-row-comparch-review-button');
    fireEvent.click(button);
    await waitFor(() =>
      expect(mockedReview).toHaveBeenCalledWith('proj_1', 'comparch'),
    );
    await waitFor(() =>
      expect(screen.getByTestId('tier-row-comparch-message')).toHaveTextContent(
        /Regenerated 1 scope \(1 skipped\)/,
      ),
    );
  });

  it('disables Reset All when the tier has zero nodes', async () => {
    mockedGetInfo.mockImplementation(async (_pid: string, tier: string) =>
      makeInfo({ tier, node_count: 0, nodes_with_content: 0 }),
    );
    renderPanel();
    const button = await screen.findByTestId('tier-row-comparch-reset-button');
    expect(button).toBeDisabled();
  });

  it('disables Review All when no nodes have content', async () => {
    mockedGetInfo.mockImplementation(async (_pid: string, tier: string) =>
      makeInfo({ tier, node_count: 2, nodes_with_content: 0 }),
    );
    renderPanel();
    const button = await screen.findByTestId('tier-row-comparch-review-button');
    expect(button).toBeDisabled();
  });

  it('Review summary toggle flips aria-expanded state', async () => {
    mockedGetInfo.mockImplementation(async (_pid: string, tier: string) =>
      makeInfo({ tier, node_count: 3, nodes_with_content: 3 }),
    );
    // Inline panel itself is exercised by its own test file. Here we
    // only verify the toggle button renders + dispatches a click that
    // flips its expansion state once the tier-info query resolves and
    // enables it.
    renderPanel();
    const toggle = await screen.findByTestId('tier-row-comparch-review-summary-button');
    await waitFor(() => expect(toggle).not.toBeDisabled());
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(toggle);
    await waitFor(() => expect(toggle).toHaveAttribute('aria-expanded', 'true'));
    fireEvent.click(toggle);
    await waitFor(() => expect(toggle).toHaveAttribute('aria-expanded', 'false'));
  });

  it('Review summary toggle is disabled when the tier has zero content', async () => {
    mockedGetInfo.mockImplementation(async (_pid: string, tier: string) =>
      makeInfo({ tier, node_count: 0, nodes_with_content: 0 }),
    );
    renderPanel();
    const toggle = await screen.findByTestId('tier-row-comparch-review-summary-button');
    expect(toggle).toBeDisabled();
  });

  it('Review All + Review summary enable on pending drafts (no approved content yet)', async () => {
    // The actual user-bug case: 40 comparch comps with pending
    // drafts but no approvals. nodes_with_content = 0 but
    // reviewable_count = 40 — the buttons should fire.
    mockedGetInfo.mockImplementation(async (_pid: string, tier: string) =>
      makeInfo({
        tier,
        node_count: 40,
        nodes_with_content: 0,
        reviewable_count: 40,
      }),
    );
    renderPanel();
    const reviewAll = await screen.findByTestId('tier-row-comparch-review-button');
    const summary = await screen.findByTestId('tier-row-comparch-review-summary-button');
    await waitFor(() => {
      expect(reviewAll).not.toBeDisabled();
      expect(summary).not.toBeDisabled();
    });
  });
});
