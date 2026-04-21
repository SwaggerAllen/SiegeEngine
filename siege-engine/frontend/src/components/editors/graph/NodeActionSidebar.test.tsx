import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { NodeActionSidebar, SidebarActionButton } from './NodeActionSidebar';

describe('NodeActionSidebar', () => {
  it('renders title + actions', () => {
    render(
      <NodeActionSidebar
        title="Billing"
        subtitle="top-level comp"
        actions={
          <SidebarActionButton
            label="Rename…"
            onClick={() => {}}
            testId="btn-rename"
          />
        }
      />,
    );
    expect(screen.getByText('Billing')).toBeInTheDocument();
    expect(screen.getByText('top-level comp')).toBeInTheDocument();
    expect(screen.getByTestId('btn-rename')).toBeInTheDocument();
  });

  it('onCancel fires when Close is clicked', async () => {
    const onCancel = vi.fn();
    render(<NodeActionSidebar title="X" actions={null} onCancel={onCancel} />);
    await userEvent.click(screen.getByRole('button', { name: /close/i }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('Close button is hidden when onCancel is not provided', () => {
    render(<NodeActionSidebar title="X" actions={null} />);
    expect(screen.queryByRole('button', { name: /close/i })).toBeNull();
  });
});

describe('SidebarActionButton', () => {
  it('calls onClick when enabled', async () => {
    const fn = vi.fn();
    render(<SidebarActionButton label="Do it" onClick={fn} testId="btn" />);
    await userEvent.click(screen.getByTestId('btn'));
    expect(fn).toHaveBeenCalled();
  });

  it('does not call onClick when disabled', async () => {
    const fn = vi.fn();
    render(
      <SidebarActionButton label="Do it" onClick={fn} disabled testId="btn" />,
    );
    await userEvent.click(screen.getByTestId('btn'));
    expect(fn).not.toHaveBeenCalled();
  });

  it('applies the destructive palette', () => {
    render(
      <SidebarActionButton
        label="Delete"
        onClick={() => {}}
        variant="destructive"
        testId="btn"
      />,
    );
    expect(screen.getByTestId('btn').className).toContain('bg-red-900');
  });
});
