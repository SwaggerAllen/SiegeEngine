import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { DraftDiffView } from './DraftDiffView';

describe('DraftDiffView', () => {
  it('renders a hint when no prior version is available', () => {
    render(<DraftDiffView before={null} after="<sysarch>v1</sysarch>" />);
    expect(
      screen.getByText(/first version on this tier/i),
    ).toBeInTheDocument();
  });

  it('renders an empty-state hint when before and after match', () => {
    const same = '<sysarch>unchanged</sysarch>';
    render(<DraftDiffView before={same} after={same} />);
    expect(screen.getByText(/No changes/i)).toBeInTheDocument();
  });

  it('renders a visible diff when before and after differ', () => {
    render(
      <DraftDiffView
        before="<sysarch>v1 line one</sysarch>"
        after="<sysarch>v2 line one</sysarch>"
        label="Comparing against the previous draft."
      />,
    );
    // Label surfaces so the user knows which side is which.
    expect(
      screen.getByText(/Comparing against the previous draft/i),
    ).toBeInTheDocument();
    // Both content fragments are visible in the rendered diff rows.
    expect(screen.getByText(/v1 line one/)).toBeInTheDocument();
    expect(screen.getByText(/v2 line one/)).toBeInTheDocument();
    // Layout toggle is available so the user can flip to unified view.
    expect(
      screen.getByRole('button', { name: /Side-by-side/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Unified/i })).toBeInTheDocument();
  });

  it('flips to unified layout on click', async () => {
    const user = userEvent.setup();
    render(
      <DraftDiffView
        before="<sysarch>v1</sysarch>"
        after="<sysarch>v2</sysarch>"
      />,
    );
    const sideBySide = screen.getByRole('button', { name: /Side-by-side/i });
    const unified = screen.getByRole('button', { name: /Unified/i });
    expect(sideBySide).toHaveAttribute('aria-pressed', 'true');
    expect(unified).toHaveAttribute('aria-pressed', 'false');

    await user.click(unified);
    expect(unified).toHaveAttribute('aria-pressed', 'true');
    expect(sideBySide).toHaveAttribute('aria-pressed', 'false');
  });

  describe('summaryText', () => {
    it('renders above the diff when provided', () => {
      render(
        <DraftDiffView
          before="<sysarch>v1</sysarch>"
          after="<sysarch>v2</sysarch>"
          summaryText="Split Auth into five atoms per the review's compound-name finding."
        />,
      );
      const summary = screen.getByTestId('draft-diff-summary');
      expect(summary).toBeInTheDocument();
      expect(summary).toHaveTextContent('Split Auth into five atoms');
    });

    it('is omitted when the summary is empty or whitespace-only', () => {
      const { rerender } = render(
        <DraftDiffView
          before="<sysarch>v1</sysarch>"
          after="<sysarch>v2</sysarch>"
          summaryText={null}
        />,
      );
      expect(screen.queryByTestId('draft-diff-summary')).not.toBeInTheDocument();

      rerender(
        <DraftDiffView
          before="<sysarch>v1</sysarch>"
          after="<sysarch>v2</sysarch>"
          summaryText="   "
        />,
      );
      expect(screen.queryByTestId('draft-diff-summary')).not.toBeInTheDocument();
    });

    it('renders above the "no prior version" empty state', () => {
      render(
        <DraftDiffView
          before={null}
          after="<sysarch>v1</sysarch>"
          summaryText="First pass — initial shape of the document."
        />,
      );
      expect(screen.getByTestId('draft-diff-summary')).toHaveTextContent(
        'First pass',
      );
      expect(
        screen.getByText(/first version on this tier/i),
      ).toBeInTheDocument();
    });

    it('renders above the "no changes" empty state', () => {
      const same = '<sysarch>unchanged</sysarch>';
      render(
        <DraftDiffView
          before={same}
          after={same}
          summaryText="Regen produced identical output."
        />,
      );
      expect(screen.getByTestId('draft-diff-summary')).toHaveTextContent(
        'Regen produced identical output.',
      );
      expect(screen.getByText(/No changes/i)).toBeInTheDocument();
    });
  });
});
