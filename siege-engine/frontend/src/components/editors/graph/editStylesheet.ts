// Additional stylesheet classes used by EditableGraph.
//
// Extends the Phase 10 `stylesheet.ts` with three selection-mode
// classes driven by the two-tap edge-add state machine in
// `useEditableGraphSelection`:
//
// - `selected-source` — the node the user tapped first; target
//   candidates are now highlighted.
// - `candidate-target` — nodes eligible to be the second tap
//   (creates a new edge via `AddDependency` / `AddDomainParent`
//   / etc.).
// - `invalid-target` — nodes that *would* be candidates but are
//   blocked (cycle, same-node, rule violation like "presentational
//   has 2 domain parents already"). Styled as dimmed + red-bordered
//   with a tooltip the editor wires up.
//
// Kept in its own file rather than appended to `stylesheet.ts` so
// the read-only DAG view and the editable graph don't step on
// each other's CSS. Both stylesheets compose cleanly — an editor
// view passes `[...fullDagStylesheet, ...editStylesheet]` and the
// edit classes layer on top.

import type { StylesheetCSS } from 'cytoscape';

export const editStylesheet: StylesheetCSS[] = [
  {
    selector: 'node.selected-source',
    css: {
      'border-width': 3,
      'border-color': '#60a5fa',
      'background-color': '#1e40af',
    },
  },
  {
    selector: 'node.candidate-target',
    css: {
      'border-width': 2,
      'border-color': '#34d399',
      'border-style': 'dashed',
    },
  },
  {
    selector: 'node.invalid-target',
    css: {
      'border-width': 2,
      'border-color': '#ef4444',
      'border-style': 'dashed',
      opacity: 0.55,
    },
  },
  // De-emphasize everything else when something is selected so the
  // candidate / invalid sets stand out.
  {
    selector: 'node.non-candidate',
    css: {
      opacity: 0.4,
    },
  },
  // Edge hover / selection highlight (used for tap-edge-to-remove).
  {
    selector: 'edge.selected-edge',
    css: {
      width: 4,
      'line-color': '#f87171',
      'target-arrow-color': '#f87171',
    },
  },
  // Multi-select class for the Decomposition editor's Merge flow.
  // Applied independently of the single-select state machine so
  // users can build up a set without losing the highlight when
  // they tap another node.
  {
    selector: 'node.multi-selected',
    css: {
      'border-width': 3,
      'border-color': '#f59e0b',
      'background-color': '#78350f',
    },
  },
];
