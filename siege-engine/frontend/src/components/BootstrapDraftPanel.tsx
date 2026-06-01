import { useState } from 'react';
import type {
  BodyResponse,
  ScopeStateResponse,
  ScopeStatus,
} from '../api/siege';

/**
 * Read-only per-tier panel shell — the v3 shape.
 *
 * Renders the substrate's per-scope state (status badge + approval
 * footer), the draft body (when present), the review body (when
 * present), and an "Open in Claude Code" hint footer naming the
 * skill the user should invoke to act on this scope.
 *
 * The bodies mix markdown headings with the inline XML grammar the
 * substrate tiers use; rendering them as ``<pre>`` shows the
 * artifact verbatim, matching the v3 spec's "artifacts are the
 * source of truth" framing. (V3BodyPanel does the same — they
 * share a rendering convention.)
 *
 * The four-state generate / review / approve lifecycle UI that used
 * to live here moved to Claude Code skills. The dashboard's job is
 * to surface what's on disk, plus a pointer to where the write
 * surface lives.
 */
export interface BootstrapDraftPanelProps {
  scopeName: string;
  state: ScopeStateResponse | undefined;
  draftBody: BodyResponse | undefined;
  reviewBody: BodyResponse | undefined;
  isLoading: boolean;
  error: unknown;
  /**
   * One-line hint shown in the footer pointing the user at the
   * Claude Code skill they'd invoke to act on this scope (e.g.
   * ``/draft-comparch <comp_id>`` or ``/approve-comparch <comp_id>``
   * depending on status). Optional — if unset, the footer is
   * suppressed.
   */
  skillHint?: string;
  /** Human-readable label for the tier — shown in the empty state. */
  tierLabel: string;
}

const STATUS_LABEL: Record<ScopeStatus, string> = {
  absent: 'Absent',
  drafted: 'Drafted',
  reviewed: 'Reviewed',
  approved: 'Approved',
};

const STATUS_CHIP_CLASS: Record<ScopeStatus, string> = {
  absent: 'border-gray-700 text-gray-400',
  drafted: 'border-amber-700 text-amber-300',
  reviewed: 'border-blue-700 text-blue-300',
  approved: 'border-emerald-700 text-emerald-300',
};

function StatusChip({ status }: { status: ScopeStatus }) {
  return (
    <span
      className={`px-2 py-0.5 text-xs uppercase tracking-wide rounded border ${STATUS_CHIP_CLASS[status]}`}
    >
      {STATUS_LABEL[status]}
    </span>
  );
}

function CopyButton({ content, label = 'Copy' }: { content: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        navigator.clipboard.writeText(content).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 2000);
        });
      }}
      className="px-3 py-1 text-xs rounded border border-gray-700 text-gray-400 hover:bg-gray-800 hover:text-gray-200"
    >
      {copied ? 'Copied' : label}
    </button>
  );
}

function BodyBlock({
  heading,
  body,
  emptyHint,
}: {
  heading: string;
  body: BodyResponse | undefined;
  emptyHint: string;
}) {
  const found = body?.found === true;
  return (
    <section className="space-y-2">
      <header className="flex items-baseline justify-between gap-3">
        <h3 className="text-sm font-semibold text-gray-200">{heading}</h3>
        {body?.body_path && (
          <span className="font-mono text-[11px] text-gray-600 truncate" title={body.body_path}>
            {body.body_path}
          </span>
        )}
      </header>
      {!found ? (
        <p className="text-xs text-gray-500 italic">{emptyHint}</p>
      ) : (
        <>
          <pre
            className="whitespace-pre-wrap break-words rounded border border-gray-800 bg-gray-950/60 p-4 text-xs text-gray-200 font-mono leading-relaxed"
            data-testid={`body-${heading.toLowerCase().replace(/\s+/g, '-')}`}
          >
            {body!.body_text}
          </pre>
          <CopyButton content={body!.body_text} />
        </>
      )}
    </section>
  );
}

function ApprovalLine({ state }: { state: ScopeStateResponse }) {
  if (!state.approval) return null;
  return (
    <p className="text-xs text-emerald-300/80">
      Approved at {state.approval.approved_at} by {state.approval.approved_by}.
    </p>
  );
}

function ReviewScoreLine({ state }: { state: ScopeStateResponse }) {
  const score = state.review?.score;
  if (score == null) return null;
  return (
    <p className="text-xs text-blue-300/80">
      Review score: <span className="font-mono">{score}</span> · reviewed at{' '}
      {state.review!.reviewed_at}
    </p>
  );
}

function SkillHintFooter({ hint }: { hint: string }) {
  return (
    <footer className="pt-4 border-t border-gray-800 space-y-2">
      <p className="text-xs text-gray-500">
        Write actions live in Claude Code skills — invoke from your CC session.
      </p>
      <p className="font-mono text-xs text-gray-400 bg-gray-950/60 border border-gray-800 rounded px-3 py-2 inline-block">
        {hint}
      </p>
    </footer>
  );
}

export function BootstrapDraftPanel({
  scopeName,
  state,
  draftBody,
  reviewBody,
  isLoading,
  error,
  skillHint,
  tierLabel,
}: BootstrapDraftPanelProps) {
  if (isLoading) {
    return <div className="p-6 text-gray-400 text-sm">Loading {tierLabel}…</div>;
  }
  if (error) {
    const msg = error instanceof Error ? error.message : String(error);
    return (
      <div className="p-6 text-red-400 text-sm">
        Failed to load {tierLabel}: {msg}
      </div>
    );
  }
  const status = state?.status;
  if (!state || !state.found || !status || status === 'absent') {
    return (
      <div className="p-6 max-w-4xl mx-auto space-y-4">
        <header className="flex items-center justify-between gap-4">
          <h2 className="text-lg font-semibold">{scopeName}</h2>
          <StatusChip status="absent" />
        </header>
        <p className="text-sm text-gray-400 italic">
          No substrate state for this scope yet — invoke the draft skill in
          Claude Code to produce one.
        </p>
        {skillHint && <SkillHintFooter hint={skillHint} />}
      </div>
    );
  }
  return (
    <div className="p-6 max-w-4xl mx-auto space-y-5">
      <header className="flex items-center justify-between gap-4">
        <h2 className="text-lg font-semibold">{scopeName}</h2>
        <StatusChip status={status} />
      </header>
      <div className="space-y-1">
        <ApprovalLine state={state} />
        <ReviewScoreLine state={state} />
      </div>
      <BodyBlock
        heading="Draft"
        body={draftBody}
        emptyHint="No draft body — the scope hasn't been drafted yet."
      />
      {(status === 'reviewed' || status === 'approved') && (
        <BodyBlock
          heading="Review"
          body={reviewBody}
          emptyHint="No review body on disk."
        />
      )}
      {skillHint && <SkillHintFooter hint={skillHint} />}
    </div>
  );
}
