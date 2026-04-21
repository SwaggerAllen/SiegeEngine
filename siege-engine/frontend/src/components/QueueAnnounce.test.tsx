import { act, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { Instruction } from '../api/queue';
import {
  announceInstruction,
  useQueueAnnounceStore,
} from '../lib/queueAnnounce';
import { QueueAnnounceRegion } from './QueueAnnounce';

describe('QueueAnnounceRegion', () => {
  it('renders an aria-live=polite sr-only region', () => {
    render(<QueueAnnounceRegion />);
    const region = screen.getByTestId('queue-announce-region');
    expect(region.getAttribute('aria-live')).toBe('polite');
    expect(region.getAttribute('aria-atomic')).toBe('true');
    expect(region.className).toContain('sr-only');
  });

  it('renders the announced prose for an enqueued instruction', () => {
    render(<QueueAnnounceRegion />);
    const ins: Instruction = {
      instruction_type: 'AddDependency',
      source_id: 'comp_A',
      source_name: 'Billing',
      target_id: 'comp_B',
      target_name: 'Payments',
    };
    act(() => announceInstruction(ins));
    expect(screen.getByTestId('queue-announce-region').textContent).toContain(
      'Queued: Add dependency: "Billing" → "Payments"',
    );
  });

  it('bumps the seq key so duplicate messages re-announce', () => {
    // Reset the store to a known state before asserting seq deltas.
    useQueueAnnounceStore.setState({ latestMessage: '', seq: 0 });
    const ins: Instruction = {
      instruction_type: 'RemoveDependency',
      source_id: 'comp_A',
      source_name: 'A',
      target_id: 'comp_B',
      target_name: 'B',
    };
    act(() => announceInstruction(ins));
    const seqAfterFirst = useQueueAnnounceStore.getState().seq;
    act(() => announceInstruction(ins));
    expect(useQueueAnnounceStore.getState().seq).toBe(seqAfterFirst + 1);
  });
});
