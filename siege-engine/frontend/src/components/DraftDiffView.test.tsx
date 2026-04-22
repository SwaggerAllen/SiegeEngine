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
});
