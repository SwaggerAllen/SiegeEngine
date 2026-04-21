import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { StructureNode } from '../../api/structure';
import { TestQueryWrapper } from '../../test/queryWrapper';

// Mock react-cytoscapejs to a harness identical to the one in
// graph/EditableGraph.test.tsx — lets us drive Cytoscape's
// `tap` event without running ELK in jsdom.
interface FakeCy {
  on: (ev: string, cb: (e: unknown) => void) => void;
  off: (ev: string, cb: (e: unknown) => void) => void;
  batch: (fn: () => void) => void;
  elements: () => { removeClass: () => void };
  nodes: () => { forEach: (cb: (n: unknown) => void) => void; removeClass: () => void };
  $id: (id: string) => { length: number; addClass: () => void; removeClass: () => void };
  layout: () => { run: () => void };
}

let latestCy: FakeCy | null = null;

vi.mock('react-cytoscapejs', () => ({
  default: ({ cy }: { cy: (cy: FakeCy) => void }) => {
    // Single stable fakeCy across renders so the handler
    // registration in EditableGraph's useEffect survives.
    // Tests reset via `beforeEach(() => { latestCy = null; })`
    // which forces a fresh one on the next render.
    if (!latestCy) {
      const handlers = new Map<string, Array<(e: unknown) => void>>();
      const fakeCy: FakeCy = {
        on: (ev, cb) => {
          const arr = handlers.get(ev) ?? [];
          arr.push(cb);
          handlers.set(ev, arr);
        },
        off: (ev, cb) => {
          const arr = handlers.get(ev) ?? [];
          handlers.set(
            ev,
            arr.filter((h) => h !== cb),
          );
        },
        batch: (fn) => fn(),
        elements: () => ({ removeClass: () => {} }),
        nodes: () => ({ forEach: () => {}, removeClass: () => {} }),
        $id: () => ({ length: 0, addClass: () => {}, removeClass: () => {} }),
        layout: () => ({ run: () => {} }),
      };
      (fakeCy as unknown as { _fire: (ev: string, e: unknown) => void })._fire = (
        ev,
        e,
      ) => handlers.get(ev)?.forEach((h) => h(e));
      latestCy = fakeCy;
    }
    cy(latestCy);
    return null;
  },
}));

vi.mock('../../lib/cytoscapeExtensions', () => ({}));

vi.mock('../../api/queue', async () => {
  const actual = await vi.importActual<typeof import('../../api/queue')>('../../api/queue');
  let counter = 0;
  return {
    ...actual,
    enqueueInstruction: vi.fn(),
    mintClientId: vi.fn((kind: string) => `${kind}_TEST${counter++}`),
  };
});

import * as queueApi from '../../api/queue';
import { DecompositionGraphView } from './DecompositionGraphView';

const mockedEnqueue = queueApi.enqueueInstruction as unknown as ReturnType<typeof vi.fn>;

function node(
  id: string,
  name: string,
  parent_id: string | null = null,
): StructureNode {
  return {
    id,
    name,
    tier: 'comp',
    kind: 'domain',
    parent_id,
    display_order: 0,
    content: '',
    has_content: true,
    has_pending_draft: false,
    generation_running: false,
    has_error: false,
    needs_user_action: false,
    is_stale: false,
    staleness_reasons: [],
    techspec: '',
    pubapi: '',
    is_deferred: false,
  };
}

function tapNode(id: string) {
  (latestCy as unknown as { _fire: (ev: string, e: unknown) => void })._fire('tap', {
    target: {
      isNode: () => true,
      isEdge: () => false,
      id: () => id,
    },
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  latestCy = null;
});

describe('DecompositionGraphView — Merge', () => {
  it('enqueues a Merge instruction keeping one source identity', async () => {
    mockedEnqueue.mockResolvedValue({ sequence: 1 });
    const comps = [
      node('comp_TOP', 'Top'),
      node('comp_A', 'A', 'comp_TOP'),
      node('comp_B', 'B', 'comp_TOP'),
    ];
    render(
      <TestQueryWrapper>
        <DecompositionGraphView projectId="p1" allComps={comps} />
      </TestQueryWrapper>,
    );
    // Enter multi-select mode.
    await userEvent.click(screen.getByTestId('decomp-toggle-multi'));
    // Tap both subcomps to build the selection set.
    tapNode('comp_A');
    tapNode('comp_B');
    // Wait for the Merge action to become available in the sidebar.
    await userEvent.click(await screen.findByTestId('decomp-action-merge'));
    // Pick "Keep A" and rename to "AB".
    const destChoice = screen.getByTestId('decomp-merge-dest-choice') as HTMLSelectElement;
    await userEvent.selectOptions(destChoice, 'comp_A');
    const destName = screen.getByTestId('decomp-merge-dest-name') as HTMLInputElement;
    fireEvent.change(destName, { target: { value: 'AB' } });
    await userEvent.click(screen.getByTestId('decomp-merge-submit'));

    expect(mockedEnqueue).toHaveBeenCalledWith('p1', {
      instruction_type: 'Merge',
      source_ids: ['comp_A', 'comp_B'],
      source_names: ['A', 'B'],
      dest_id: 'comp_A',
      dest_name: 'AB',
    });
  });

  it('mints a fresh id when "New node" is picked as destination', async () => {
    mockedEnqueue.mockResolvedValue({ sequence: 1 });
    const comps = [
      node('comp_TOP', 'Top'),
      node('comp_A', 'A', 'comp_TOP'),
      node('comp_B', 'B', 'comp_TOP'),
    ];
    render(
      <TestQueryWrapper>
        <DecompositionGraphView projectId="p1" allComps={comps} />
      </TestQueryWrapper>,
    );
    await userEvent.click(screen.getByTestId('decomp-toggle-multi'));
    tapNode('comp_A');
    tapNode('comp_B');
    await userEvent.click(await screen.findByTestId('decomp-action-merge'));
    const destChoice = screen.getByTestId('decomp-merge-dest-choice') as HTMLSelectElement;
    await userEvent.selectOptions(destChoice, '__new__');
    const destName = screen.getByTestId('decomp-merge-dest-name') as HTMLInputElement;
    fireEvent.change(destName, { target: { value: 'Combined' } });
    await userEvent.click(screen.getByTestId('decomp-merge-submit'));

    const call = mockedEnqueue.mock.calls[0][1];
    expect(call.instruction_type).toBe('Merge');
    expect(call.dest_name).toBe('Combined');
    expect(call.dest_id.startsWith('comp_TEST')).toBe(true);
  });

  it('blocks Merge when the selected nodes have different parents', async () => {
    const comps = [
      node('comp_TOP_X', 'X'),
      node('comp_TOP_Y', 'Y'),
      node('comp_A', 'A', 'comp_TOP_X'),
      node('comp_B', 'B', 'comp_TOP_Y'),
    ];
    render(
      <TestQueryWrapper>
        <DecompositionGraphView projectId="p1" allComps={comps} />
      </TestQueryWrapper>,
    );
    await userEvent.click(screen.getByTestId('decomp-toggle-multi'));
    tapNode('comp_A');
    tapNode('comp_B');
    await waitFor(() =>
      expect(screen.getByText(/Select 2\+ sibling comps/)).toBeInTheDocument(),
    );
    expect(screen.queryByTestId('decomp-action-merge')).toBeNull();
  });
});

describe('DecompositionGraphView — Split', () => {
  it('enqueues a Split instruction with the entered names', async () => {
    mockedEnqueue.mockResolvedValue({ sequence: 1 });
    const comps = [node('comp_X', 'Billing')];
    render(
      <TestQueryWrapper>
        <DecompositionGraphView projectId="p1" allComps={comps} />
      </TestQueryWrapper>,
    );
    tapNode('comp_X');
    await userEvent.click(await screen.findByTestId('decomp-action-split'));
    // Default seeds two rows with "Billing A", "Billing B".
    const row0 = screen.getByTestId('decomp-split-name-0') as HTMLInputElement;
    const row1 = screen.getByTestId('decomp-split-name-1') as HTMLInputElement;
    fireEvent.change(row0, { target: { value: 'Invoicing' } });
    fireEvent.change(row1, { target: { value: 'Payments' } });
    await userEvent.click(screen.getByTestId('decomp-split-submit'));

    const call = mockedEnqueue.mock.calls[0][1];
    expect(call.instruction_type).toBe('Split');
    expect(call.source_id).toBe('comp_X');
    expect(call.source_name).toBe('Billing');
    expect(call.dest_names).toEqual(['Invoicing', 'Payments']);
    expect(call.dest_ids).toHaveLength(2);
    expect(call.dest_ids[0].startsWith('comp_TEST')).toBe(true);
  });

  it('disables submit until at least 2 non-empty names are present', async () => {
    const comps = [node('comp_X', 'Billing')];
    render(
      <TestQueryWrapper>
        <DecompositionGraphView projectId="p1" allComps={comps} />
      </TestQueryWrapper>,
    );
    tapNode('comp_X');
    await userEvent.click(await screen.findByTestId('decomp-action-split'));
    const row0 = screen.getByTestId('decomp-split-name-0') as HTMLInputElement;
    const row1 = screen.getByTestId('decomp-split-name-1') as HTMLInputElement;
    fireEvent.change(row0, { target: { value: '' } });
    fireEvent.change(row1, { target: { value: '' } });
    expect(screen.getByTestId('decomp-split-submit')).toBeDisabled();
  });
});
