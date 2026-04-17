import type { StructureNode } from '../api/structure';

interface Props {
  component: StructureNode;
}

/**
 * Read-only "what sysarch said about this component" view.
 *
 * Shown as the default landing tab on a top-level comp_* so the
 * user can review the role (techspec fragment) and api-intent
 * (pubapi fragment) sysarch committed at mint time, before
 * kicking off comparch generation. Pairs with the Subreqs tab
 * for cross-referencing while reviewing a pending subreqs draft.
 */
export function ComponentOverviewPanel({ component }: Props) {
  return (
    <div className="h-full overflow-auto">
      <div className="max-w-3xl mx-auto px-6 py-6 space-y-6">
        <header>
          <h2 className="text-lg font-semibold text-gray-100">{component.name}</h2>
          <p className="text-xs text-gray-500 mt-1">
            Sysarch-time role and api-intent for this component. Read-only —
            further edits happen through the downstream tiers.
          </p>
        </header>

        <FragmentSection
          label="Role"
          hint="What this component is responsible for, in sysarch's own words."
          body={component.techspec}
        />
        <FragmentSection
          label="API intent"
          hint="The external-facing contract sysarch declared for this component."
          body={component.pubapi}
        />
      </div>
    </div>
  );
}

function FragmentSection({
  label,
  hint,
  body,
}: {
  label: string;
  hint: string;
  body: string;
}) {
  const trimmed = body.trim();
  return (
    <section>
      <div className="flex items-baseline gap-2 mb-2">
        <h3 className="text-sm font-semibold text-gray-200">{label}</h3>
        <span className="text-[11px] text-gray-500">{hint}</span>
      </div>
      {trimmed ? (
        <div className="text-sm text-gray-300 space-y-3">
          {splitParagraphs(trimmed).map((p, i) => (
            <p key={i} className="whitespace-pre-wrap">
              {p}
            </p>
          ))}
        </div>
      ) : (
        <p className="text-xs text-gray-500 italic">
          Not yet populated. Sysarch mint writes this fragment when the sysarch
          draft is approved.
        </p>
      )}
    </section>
  );
}

function splitParagraphs(s: string): string[] {
  return s
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter((p) => p.length > 0);
}
