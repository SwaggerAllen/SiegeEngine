import { useMemo } from 'react';
import { useProjectStructure } from './useProjectStructure';

/**
 * Light wrapper over :func:`useProjectStructure` that derives the
 * feature list from the project's structure snapshot. Kept as a
 * named hook so consumers (``RequirementsPanel``) don't need to
 * know the projection shape.
 *
 * Previously this hook hit a dedicated ``/features`` GET and
 * polled during mint. Now the SSE stream triggers structure
 * refetches on ``NodeCreated``/``NodeDeleted``, so the derived
 * list stays fresh without its own poller.
 */
export function useFeatures(projectId: string) {
  const query = useProjectStructure(projectId);
  const features = useMemo(() => {
    const nodes = query.data?.nodes ?? [];
    return nodes
      .filter((n) => n.tier === 'feat')
      .sort((a, b) => a.display_order - b.display_order)
      .map((n) => ({
        id: n.id,
        name: n.name,
        content: n.content,
      }));
  }, [query.data]);
  return {
    ...query,
    data: query.data ? { features } : undefined,
  };
}
