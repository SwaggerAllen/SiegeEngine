import { createSafeStore } from '../store/createSafeStore';
import { renderInstruction, type Instruction } from '../api/queue';

/**
 * A11y announce pump for queue enqueues. Shared state lives
 * here (.ts file) so the Fast-Refresh lint rule doesn't
 * complain about a React component file exporting stores and
 * helpers alongside its component.
 *
 * Panels that enqueue call ``announceInstruction(ins)`` on the
 * mutation's success path. The store is a Zustand-safe-store
 * singleton so it can be written to from anywhere without
 * threading a ref through props.
 */

interface AnnounceState {
  latestMessage: string;
  // Bumped on every announce so the aria-live region re-announces
  // even when the same message lands twice in a row.
  seq: number;
  announce: (message: string) => void;
}

export const useQueueAnnounceStore = createSafeStore<AnnounceState>(
  'queueAnnounce',
  (set) => ({
    latestMessage: '',
    seq: 0,
    announce: (message: string) =>
      set((s) => ({ latestMessage: message, seq: s.seq + 1 })),
  }),
);

/** Convenience: format + announce a queued instruction. */
export function announceInstruction(instruction: Instruction) {
  const { instruction_type, ...payload } = instruction as Instruction & {
    instruction_type: string;
  };
  useQueueAnnounceStore.getState().announce(
    `Queued: ${renderInstruction(instruction_type, payload as Record<string, unknown>)}`,
  );
}
