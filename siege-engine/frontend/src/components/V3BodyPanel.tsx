import { useQuery } from '@tanstack/react-query';
import * as siegeApi from '../api/siege';
import type { BodyScope } from '../api/siege';

interface Props {
  projectId: string;
  scope: BodyScope;
  title: string;
  hint?: string;
}

/**
 * Read-only substrate-body viewer for upload-imported (v3) projects.
 *
 * The legacy per-tier panels (FeatureExpansionPanel, RequirementsPanel,
 * SysarchPanel, ComparchPanel, SubcomparchPanel) all hit the old
 * SQLAlchemy backend's per-tier endpoints, which return 404 on upload
 * projects — those have no SQL rows, only git artifacts. This panel
 * is the v3-aware fallback: it asks the siege server for the body
 * file at the given scope and renders it as preformatted text.
 *
 * Renders as ``<pre>`` rather than markdown deliberately — the bodies
 * mix markdown headings with the inline XML grammar
 * (``<components>…<dependencies>…``) the substrate tier uses, and the
 * XML doesn't survive a markdown pass. Showing the artifact verbatim
 * matches the v3 spec's "artifacts are the source of truth" framing.
 */
export function V3BodyPanel({ projectId, scope, title, hint }: Props) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['v3-body', projectId, scope],
    queryFn: () => siegeApi.getBody(projectId, scope),
  });

  return (
    <div
      className="h-full overflow-auto"
      data-testid={`v3-body-${scope.tier}`}
    >
      <div className="max-w-4xl mx-auto px-6 py-6 space-y-4">
        <header className="space-y-1">
          <h2 className="text-lg font-semibold text-gray-100">{title}</h2>
          {hint && <p className="text-xs text-gray-500">{hint}</p>}
          {data?.body_path && (
            <p className="font-mono text-[11px] text-gray-600">
              {data.body_path}
            </p>
          )}
        </header>
        {isLoading && (
          <div className="text-xs text-gray-500 italic">Loading body…</div>
        )}
        {error && (
          <div className="text-xs text-red-400">
            Failed to load body
            {error instanceof Error ? `: ${error.message}` : ''}
          </div>
        )}
        {data && !data.found && (
          <div className="text-xs text-gray-500 italic">
            No body found at this scope — the substrate may not have been
            drafted yet.
          </div>
        )}
        {data && data.found && (
          <pre className="whitespace-pre-wrap break-words rounded border border-gray-800 bg-gray-950/60 p-4 text-xs text-gray-200 font-mono leading-relaxed">
            {data.body_text}
          </pre>
        )}
      </div>
    </div>
  );
}
