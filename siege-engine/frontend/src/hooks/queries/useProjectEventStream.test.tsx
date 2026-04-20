import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { StructureResponse } from '../../api/structure';
import { structureKeys } from './useProjectStructure';
import { useProjectEventStream } from './useProjectEventStream';

// Minimal EventSource mock — holds listeners + exposes a test
// hook to fire fake events. Matches the ``EventSource`` surface
// the production code uses: ``addEventListener``,
// ``removeEventListener``, ``close``.
class FakeEventSource {
  static latest: FakeEventSource | null = null;
  url: string;
  listeners = new Map<string, Set<(event: Event) => void>>();
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeEventSource.latest = this;
  }

  addEventListener(type: string, cb: (event: Event) => void) {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type)!.add(cb);
  }

  removeEventListener(type: string, cb: (event: Event) => void) {
    this.listeners.get(type)?.delete(cb);
  }

  close() {
    this.closed = true;
  }

  // Test helpers — fire a fake event with payload.
  fire(type: string, payload: Record<string, unknown>) {
    const event = new MessageEvent(type, { data: JSON.stringify(payload) });
    this.listeners.get(type)?.forEach((cb) => cb(event));
  }

  fireError() {
    const event = new Event('error');
    this.listeners.get('error')?.forEach((cb) => cb(event));
  }
}

const OriginalEventSource = (globalThis as unknown as { EventSource?: typeof EventSource })
  .EventSource;

beforeEach(() => {
  (globalThis as unknown as { EventSource: typeof FakeEventSource }).EventSource =
    FakeEventSource;
  FakeEventSource.latest = null;
});

afterEach(() => {
  (globalThis as unknown as { EventSource: typeof EventSource | undefined }).EventSource =
    OriginalEventSource;
});

function makeWrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

function seedStructure(client: QueryClient, projectId: string, offset: number) {
  const snap: StructureResponse = { offset, nodes: [], edges: [] };
  client.setQueryData(structureKeys.project(projectId), snap);
}

describe('useProjectEventStream', () => {
  it('opens an EventSource with since=<cached offset>', () => {
    const qc = new QueryClient();
    seedStructure(qc, 'p1', 42);
    renderHook(() => useProjectEventStream('p1'), { wrapper: makeWrapper(qc) });
    expect(FakeEventSource.latest).not.toBeNull();
    expect(FakeEventSource.latest!.url).toContain('/events/stream?since=42');
  });

  it('opens with since=0 when no snapshot is cached yet', () => {
    const qc = new QueryClient();
    renderHook(() => useProjectEventStream('p1'), { wrapper: makeWrapper(qc) });
    expect(FakeEventSource.latest!.url).toContain('since=0');
  });

  it('invalidates structure on any incoming event', () => {
    const qc = new QueryClient();
    seedStructure(qc, 'p1', 0);
    const spy = vi.spyOn(qc, 'invalidateQueries');
    renderHook(() => useProjectEventStream('p1'), { wrapper: makeWrapper(qc) });
    FakeEventSource.latest!.fire('delta', {
      offset: 1,
      event_type: 'NodeCreated',
      node_ids: ['comp_X'],
    });
    // At least one call was for structureKeys.project('p1').
    const calls = spy.mock.calls.map((c) => JSON.stringify(c[0]?.queryKey));
    expect(calls.some((k) => k.includes('structure') && k.includes('p1'))).toBe(true);
  });

  it('closes the EventSource on unmount', () => {
    const qc = new QueryClient();
    seedStructure(qc, 'p1', 0);
    const { unmount } = renderHook(() => useProjectEventStream('p1'), {
      wrapper: makeWrapper(qc),
    });
    const es = FakeEventSource.latest!;
    expect(es.closed).toBe(false);
    unmount();
    expect(es.closed).toBe(true);
  });

  it('invalidates structure on stream error (re-seed after reconnect)', () => {
    const qc = new QueryClient();
    seedStructure(qc, 'p1', 0);
    const spy = vi.spyOn(qc, 'invalidateQueries');
    renderHook(() => useProjectEventStream('p1'), { wrapper: makeWrapper(qc) });
    spy.mockClear();
    FakeEventSource.latest!.fireError();
    const calls = spy.mock.calls.map((c) => JSON.stringify(c[0]?.queryKey));
    expect(calls.some((k) => k.includes('structure') && k.includes('p1'))).toBe(true);
  });

  describe('Phase 11 queue events', () => {
    const QUEUE_EVENTS = [
      'QueueInstructionAppended',
      'QueueInstructionDiscarded',
      'QueueApplying',
      'QueueFailed',
    ];

    it.each(QUEUE_EVENTS)(
      '%s invalidates the queue list but not structure',
      (eventType) => {
        const qc = new QueryClient();
        seedStructure(qc, 'p1', 0);
        const spy = vi.spyOn(qc, 'invalidateQueries');
        renderHook(() => useProjectEventStream('p1'), { wrapper: makeWrapper(qc) });
        spy.mockClear();

        FakeEventSource.latest!.fire('delta', {
          offset: -1,
          event_type: eventType,
          node_ids: [],
        });

        const calls = spy.mock.calls.map((c) => JSON.stringify(c[0]?.queryKey));
        expect(calls.some((k) => k.includes('queue') && k.includes('p1'))).toBe(true);
        // Non-terminal queue events don't touch structure.
        expect(calls.some((k) => k.includes('structure') && k.includes('p1'))).toBe(false);
      },
    );

    it('QueueApplied also invalidates structure + per-tier detail for affected nodes', () => {
      const qc = new QueryClient();
      const snap: StructureResponse = {
        offset: 0,
        nodes: [{ id: 'comp_AAAAAAAA', tier: 'comp', parent_id: null }],
        edges: [],
      } as unknown as StructureResponse;
      qc.setQueryData(structureKeys.project('p1'), snap);

      const spy = vi.spyOn(qc, 'invalidateQueries');
      renderHook(() => useProjectEventStream('p1'), { wrapper: makeWrapper(qc) });
      spy.mockClear();

      FakeEventSource.latest!.fire('delta', {
        offset: -1,
        event_type: 'QueueApplied',
        node_ids: ['comp_AAAAAAAA'],
      });

      const calls = spy.mock.calls.map((c) => JSON.stringify(c[0]?.queryKey));
      expect(calls.some((k) => k.includes('queue') && k.includes('p1'))).toBe(true);
      expect(calls.some((k) => k.includes('structure') && k.includes('p1'))).toBe(true);
      // Tier detail for the affected comp was invalidated.
      expect(calls.some((k) => k.includes('comparch') && k.includes('comp_AAAAAAAA'))).toBe(true);
    });
  });
});
