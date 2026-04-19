import { useEffect, useState } from 'react';

function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rs = s % 60;
  if (m < 60) return `${m}m ${rs.toString().padStart(2, '0')}s`;
  const h = Math.floor(m / 60);
  const rm = m % 60;
  return `${h}h ${rm.toString().padStart(2, '0')}m`;
}

/**
 * Duration clock + PST start-time label rendered while a generation
 * or review job is running. Ticks once a second via a ``setInterval``
 * local to the component so the rest of the panel doesn't re-render
 * on every tick. ``startedAtIso`` is the backend-reported job
 * created_at (naive UTC ISO-8601); we parse it as UTC by appending
 * ``Z`` if the server didn't. Shared between the bootstrap draft
 * generation spinner and the AI self-review spinner so both loading
 * states present the same elapsed / start-time / attempt triple.
 */
export function GenerationClock({
  startedAtIso,
  currentAttempt,
  maxAttempts,
  variant = 'inline',
  testId = 'generation-clock',
}: {
  startedAtIso: string | null;
  currentAttempt: number | null;
  maxAttempts: number | null;
  variant?: 'inline' | 'block';
  testId?: string;
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!startedAtIso) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [startedAtIso]);

  if (!startedAtIso) return null;

  const iso = /[Zz]|[+-]\d\d:?\d\d$/.test(startedAtIso)
    ? startedAtIso
    : `${startedAtIso}Z`;
  const startMs = Date.parse(iso);
  if (Number.isNaN(startMs)) return null;

  const elapsed = (now - startMs) / 1000;
  const duration = formatDuration(elapsed);
  const startedLabel = new Date(startMs).toLocaleTimeString('en-US', {
    timeZone: 'America/Los_Angeles',
    hour: 'numeric',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
  });
  const attemptLabel =
    currentAttempt && maxAttempts
      ? `attempt ${currentAttempt} / ${maxAttempts}`
      : null;

  if (variant === 'block') {
    return (
      <div className="text-xs text-gray-400 text-center" data-testid={testId}>
        <div>Elapsed: {duration}</div>
        <div className="text-gray-500">started {startedLabel} PT</div>
        {attemptLabel && <div className="text-gray-500">{attemptLabel}</div>}
      </div>
    );
  }
  return (
    <span className="text-xs text-gray-400" data-testid={testId}>
      {duration} · started {startedLabel} PT
      {attemptLabel && <> · {attemptLabel}</>}
    </span>
  );
}
