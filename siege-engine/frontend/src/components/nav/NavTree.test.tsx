import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { StructureNode } from '../../api/structure';
import { NavTree } from './NavTree';

function n(
  id: string,
  tier: string,
  parent_id: string | null,
  overrides: Partial<StructureNode> = {},
): StructureNode {
  return {
    id,
    tier,
    kind: 'domain',
    parent_id,
    name: id,
    display_order: 0,
    content: '',
    has_content: true,
    has_pending_draft: false,
    generation_running: false,
    has_error: false,
    ...overrides,
  };
}

describe('NavTree', () => {
  it('renders synthetic entries + singleton tiers + components subtree', () => {
    const nodes = [
      n('expansion_1', 'expansion', null, { name: 'Expansion' }),
      n('comp_A', 'comp', null, { name: 'Billing' }),
      n('comp_Asub', 'comp', 'comp_A', { name: 'BillingStore' }),
    ];
    render(<NavTree nodes={nodes} selectedId={null} onSelect={() => {}} />);
    expect(screen.getByText('Feature Expansion')).toBeInTheDocument();
    expect(screen.getByText('Vocabulary')).toBeInTheDocument();
    expect(screen.getByText('References')).toBeInTheDocument();
    expect(screen.getByText('Decomposition Graph')).toBeInTheDocument();
    expect(screen.getByText('Components')).toBeInTheDocument();
    // Components root defaults to expanded → the comp is visible.
    expect(screen.getByText('Billing')).toBeInTheDocument();
    // But the sub's parent is collapsed by default.
    expect(screen.queryByText('BillingStore')).not.toBeInTheDocument();
  });

  it('invokes onSelect when a leaf is clicked', async () => {
    const onSelect = vi.fn();
    const nodes = [n('expansion_1', 'expansion', null)];
    render(<NavTree nodes={nodes} selectedId={null} onSelect={onSelect} />);
    await userEvent.click(screen.getByText('Feature Expansion'));
    expect(onSelect).toHaveBeenCalledWith('expansion_1');
  });

  it('expands a comp subtree when the disclosure triangle is clicked', async () => {
    const nodes = [
      n('comp_A', 'comp', null, { name: 'Billing' }),
      n('comp_Asub', 'comp', 'comp_A', { name: 'BillingStore' }),
    ];
    render(<NavTree nodes={nodes} selectedId={null} onSelect={() => {}} />);
    expect(screen.queryByText('BillingStore')).not.toBeInTheDocument();
    // Find the expand button for Billing — it's a sibling of the label.
    const billingRow = screen.getByText('Billing').closest('div')!;
    const expandBtn = billingRow.querySelector('button[aria-label="Expand"]');
    expect(expandBtn).not.toBeNull();
    await userEvent.click(expandBtn!);
    expect(screen.getByText('BillingStore')).toBeInTheDocument();
  });

  it('auto-expands ancestors of the selected node', () => {
    const nodes = [
      n('comp_A', 'comp', null, { name: 'Billing' }),
      n('comp_Asub', 'comp', 'comp_A', { name: 'BillingStore' }),
      n('impl_Asub', 'impl', 'comp_Asub'),
    ];
    render(
      <NavTree nodes={nodes} selectedId="impl_Asub" onSelect={() => {}} />,
    );
    // Billing → BillingStore → Implementation chain all visible
    // because the layout hook expanded ancestors.
    expect(screen.getByText('Billing')).toBeInTheDocument();
    expect(screen.getByText('BillingStore')).toBeInTheDocument();
    expect(screen.getByText('Implementation')).toBeInTheDocument();
  });

  it('fires onLeafSelect when a leaf is chosen (for drawer auto-close)', async () => {
    const onSelect = vi.fn();
    const onLeafSelect = vi.fn();
    const nodes = [n('expansion_1', 'expansion', null)];
    render(
      <NavTree
        nodes={nodes}
        selectedId={null}
        onSelect={onSelect}
        onLeafSelect={onLeafSelect}
      />,
    );
    await userEvent.click(screen.getByText('Feature Expansion'));
    expect(onLeafSelect).toHaveBeenCalled();
  });

  it('does not invoke onSelect for the Components header row', async () => {
    const onSelect = vi.fn();
    const nodes = [n('comp_A', 'comp', null, { name: 'Billing' })];
    render(<NavTree nodes={nodes} selectedId={null} onSelect={onSelect} />);
    await userEvent.click(screen.getByText('Components'));
    // Header is non-selectable; click just toggles expand.
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('renders status indicators for pending and running state', () => {
    const nodes = [
      n('reqs_1', 'reqs', null, { has_pending_draft: true }),
      n('sysarch_1', 'sysarch', null, { generation_running: true }),
    ];
    render(<NavTree nodes={nodes} selectedId={null} onSelect={() => {}} />);
    expect(screen.getByLabelText('Draft awaiting review')).toBeInTheDocument();
    expect(screen.getByLabelText('Generating')).toBeInTheDocument();
  });
});
