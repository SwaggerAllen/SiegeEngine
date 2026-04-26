import { useMemo } from 'react';
import type { StructureNode } from '../api/structure';
import { useProjectStructure } from '../hooks/queries/useProjectStructure';

interface Props {
  projectId: string;
  component: StructureNode;
}

interface CompRef {
  id: string;
  name: string;
  kind: string;
}

/**
 * Read-only "what sysarch said about this component" view.
 *
 * Shows the component's role (techspec fragment), api-intent
 * (pubapi fragment), and its sysarch-time graph relations:
 * outbound + inbound dependency edges, and domain-parent edges
 * (presents/presented-by). The fragments are sysarch-mint output;
 * the relations let the user spot mistakes in the as-designed
 * topology before kicking off comparch.
 */
export function ComponentOverviewPanel({ projectId, component }: Props) {
  const { data: structure } = useProjectStructure(projectId);

  const relations = useMemo(() => {
    if (!structure) {
      return {
        outboundDeps: [] as CompRef[],
        inboundDeps: [] as CompRef[],
        domainParents: [] as CompRef[],
        presentingChildren: [] as CompRef[],
      };
    }
    const compById = new Map<string, StructureNode>();
    for (const n of structure.nodes) {
      compById.set(n.id, n);
    }
    const ref = (id: string): CompRef | null => {
      const n = compById.get(id);
      if (!n || n.tier !== 'comp' || n.parent_id !== null) return null;
      return { id: n.id, name: n.name, kind: n.kind };
    };
    const outbound: CompRef[] = [];
    const inbound: CompRef[] = [];
    const parents: CompRef[] = [];
    const children: CompRef[] = [];
    for (const e of structure.edges) {
      if (e.edge_type === 'dependency') {
        if (e.source_id === component.id) {
          const r = ref(e.target_id);
          if (r) outbound.push(r);
        } else if (e.target_id === component.id) {
          const r = ref(e.source_id);
          if (r) inbound.push(r);
        }
      } else if (e.edge_type === 'domain_parent') {
        // Direction: source = presentational comp, target = domain comp it presents.
        if (e.source_id === component.id) {
          const r = ref(e.target_id);
          if (r) parents.push(r);
        } else if (e.target_id === component.id) {
          const r = ref(e.source_id);
          if (r) children.push(r);
        }
      }
    }
    const byName = (a: CompRef, b: CompRef) => a.name.localeCompare(b.name);
    return {
      outboundDeps: outbound.sort(byName),
      inboundDeps: inbound.sort(byName),
      domainParents: parents.sort(byName),
      presentingChildren: children.sort(byName),
    };
  }, [structure, component.id]);

  return (
    <div className="h-full overflow-auto">
      <div className="max-w-3xl mx-auto px-6 py-6 space-y-6">
        <header>
          <h2 className="text-lg font-semibold text-gray-100">{component.name}</h2>
          <p className="text-xs text-gray-500 mt-1">
            Sysarch-time role, api-intent, and graph relations for this
            component. Read-only — further edits happen through the downstream
            tiers and the structural-edit panels.
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
        <RelationSection
          label="Depends on"
          hint="Sibling components this one consumes (outbound dependency edges)."
          comps={relations.outboundDeps}
          emptyHint="No outbound dependencies."
          testId="overview-outbound-deps"
        />
        <RelationSection
          label="Depended on by"
          hint="Sibling components that consume this one (inbound dependency edges)."
          comps={relations.inboundDeps}
          emptyHint="Nothing depends on this component."
          testId="overview-inbound-deps"
        />
        {component.kind === 'presentational' && (
          <RelationSection
            label="Presents"
            hint="Domain components this presentational component fronts (domain_parent edges)."
            comps={relations.domainParents}
            emptyHint="No domain-parent edges declared."
            testId="overview-domain-parents"
          />
        )}
        {relations.presentingChildren.length > 0 && (
          <RelationSection
            label="Presented by"
            hint="Presentational components that front this domain (inbound domain_parent edges)."
            comps={relations.presentingChildren}
            emptyHint=""
            testId="overview-presenting-children"
          />
        )}
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

function RelationSection({
  label,
  hint,
  comps,
  emptyHint,
  testId,
}: {
  label: string;
  hint: string;
  comps: CompRef[];
  emptyHint: string;
  testId: string;
}) {
  return (
    <section data-testid={testId}>
      <div className="flex items-baseline gap-2 mb-2">
        <h3 className="text-sm font-semibold text-gray-200">{label}</h3>
        <span className="text-[11px] text-gray-500">{hint}</span>
      </div>
      {comps.length === 0 ? (
        emptyHint ? (
          <p className="text-xs text-gray-500 italic">{emptyHint}</p>
        ) : null
      ) : (
        <ul className="flex flex-wrap gap-1.5">
          {comps.map((c) => (
            <li
              key={c.id}
              className="inline-flex items-center gap-1.5 rounded border border-gray-700/60 bg-gray-900/40 px-2 py-1 text-xs"
            >
              <span
                className={`h-2 w-2 rounded-full ${
                  c.kind === 'presentational' ? 'bg-violet-400/80' : 'bg-emerald-400/80'
                }`}
                aria-hidden="true"
              />
              <span className="text-gray-200">{c.name}</span>
              <span className="font-mono text-[10px] text-gray-500">{c.id}</span>
            </li>
          ))}
        </ul>
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
