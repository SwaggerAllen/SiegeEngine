import { useEffect } from 'react';
import { useQueueAnnounceStore } from '../lib/queueAnnounce';

/**
 * Single aria-live region at the app root. Renders the latest
 * announce message from ``useQueueAnnounceStore`` as screen-
 * reader-only text so keyboard / SR users get verbal
 * confirmation when a tap-sequence enqueues an instruction.
 *
 * The store + helpers live in ``lib/queueAnnounce.ts`` so this
 * component file only exports a React component (keeps Fast
 * Refresh happy).
 */
export function QueueAnnounceRegion() {
  const message = useQueueAnnounceStore((s) => s.latestMessage);
  const seq = useQueueAnnounceStore((s) => s.seq);

  // Side effect only; ``key={seq}`` forces the DOM node to
  // re-mount so screen readers re-announce duplicates.
  useEffect(() => {
    // No-op.
  }, [seq]);

  return (
    <div
      aria-live="polite"
      aria-atomic="true"
      className="sr-only"
      data-testid="queue-announce-region"
      key={seq}
    >
      {message}
    </div>
  );
}
