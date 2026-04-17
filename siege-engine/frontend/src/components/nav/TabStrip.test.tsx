import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { TabStrip } from './TabStrip';
import type { TabScope } from './tabScope';

function scopeFixture(overrides: Partial<TabScope> = {}): TabScope {
  return {
    tabs: [],
    activeKey: null,
    scopeLabel: null,
    ...overrides,
  };
}

describe('TabStrip', () => {
  it('renders nothing when tabs are empty', () => {
    const { container } = render(
      <TabStrip scope={scopeFixture()} onSelectTab={() => {}} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('renders scope label + tab buttons, marking the active tab aria-selected', () => {
    render(
      <TabStrip
        scope={scopeFixture({
          scopeLabel: 'Billing',
          activeKey: 'overview',
          tabs: [
            { key: 'overview', label: 'Overview', targetNodeId: 'comp_1', targetView: 'overview' },
            { key: 'subreqs', label: 'Subrequirements', targetNodeId: 'subreqs_1' },
            { key: 'comparch', label: 'Comparch', targetNodeId: 'comp_1', targetView: 'comparch' },
          ],
        })}
        onSelectTab={() => {}}
      />,
    );
    expect(screen.getByTestId('tab-scope-label')).toHaveTextContent('Billing');
    expect(screen.getByRole('tab', { name: 'Overview' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(screen.getByRole('tab', { name: 'Subrequirements' })).toHaveAttribute(
      'aria-selected',
      'false',
    );
  });

  it('invokes onSelectTab with the clicked tab', async () => {
    const user = userEvent.setup();
    const spy = vi.fn();
    render(
      <TabStrip
        scope={scopeFixture({
          activeKey: 'overview',
          tabs: [
            { key: 'overview', label: 'Overview', targetNodeId: 'comp_1', targetView: 'overview' },
            { key: 'comparch', label: 'Comparch', targetNodeId: 'comp_1', targetView: 'comparch' },
          ],
        })}
        onSelectTab={spy}
      />,
    );
    await user.click(screen.getByRole('tab', { name: 'Comparch' }));
    expect(spy).toHaveBeenCalledOnce();
    expect(spy.mock.calls[0][0].key).toBe('comparch');
  });
});
