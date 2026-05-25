import { useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { DagCanvas } from '../components/graph/DagCanvas';
import { topLevelElements } from '../components/graph/elements';
import { fullDagStylesheet } from '../components/graph/stylesheet';
import { useProjectGraph } from '../hooks/queries/useProjectGraph';
import { useProject } from '../hooks/queries/useProjectQueries';
import { describeApiError } from '../lib/describeApiError';
import { v3ToLegacyStructure } from '../lib/v3ToLegacyStructure';
import type { ProjectGraph, V3Edge, V3Node } from '../api/siege';

/**
 * Diagnostics page for the v3 read pipeline.
 *
 * Hits the same ``/siege/api/get-project-graph`` endpoint
 * ``useStructureForViz`` does for upload projects, then walks the
 * data through every transform in the FullDagView pipeline so a "DAG
 * is empty" failure can be localized to a specific step:
 *
 *  1. Project lookup — does ``useProject`` return ``source: "upload"``?
 *  2. v3 graph response — what does ``build_project_graph`` actually return?
 *  3. Adapter — does ``v3ToLegacyStructure`` produce legacy-shape nodes?
 *  4. ``topLevelElements`` — how many cytoscape elements get emitted?
 *  5. ``DagCanvas`` — does the canvas render them?
 *
 * Each step's row count is shown; if a step's count drops to zero we
 * know where the data falls off.
 */
export function ProjectV3GraphPage() {
  const { id } = useParams<{ id: string }>();
  const projectId = id ?? '';
  const { data: project, isLoading: projectLoading } = useProject(projectId);
  const { data, isLoading, error } = useProjectGraph(projectId);

  return (
    <div className="min-h-screen bg-gray-900 text-white">
      <header className="border-b border-gray-700 px-6 py-4 flex items-center gap-4">
        <Link to={`/projects/${projectId}`} className="text-gray-400 hover:text-white text-sm">
          &larr; Back to project
        </Link>
        <span className="text-gray-500">/</span>
        <span className="text-sm">v3 pipeline diagnostics</span>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-6 space-y-5">
        <ProjectBanner
          project={project}
          projectLoading={projectLoading}
          projectId={projectId}
        />

        {isLoading && <p className="text-gray-400">Loading graph…</p>}
        {error != null && (
          <p className="text-red-400 text-sm">{describeApiError(error, 'Failed to load graph')}</p>
        )}
        {data && <Diagnostics data={data} />}
      </main>
    </div>
  );
}

function ProjectBanner({
  project,
  projectLoading,
  projectId,
}: {
  project: { id: string; name: string; source?: string } | undefined;
  projectLoading: boolean;
  projectId: string;
}) {
  return (
    <section className="rounded border border-gray-700 bg-gray-800/50 p-4 text-sm">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Stat label="Project" value={projectLoading ? '…' : (project?.name ?? '— not found —')} />
        <Stat label="ID" value={<span className="font-mono text-xs">{projectId}</span>} />
        <Stat
          label="source"
          value={
            project?.source ? (
              <SourcePill source={project.source} />
            ) : projectLoading ? (
              '…'
            ) : (
              <span className="text-amber-400">(missing — useStructureForViz will use legacy)</span>
            )
          }
        />
        <Stat
          label="Branch"
          value={
            project?.source === 'upload' ? (
              <span className="text-green-300">v3 (this page = same path)</span>
            ) : project?.source ? (
              <span className="text-blue-300">legacy SQL (this page bypasses to v3)</span>
            ) : (
              '…'
            )
          }
        />
      </div>
    </section>
  );
}

function Diagnostics({ data }: { data: ProjectGraph }) {
  const adapted = useMemo(() => v3ToLegacyStructure(data), [data]);
  const elements = useMemo(
    () => topLevelElements(adapted.nodes, adapted.edges),
    [adapted.nodes, adapted.edges],
  );
  const { id: projectId } = useParams<{ id: string }>();
  const { data: project } = useProject(projectId ?? '');

  const adaptedTierCounts = useMemo(
    () => countBy(adapted.nodes, (n) => n.tier),
    [adapted.nodes],
  );
  const adaptedKindCounts = useMemo(
    () => countBy(adapted.nodes, (n) => n.kind),
    [adapted.nodes],
  );
  const adaptedEdgeCounts = useMemo(
    () => countBy(adapted.edges, (e) => e.edge_type),
    [adapted.edges],
  );
  const elementTypeCounts = useMemo(() => {
    const out: Record<string, number> = { node: 0, edge: 0 };
    for (const el of elements) {
      const d = el.data as { type?: string; source?: string; target?: string };
      if (d.source && d.target) {
        out.edge += 1;
        const t = d['type'];
        if (t) out[`edge:${t}`] = (out[`edge:${t}`] ?? 0) + 1;
      } else {
        out.node += 1;
        const t = d.type ?? 'unknown';
        out[`node:${t}`] = (out[`node:${t}`] ?? 0) + 1;
      }
    }
    return out;
  }, [elements]);

  const report = useMemo(
    () =>
      buildReport({
        project,
        projectId: projectId ?? '',
        data,
        adapted,
        elementTypeCounts,
        adaptedTierCounts,
        adaptedKindCounts,
        adaptedEdgeCounts,
      }),
    [
      project,
      projectId,
      data,
      adapted,
      elementTypeCounts,
      adaptedTierCounts,
      adaptedKindCounts,
      adaptedEdgeCounts,
    ],
  );

  return (
    <div className="space-y-5">
      <CopyButton report={report} />

      <section className="rounded border border-gray-700 bg-gray-800/50 p-4 text-sm">
        <h2 className="text-base font-semibold mb-2">Pipeline counts</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
          <Stat label="1 — v3 nodes" value={String(data.nodes.length)} />
          <Stat label="1 — v3 edges" value={String(data.edges.length)} />
          <Stat label="2 — adapted nodes" value={String(adapted.nodes.length)} />
          <Stat label="2 — adapted edges" value={String(adapted.edges.length)} />
          <Stat
            label="3 — topLevelElements"
            value={`${elementTypeCounts.node} nodes + ${elementTypeCounts.edge} edges`}
          />
          <Stat label="ref" value={`${data.ref} @ ${data.ref_head_sha.slice(0, 8)}`} />
        </div>
        <div className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-3 text-xs text-gray-300">
          <KvLine label="Adapted tier" map={adaptedTierCounts} />
          <KvLine label="Adapted kind" map={adaptedKindCounts} />
          <KvLine label="Adapted edges" map={adaptedEdgeCounts} />
        </div>
        <div className="mt-3 text-xs text-gray-300">
          <KvLine
            label="Emitted element types"
            map={Object.fromEntries(
              Object.entries(elementTypeCounts).filter(([k]) => k.includes(':')),
            )}
          />
        </div>
        {adapted.nodes.length > 0 && elementTypeCounts.node === 0 && (
          <p className="mt-3 text-amber-300 text-xs">
            ⚠ Adapter produced {adapted.nodes.length} nodes but topLevelElements emitted zero —
            check tier mapping (feat/resp/comp top-level expected) and parent_id (top-level resp /
            comp must have parent_id=null).
          </p>
        )}
      </section>

      <section>
        <h2 className="text-base font-semibold mb-2">DAG render</h2>
        <p className="text-xs text-gray-400 mb-2">
          The same DagCanvas the workspace's FullDagView mounts, fed from this page's adapted data.
          If this renders correctly the v3 pipeline is fine and any "empty graph" on the workspace
          page is upstream of FullDagView.
        </p>
        <div className="h-[600px] rounded border border-gray-700 bg-gray-950">
          {elements.length > 0 ? (
            <DagCanvas elements={elements} stylesheet={fullDagStylesheet} />
          ) : (
            <div className="h-full flex items-center justify-center text-sm text-gray-500">
              topLevelElements is empty — nothing for cytoscape to draw.
            </div>
          )}
        </div>
      </section>

      <section>
        <h2 className="text-base font-semibold mb-2">Adapted nodes (post-v3ToLegacyStructure)</h2>
        <div className="overflow-x-auto rounded border border-gray-700">
          <table className="w-full text-sm">
            <thead className="bg-gray-800 text-gray-300">
              <tr>
                <Th>name</Th>
                <Th>tier</Th>
                <Th>kind</Th>
                <Th>parent</Th>
                <Th>has_pending_draft</Th>
                <Th>id</Th>
              </tr>
            </thead>
            <tbody>
              {adapted.nodes.map((n) => (
                <tr key={n.id} className="border-t border-gray-700/50">
                  <Td>{n.name || <span className="text-gray-500">—</span>}</Td>
                  <Td>{n.tier}</Td>
                  <Td>{n.kind}</Td>
                  <Td className="text-xs text-gray-400">{n.parent_id ?? '—'}</Td>
                  <Td>{n.has_pending_draft ? 'true' : 'false'}</Td>
                  <Td className="font-mono text-xs text-gray-400">{n.id}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <details className="rounded border border-gray-700 bg-gray-800/30 p-3">
        <summary className="cursor-pointer text-sm text-gray-300">
          Raw v3 nodes ({data.nodes.length})
        </summary>
        <RawNodesTable nodes={data.nodes} />
      </details>

      <details className="rounded border border-gray-700 bg-gray-800/30 p-3">
        <summary className="cursor-pointer text-sm text-gray-300">
          Raw v3 edges ({data.edges.length})
        </summary>
        <RawEdgesTable edges={data.edges} />
      </details>

      <details className="rounded border border-gray-700 bg-gray-800/30 p-3">
        <summary className="cursor-pointer text-sm text-gray-300">Raw JSON</summary>
        <pre className="mt-2 max-h-96 overflow-auto text-xs text-gray-200">
          {JSON.stringify(data, null, 2)}
        </pre>
      </details>
    </div>
  );
}

function RawNodesTable({ nodes }: { nodes: V3Node[] }) {
  return (
    <div className="overflow-x-auto mt-2">
      <table className="w-full text-sm">
        <thead className="bg-gray-800/60 text-gray-300">
          <tr>
            <Th>name</Th>
            <Th>kind</Th>
            <Th>tier</Th>
            <Th>parent</Th>
            <Th>status</Th>
            <Th>flags</Th>
          </tr>
        </thead>
        <tbody>
          {nodes.map((n) => (
            <tr key={n.id} className="border-t border-gray-700/50">
              <Td>{n.name || <span className="text-gray-500">—</span>}</Td>
              <Td>{n.kind}</Td>
              <Td className="text-xs text-gray-400">{n.tier}</Td>
              <Td className="text-xs text-gray-400">{n.parent_id ?? '—'}</Td>
              <Td>{n.status}</Td>
              <Td className="text-xs text-gray-400">
                {[n.is_foundation && 'foundation', n.implicit && 'implicit']
                  .filter(Boolean)
                  .join(', ') || '—'}
              </Td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RawEdgesTable({ edges }: { edges: V3Edge[] }) {
  return (
    <div className="overflow-x-auto mt-2">
      <table className="w-full text-sm">
        <thead className="bg-gray-800/60 text-gray-300">
          <tr>
            <Th>type</Th>
            <Th>source</Th>
            <Th>target</Th>
          </tr>
        </thead>
        <tbody>
          {edges.map((e) => (
            <tr key={e.id} className="border-t border-gray-700/50">
              <Td>{e.type}</Td>
              <Td className="font-mono text-xs text-gray-400">{e.source_id}</Td>
              <Td className="font-mono text-xs text-gray-400">{e.target_id}</Td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function countBy<T>(items: T[], key: (t: T) => string): Record<string, number> {
  return items.reduce<Record<string, number>>((acc, item) => {
    const k = key(item);
    acc[k] = (acc[k] ?? 0) + 1;
    return acc;
  }, {});
}

function KvLine({ label, map }: { label: string; map: Record<string, number> }) {
  const entries = Object.entries(map);
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-gray-500">{label}</div>
      <div className="mt-0.5 font-mono text-xs">
        {entries.length
          ? entries.map(([k, v]) => `${k}: ${v}`).join(' · ')
          : <span className="text-gray-500">—</span>}
      </div>
    </div>
  );
}

function SourcePill({ source }: { source: string }) {
  const color =
    source === 'upload' ? 'bg-amber-900/60 text-amber-200' : 'bg-blue-900/60 text-blue-200';
  return (
    <span className={`inline-block px-1.5 py-0.5 rounded text-xs font-mono ${color}`}>{source}</span>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-gray-500">{label}</div>
      <div className="mt-0.5 text-gray-100">{value}</div>
    </div>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="text-left px-3 py-2 font-medium">{children}</th>;
}

function CopyButton({ report }: { report: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'error'>('idle');
  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(report);
      setState('copied');
    } catch {
      setState('error');
    }
    setTimeout(() => setState('idle'), 1500);
  };
  return (
    <div className="flex items-center gap-3">
      <button
        type="button"
        onClick={onCopy}
        className="px-3 py-1.5 text-sm rounded border border-gray-600 bg-gray-800 hover:bg-gray-700"
      >
        {state === 'copied' ? 'Copied!' : state === 'error' ? 'Copy failed' : 'Copy diagnostics'}
      </button>
      <span className="text-xs text-gray-500">
        Pastable markdown report — project info + pipeline counts + every v3 node + edge.
      </span>
    </div>
  );
}

interface ReportInputs {
  project: { id: string; name: string; source?: string } | undefined;
  projectId: string;
  data: ProjectGraph;
  adapted: { nodes: { id: string; tier: string; kind: string; parent_id: string | null }[]; edges: { edge_type: string }[] };
  elementTypeCounts: Record<string, number>;
  adaptedTierCounts: Record<string, number>;
  adaptedKindCounts: Record<string, number>;
  adaptedEdgeCounts: Record<string, number>;
}

function buildReport(inp: ReportInputs): string {
  const { project, projectId, data, adapted, elementTypeCounts } = inp;
  const lines: string[] = [];

  lines.push(`# v3 diagnostics — ${project?.name ?? '(project not found)'}`);
  lines.push('');
  lines.push(`project_id: ${projectId}`);
  lines.push(`source: ${project?.source ?? '(missing)'}`);
  lines.push(`ref: ${data.ref} @ ${data.ref_head_sha.slice(0, 8)}`);
  lines.push('');

  lines.push('## Pipeline counts');
  lines.push(`- v3 nodes:      ${data.nodes.length}`);
  lines.push(`- v3 edges:      ${data.edges.length}`);
  lines.push(`- adapted nodes: ${adapted.nodes.length}`);
  lines.push(`- adapted edges: ${adapted.edges.length}`);
  lines.push(`- emitted nodes: ${elementTypeCounts.node ?? 0}`);
  lines.push(`- emitted edges: ${elementTypeCounts.edge ?? 0}`);
  lines.push('');

  lines.push('## Adapted distributions');
  lines.push(`- tier:  ${fmtKv(inp.adaptedTierCounts)}`);
  lines.push(`- kind:  ${fmtKv(inp.adaptedKindCounts)}`);
  lines.push(`- edges: ${fmtKv(inp.adaptedEdgeCounts)}`);
  lines.push('');

  lines.push('## topLevelElements emitted types');
  const emitTypes = Object.entries(elementTypeCounts).filter(([k]) => k.includes(':'));
  if (emitTypes.length === 0) {
    lines.push('(none)');
  } else {
    for (const [k, v] of emitTypes.sort()) lines.push(`- ${k}: ${v}`);
  }
  lines.push('');

  const warning =
    adapted.nodes.length > 0 && (elementTypeCounts.node ?? 0) === 0
      ? `⚠ Adapter has ${adapted.nodes.length} nodes but topLevelElements emitted zero — check tier mapping + parent_id alignment.`
      : null;
  if (warning) {
    lines.push('## Warnings');
    lines.push(warning);
    lines.push('');
  }

  lines.push('## v3 nodes');
  lines.push('| id | tier | kind | parent_id | name | status | flags |');
  lines.push('|----|------|------|-----------|------|--------|-------|');
  for (const n of data.nodes) {
    const flags = [n.is_foundation && 'foundation', n.implicit && 'implicit']
      .filter(Boolean)
      .join(',') || '-';
    lines.push(
      `| ${n.id} | ${n.tier} | ${n.kind} | ${n.parent_id ?? '-'} | ${escapeMd(n.name)} | ${n.status} | ${flags} |`,
    );
  }
  lines.push('');

  lines.push('## v3 edges');
  if (data.edges.length === 0) {
    lines.push('(none)');
  } else {
    lines.push('| type | source | target |');
    lines.push('|------|--------|--------|');
    for (const e of data.edges) {
      lines.push(`| ${e.type} | ${e.source_id} | ${e.target_id} |`);
    }
  }
  lines.push('');

  lines.push('## Adapted nodes (post-v3ToLegacyStructure)');
  lines.push('| id | tier | kind | parent_id |');
  lines.push('|----|------|------|-----------|');
  for (const n of adapted.nodes) {
    lines.push(`| ${n.id} | ${n.tier} | ${n.kind} | ${n.parent_id ?? '-'} |`);
  }
  lines.push('');

  return lines.join('\n');
}

function fmtKv(map: Record<string, number>): string {
  const entries = Object.entries(map);
  return entries.length ? entries.map(([k, v]) => `${k}=${v}`).join(', ') : '(none)';
}

function escapeMd(s: string): string {
  // Pipes break markdown tables; backslash-escape them. Names are
  // short free-form text, no other risky chars in practice.
  return s.replace(/\|/g, '\\|');
}

function Td({
  children,
  className = '',
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <td className={`px-3 py-1.5 ${className}`}>{children}</td>;
}
