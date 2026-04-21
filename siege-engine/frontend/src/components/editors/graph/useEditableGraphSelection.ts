import { useCallback, useState } from 'react';

/**
 * Two-tap edge-add state machine for the PR-11a graph editors.
 *
 * State progression driven by `onNodeTap` / `onEdgeTap` /
 * `onBackgroundTap` callbacks the `EditableGraph` wires:
 *
 * ```
 *    idle
 *      | onNodeTap(id)
 *      v
 *    source-selected(sourceId)
 *      | onNodeTap(target)    [if target is candidate]
 *      v
 *    edge-staged(sourceId, targetId)
 *      | onBackgroundTap / ESC / cancel()
 *      v
 *    idle
 * ```
 *
 * Rules:
 *
 * - Tapping the same node twice when it's already `selected-source`
 *   cancels (back to `idle`).
 * - Tapping an `invalid-target` (blocked by the editor's own
 *   rule function — cycle detection, parent cap, etc.) leaves the
 *   state at `source-selected` so the user can pick another
 *   candidate.
 * - `edge-staged` stays until the editor dispatches (via
 *   `commit()`) or the user cancels. The editor renders a "Queue
 *   add" button in its sidebar that calls `commit()` on click.
 *
 * `onEdgeTap(edgeId)` is a separate path that bypasses the
 * source/target state machine entirely and flips to
 * `edge-tapped(edgeId)` so the editor can offer "Queue remove".
 * Tapping another edge or background returns to `idle`.
 */

export type SelectionState =
  | { kind: 'idle' }
  | { kind: 'source-selected'; sourceId: string }
  | { kind: 'edge-staged'; sourceId: string; targetId: string }
  | { kind: 'edge-tapped'; edgeId: string };

export interface EditableGraphSelection {
  state: SelectionState;
  /** Tap a node. Routes by current state. */
  onNodeTap: (nodeId: string) => void;
  /** Tap an existing edge. Flips to `edge-tapped` for remove flow. */
  onEdgeTap: (edgeId: string) => void;
  /** Tap the background. Always returns to `idle`. */
  onBackgroundTap: () => void;
  /** Editor calls after it enqueues the staged edge. */
  commit: () => void;
  /** Manual cancel (e.g. ESC, sidebar cancel button). */
  cancel: () => void;
}

export interface UseEditableGraphSelectionOpts {
  /**
   * Predicate invoked when the user taps a potential target. Return
   * `true` if the edge `sourceId → targetId` can be added. Editors
   * use this for cycle detection, rule enforcement (e.g. "domain-
   * parent cap is 1-2"), and same-node guarding.
   *
   * When the predicate returns `false` the state stays at
   * `source-selected` — the user can try a different target. The
   * editor is responsible for styling the invalid targets via
   * `invalid-target` classes so the user knows which ones are
   * blocked before tapping.
   */
  canConnect: (sourceId: string, targetId: string) => boolean;
}

export function useEditableGraphSelection(
  opts: UseEditableGraphSelectionOpts,
): EditableGraphSelection {
  const [state, setState] = useState<SelectionState>({ kind: 'idle' });

  const onNodeTap = useCallback(
    (nodeId: string) => {
      setState((prev) => {
        if (prev.kind === 'idle' || prev.kind === 'edge-tapped') {
          return { kind: 'source-selected', sourceId: nodeId };
        }
        if (prev.kind === 'source-selected') {
          // Tapping the same node cancels.
          if (prev.sourceId === nodeId) return { kind: 'idle' };
          // Invalid target — stay at source-selected for retry.
          if (!opts.canConnect(prev.sourceId, nodeId)) return prev;
          return {
            kind: 'edge-staged',
            sourceId: prev.sourceId,
            targetId: nodeId,
          };
        }
        // edge-staged + another node tap → start a new source
        // selection on the tapped node (matches user intent:
        // "oh wait, I meant this one").
        return { kind: 'source-selected', sourceId: nodeId };
      });
    },
    [opts],
  );

  const onEdgeTap = useCallback((edgeId: string) => {
    setState({ kind: 'edge-tapped', edgeId });
  }, []);

  const onBackgroundTap = useCallback(() => {
    setState({ kind: 'idle' });
  }, []);

  const commit = useCallback(() => {
    setState({ kind: 'idle' });
  }, []);

  const cancel = useCallback(() => {
    setState({ kind: 'idle' });
  }, []);

  return { state, onNodeTap, onEdgeTap, onBackgroundTap, commit, cancel };
}
