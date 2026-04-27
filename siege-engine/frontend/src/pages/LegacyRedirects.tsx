import { useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useProjectStructure } from '../hooks/queries/useProjectStructure';

type ChildTier = 'fanin' | 'impl';

/**
 * Resolves old deep-link URLs to the new workspace nav scheme by
 * looking up the target node in the project's nav tree and
 * redirecting to ``/projects/:id?node=<resolved-id>``. The
 * resolver handles transient loading state (nav tree in flight)
 * and missing-target state (tier doesn't exist yet) cleanly —
 * falls back to the parent comp/sub id when the specific child
 * isn't minted, so the user still lands somewhere useful.
 */
function useLegacyRedirect(
  projectId: string | undefined,
  anchorId: string | undefined,
  childTier: ChildTier | null,
) {
  const { data: structure, isLoading } = useProjectStructure(projectId ?? '');
  const navigate = useNavigate();

  useEffect(() => {
    if (!projectId || !anchorId) return;
    if (isLoading || !structure) return;
    let targetId: string | null = null;
    if (childTier === null) {
      targetId = anchorId; // comparch / subcomparch → select the comp/sub itself
    } else {
      const child = structure.nodes.find(
        (n) => n.parent_id === anchorId && n.tier === childTier,
      );
      targetId = child?.id ?? anchorId; // fall back to parent if not minted yet
    }
    const dest =
      targetId === anchorId
        ? `/projects/${projectId}?node=${targetId}`
        : `/projects/${projectId}?node=${targetId}`;
    navigate(dest, { replace: true });
  }, [projectId, anchorId, childTier, isLoading, structure, navigate]);
}

function RedirectPlaceholder() {
  return (
    <div className="fixed inset-0 bg-gray-900 z-50 flex items-center justify-center text-gray-400 text-sm">
      Redirecting…
    </div>
  );
}

export function RedirectComponentComparch() {
  const { id, compId } = useParams<{ id: string; compId: string }>();
  useLegacyRedirect(id, compId, null);
  return <RedirectPlaceholder />;
}

export function RedirectComponentFanIn() {
  const { id, compId } = useParams<{ id: string; compId: string }>();
  useLegacyRedirect(id, compId, 'fanin');
  return <RedirectPlaceholder />;
}

export function RedirectComponentImpl() {
  const { id, compId } = useParams<{ id: string; compId: string }>();
  useLegacyRedirect(id, compId, 'impl');
  return <RedirectPlaceholder />;
}

export function RedirectSubcomponentSubcomparch() {
  const { id, subId } = useParams<{ id: string; subId: string }>();
  useLegacyRedirect(id, subId, null);
  return <RedirectPlaceholder />;
}

export function RedirectSubcomponentImpl() {
  const { id, subId } = useParams<{ id: string; subId: string }>();
  useLegacyRedirect(id, subId, 'impl');
  return <RedirectPlaceholder />;
}

export function RedirectToSynthetic({ target }: { target: string }) {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  useEffect(() => {
    if (!id) return;
    navigate(`/projects/${id}?node=${target}`, { replace: true });
  }, [id, target, navigate]);
  return <RedirectPlaceholder />;
}
