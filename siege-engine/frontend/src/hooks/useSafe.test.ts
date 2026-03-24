import { renderHook, act } from '@testing-library/react';
import { vi, describe, it, expect, beforeEach } from 'vitest';
import { useSafeCallback } from './useSafe';
import { useErrorLogStore } from '../store/errorLogStore';

vi.mock('../store/errorLogStore', () => ({
  useErrorLogStore: {
    getState: vi.fn(() => ({ pushError: vi.fn() })),
  },
}));

describe('useSafeCallback', () => {
  let pushError: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    pushError = vi.fn();
    vi.mocked(useErrorLogStore.getState).mockReturnValue({ pushError } as never);
  });

  it('returns the callback result when no error is thrown', () => {
    const { result } = renderHook(() =>
      useSafeCallback('test', () => 42, []),
    );
    expect(result.current()).toBe(42);
  });

  it('logs and re-throws synchronous errors', () => {
    const boom = new Error('sync boom');
    const { result } = renderHook(() =>
      useSafeCallback('test', () => { throw boom; }, []),
    );

    expect(() => result.current()).toThrow('sync boom');
    expect(pushError).toHaveBeenCalledWith('useSafeCallback(test)', boom);
  });

  it('logs and re-throws async errors, returning a rejecting promise', async () => {
    const boom = new Error('async boom');
    const { result } = renderHook(() =>
      useSafeCallback('test', async () => { throw boom; }, []),
    );

    await expect(result.current()).rejects.toThrow('async boom');
    expect(pushError).toHaveBeenCalledWith('useSafeCallback(test)', boom);
  });

  it('passes arguments through to the wrapped callback', () => {
    const { result } = renderHook(() =>
      useSafeCallback('test', (a: number, b: number) => a + b, []),
    );
    act(() => {
      expect(result.current(3, 4)).toBe(7);
    });
  });
});
