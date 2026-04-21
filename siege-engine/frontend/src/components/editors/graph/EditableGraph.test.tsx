import { render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

// Mock react-cytoscapejs to a minimal harness that lets us drive
// the cy event handlers without running ELK in jsdom. The harness
// exposes a helper via a module-level variable so tests can
// trigger synthetic tap events the component would otherwise
// receive from cytoscape.
interface FakeCy {
  on: (ev: string, cb: (e: unknown) => void) => void;
  off: (ev: string, cb: (e: unknown) => void) => void;
  batch: (fn: () => void) => void;
  elements: () => { removeClass: () => void };
  nodes: () => { forEach: (cb: (n: unknown) => void) => void };
  $id: (id: string) => { length: number; addClass: () => void; removeClass: () => void };
  layout: () => { run: () => void };
}

let latestCy: FakeCy | null = null;

vi.mock('react-cytoscapejs', () => ({
  default: ({ cy }: { cy: (cy: FakeCy) => void }) => {
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
      nodes: () => ({ forEach: () => {} }),
      $id: () => ({ length: 0, addClass: () => {}, removeClass: () => {} }),
      layout: () => ({ run: () => {} }),
    };
    // Expose a `_fire` hook so tests can drive handlers directly.
    (fakeCy as unknown as { _fire: (ev: string, e: unknown) => void })._fire = (
      ev,
      e,
    ) => handlers.get(ev)?.forEach((h) => h(e));
    latestCy = fakeCy;
    cy(fakeCy);
    return null;
  },
}));

vi.mock('../../../lib/cytoscapeExtensions', () => ({}));

import { EditableGraph } from './EditableGraph';
import type { EditableGraphSelection } from './useEditableGraphSelection';

function makeSelection(): EditableGraphSelection & {
  _lastNodeTap: string | null;
  _lastEdgeTap: string | null;
  _backgroundTaps: number;
} {
  const selection = {
    state: { kind: 'idle' as const },
    _lastNodeTap: null as string | null,
    _lastEdgeTap: null as string | null,
    _backgroundTaps: 0,
    onNodeTap: (id: string) => {
      selection._lastNodeTap = id;
    },
    onEdgeTap: (id: string) => {
      selection._lastEdgeTap = id;
    },
    onBackgroundTap: () => {
      selection._backgroundTaps += 1;
    },
    commit: () => {},
    cancel: () => {},
  };
  return selection;
}

function fire(ev: string, target: unknown) {
  (latestCy as unknown as { _fire: (ev: string, e: unknown) => void })._fire(ev, {
    target,
  });
}

describe('EditableGraph tap routing', () => {
  it('routes node tap to onNodeTap with the node id', () => {
    const sel = makeSelection();
    render(<EditableGraph elements={[]} stylesheet={[]} selection={sel} />);
    fire('tap', { isNode: () => true, isEdge: () => false, id: () => 'n1' });
    expect(sel._lastNodeTap).toBe('n1');
  });

  it('routes edge tap to onEdgeTap with the edge id', () => {
    const sel = makeSelection();
    render(<EditableGraph elements={[]} stylesheet={[]} selection={sel} />);
    fire('tap', { isNode: () => false, isEdge: () => true, id: () => 'edge_1' });
    expect(sel._lastEdgeTap).toBe('edge_1');
  });

  it('routes background tap to onBackgroundTap', () => {
    const sel = makeSelection();
    render(<EditableGraph elements={[]} stylesheet={[]} selection={sel} />);
    fire('tap', latestCy);
    expect(sel._backgroundTaps).toBe(1);
  });
});
