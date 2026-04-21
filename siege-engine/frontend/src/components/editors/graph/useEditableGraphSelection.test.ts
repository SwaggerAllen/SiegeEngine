import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useEditableGraphSelection } from './useEditableGraphSelection';

describe('useEditableGraphSelection', () => {
  it('starts in idle', () => {
    const { result } = renderHook(() =>
      useEditableGraphSelection({ canConnect: () => true }),
    );
    expect(result.current.state).toEqual({ kind: 'idle' });
  });

  it('tap a node moves to source-selected', () => {
    const { result } = renderHook(() =>
      useEditableGraphSelection({ canConnect: () => true }),
    );
    act(() => result.current.onNodeTap('n1'));
    expect(result.current.state).toEqual({ kind: 'source-selected', sourceId: 'n1' });
  });

  it('tap the same node cancels back to idle', () => {
    const { result } = renderHook(() =>
      useEditableGraphSelection({ canConnect: () => true }),
    );
    act(() => result.current.onNodeTap('n1'));
    act(() => result.current.onNodeTap('n1'));
    expect(result.current.state).toEqual({ kind: 'idle' });
  });

  it('tap a valid target stages the edge', () => {
    const { result } = renderHook(() =>
      useEditableGraphSelection({ canConnect: () => true }),
    );
    act(() => result.current.onNodeTap('n1'));
    act(() => result.current.onNodeTap('n2'));
    expect(result.current.state).toEqual({
      kind: 'edge-staged',
      sourceId: 'n1',
      targetId: 'n2',
    });
  });

  it('tap an invalid target stays at source-selected', () => {
    const { result } = renderHook(() =>
      useEditableGraphSelection({
        canConnect: (_src, tgt) => tgt !== 'blocked',
      }),
    );
    act(() => result.current.onNodeTap('n1'));
    act(() => result.current.onNodeTap('blocked'));
    expect(result.current.state).toEqual({ kind: 'source-selected', sourceId: 'n1' });
  });

  it('background tap returns to idle from any state', () => {
    const { result } = renderHook(() =>
      useEditableGraphSelection({ canConnect: () => true }),
    );
    act(() => result.current.onNodeTap('n1'));
    act(() => result.current.onNodeTap('n2'));
    expect(result.current.state.kind).toBe('edge-staged');
    act(() => result.current.onBackgroundTap());
    expect(result.current.state).toEqual({ kind: 'idle' });
  });

  it('commit returns to idle', () => {
    const { result } = renderHook(() =>
      useEditableGraphSelection({ canConnect: () => true }),
    );
    act(() => result.current.onNodeTap('n1'));
    act(() => result.current.onNodeTap('n2'));
    act(() => result.current.commit());
    expect(result.current.state).toEqual({ kind: 'idle' });
  });

  it('edge tap flips to edge-tapped', () => {
    const { result } = renderHook(() =>
      useEditableGraphSelection({ canConnect: () => true }),
    );
    act(() => result.current.onEdgeTap('edge_1'));
    expect(result.current.state).toEqual({ kind: 'edge-tapped', edgeId: 'edge_1' });
  });

  it('tapping a node while in edge-staged restarts on that node', () => {
    const { result } = renderHook(() =>
      useEditableGraphSelection({ canConnect: () => true }),
    );
    act(() => result.current.onNodeTap('n1'));
    act(() => result.current.onNodeTap('n2'));
    expect(result.current.state.kind).toBe('edge-staged');
    act(() => result.current.onNodeTap('n3'));
    expect(result.current.state).toEqual({ kind: 'source-selected', sourceId: 'n3' });
  });

  it('tapping a node while in edge-tapped starts a fresh source', () => {
    const { result } = renderHook(() =>
      useEditableGraphSelection({ canConnect: () => true }),
    );
    act(() => result.current.onEdgeTap('edge_1'));
    act(() => result.current.onNodeTap('n1'));
    expect(result.current.state).toEqual({ kind: 'source-selected', sourceId: 'n1' });
  });
});
