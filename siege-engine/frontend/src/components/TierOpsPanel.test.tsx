import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TestQueryWrapper } from '../test/queryWrapper';
import { TierOpsPanel } from './TierOpsPanel';

vi.mock('../api/tierOps', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/tierOps')>();
  return {
    ...actual,
    getTierInfo: vi.fn(),
    getTierReviewSummary: vi.fn(),
  };
});

import * as tierOpsApi from '../api/tierOps';

const mockedGetInfo = tierOpsApi.getTierInfo as unknown as ReturnType<typeof vi.fn>;

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

  // TODO Phase 3 reinstate test once dashboard is read-only:
  //   - Reset All requires a confirm tap before firing
  //   - Regen From Reviews fires immediately and reports skipped scopes
  // Both confirm/fire flows moved to CC skills; the dashboard buttons
  // are now disabled Open-in-CC fallbacks. Assert presence + disabled.
  it('Reset All renders as an Open-in-CC disabled button', async () => {
    mockedGetInfo.mockImplementation(async (_pid: string, tier: string) =>
      makeInfo({ tier, node_count: 2, nodes_with_content: 2 }),
    );
    renderPanel();
    const button = await screen.findByTestId('tier-row-comparch-reset-button');
    expect(button).toBeDisabled();
    expect(button).toHaveTextContent(/Open in Claude Code/i);
    fireEvent.click(button);
    // Confirm flow + reset endpoint are gone.
    expect(
      screen.queryByTestId('tier-row-comparch-confirm-reset-button'),
    ).toBeNull();
  });

  it('Regen From Reviews renders as an Open-in-CC disabled button', async () => {
    mockedGetInfo.mockImplementation(async (_pid: string, tier: string) =>
      makeInfo({ tier, node_count: 2, nodes_with_content: 1 }),
    );
    renderPanel();
    const button = await screen.findByTestId('tier-row-comparch-review-button');
    expect(button).toBeDisabled();
    expect(button).toHaveTextContent(/Open in Claude Code/i);
  });

  // TODO Phase 3 reinstate test once dashboard is read-only:
  //   - disables Reset All when the tier has zero nodes
  //   - disables Review All when no nodes have content
  // Both buttons are now permanently disabled (Open-in-CC fallback);
  // the zero-node / zero-content gating moves into the CC skills.

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

  it('Review summary enables on pending drafts (no approved content yet)', async () => {
    // The actual user-bug case: 40 comparch comps with pending
    // drafts but no approvals. nodes_with_content = 0 but
    // reviewable_count = 40 — the summary toggle should fire even
    // though the Review-All action is now an Open-in-CC fallback.
    mockedGetInfo.mockImplementation(async (_pid: string, tier: string) =>
      makeInfo({
        tier,
        node_count: 40,
        nodes_with_content: 0,
        reviewable_count: 40,
      }),
    );
    renderPanel();
    const summary = await screen.findByTestId('tier-row-comparch-review-summary-button');
    await waitFor(() => {
      expect(summary).not.toBeDisabled();
    });
  });
});
