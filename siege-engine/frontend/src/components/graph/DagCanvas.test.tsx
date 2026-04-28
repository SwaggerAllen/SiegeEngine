import { render } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// Mock react-cytoscapejs so jsdom doesn't try to spin up a real
// cytoscape (no canvas). Capture the most recent ``layout`` prop
// so direction assertions can read it back.
let lastLayoutProp: { elk?: Record<string, unknown> } | undefined;
vi.mock('react-cytoscapejs', () => ({
  default: (props: { layout?: { elk?: Record<string, unknown> } }) => {
    lastLayoutProp = props.layout;
    return <div data-testid="cy-canvas" />;
  },
}));

function setMatchMedia(matches: (query: string) => boolean) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    configurable: true,
    value: (query: string) => ({
      matches: matches(query),
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: () => false,
    }),
  });
}

import { DagCanvas } from './DagCanvas';
import { fullDagStylesheet } from './stylesheet';

beforeEach(() => {
  lastLayoutProp = undefined;
  setMatchMedia(() => false);
});

describe('DagCanvas', () => {
  it('lays out top-to-bottom on a desktop viewport', () => {
    setMatchMedia(() => false);
    render(<DagCanvas elements={[]} stylesheet={fullDagStylesheet} />);
    expect(lastLayoutProp?.elk?.['elk.direction']).toBe('DOWN');
  });

  it('lays out left-to-right on a narrow viewport', () => {
    setMatchMedia((q) => q === '(max-width: 768px)');
    render(<DagCanvas elements={[]} stylesheet={fullDagStylesheet} />);
    expect(lastLayoutProp?.elk?.['elk.direction']).toBe('RIGHT');
  });
});
