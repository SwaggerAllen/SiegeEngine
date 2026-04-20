import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { StructureNode } from '../api/structure';
import { ComponentOverviewPanel } from './ComponentOverviewPanel';

function comp(overrides: Partial<StructureNode> = {}): StructureNode {
  return {
    id: 'comp_1',
    tier: 'comp',
    kind: 'domain',
    parent_id: null,
    name: 'Billing',
    display_order: 0,
    content: '',
    has_content: false,
    has_pending_draft: false,
    generation_running: false,
    has_error: false,
    needs_user_action: false,
    is_stale: false,
    staleness_reasons: [],
    techspec: '',
    pubapi: '',
    ...overrides,
  };
}

describe('ComponentOverviewPanel', () => {
  it('renders the component name + placeholders when fragments are empty', () => {
    render(<ComponentOverviewPanel component={comp({ name: 'Billing' })} />);
    expect(screen.getByRole('heading', { name: 'Billing' })).toBeInTheDocument();
    const placeholders = screen.getAllByText(/Not yet populated/i);
    expect(placeholders.length).toBe(2);
  });

  it('renders techspec + pubapi bodies when populated, splitting paragraphs', () => {
    render(
      <ComponentOverviewPanel
        component={comp({
          techspec: 'Runs as a Python service.\n\nUses PostgreSQL for persistence.',
          pubapi: 'Mints and refreshes session tokens.',
        })}
      />,
    );
    expect(screen.getByText('Runs as a Python service.')).toBeInTheDocument();
    expect(screen.getByText('Uses PostgreSQL for persistence.')).toBeInTheDocument();
    expect(screen.getByText('Mints and refreshes session tokens.')).toBeInTheDocument();
  });
});
